"""AI maintenance endpoints (reprocess, drop analyses, rebuild search index).

Split out of `backend/routers/ai.py` to keep individual files reviewable. All
endpoints register on the same `router` instance defined in
`backend.routers.ai`, so URL paths are unchanged.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis
from backend.models.email import Email
from backend.models.user import User
from backend.routers.ai import (
    router,
    _get_user_account_ids,
    set_ai_progress,
)
from backend.routers.auth import get_current_user
from backend.services.ai import get_model_for_user

logger = logging.getLogger(__name__)


@router.post("/reprocess")
async def reprocess_emails(
    body: dict = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reprocess emails that were analyzed with a different model.

    Deletes existing analyses where model_used != the target model
    and re-queues them for analysis.
    """
    if body is None:
        body = {}

    target_model = body.get("model")
    if not target_model:
        target_model = await get_model_for_user(user.id)

    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        return {"queued": 0, "model": target_model, "message": "No accounts found"}

    account_filter = Email.account_id.in_(account_ids)

    # Limit to the newest 1000 emails so a single click doesn't hammer the
    # worker queue with the entire mailbox.
    stale_result = await db.execute(
        select(AIAnalysis.id, AIAnalysis.email_id)
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(
            account_filter,
            AIAnalysis.model_used != target_model,
        )
        .order_by(desc(Email.date))
        .limit(1000)
    )
    stale_rows = stale_result.all()

    if not stale_rows:
        return {
            "queued": 0,
            "model": target_model,
            "message": "All emails already processed with this model",
        }

    stale_ids = [r[0] for r in stale_rows]
    email_ids = [r[1] for r in stale_rows]

    await db.execute(delete(AIAnalysis).where(AIAnalysis.id.in_(stale_ids)))
    await db.commit()

    await set_ai_progress(user.id, "reprocess", len(email_ids), target_model)

    from backend.workers.tasks import queue_analysis
    for i in range(0, len(email_ids), 100):
        chunk = email_ids[i:i + 100]
        await queue_analysis(chunk)

    return {
        "queued": len(email_ids),
        "model": target_model,
        "message": f"Queued {len(email_ids)} emails for reprocessing with {target_model}",
    }


@router.delete("/analyses")
async def delete_ai_analyses(
    rebuild_days: int = Query(
        None,
        description="If provided, immediately re-queue analysis for the last N days after deletion.",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Drop all AI analyses for the user's accounts.

    Optionally rebuild by re-queuing auto-categorization for a given date range.
    """
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"deleted": 0, "message": "No accounts found"}

    account_filter = Email.account_id.in_(account_ids)

    delete_count = await db.scalar(
        select(func.count(AIAnalysis.id))
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(account_filter)
    ) or 0

    if delete_count > 0:
        analysis_ids_subquery = (
            select(AIAnalysis.id)
            .join(Email, Email.id == AIAnalysis.email_id)
            .where(account_filter)
        )
        await db.execute(
            delete(AIAnalysis).where(AIAnalysis.id.in_(analysis_ids_subquery))
        )
        await db.commit()

    result = {
        "deleted": delete_count,
        "message": f"Deleted {delete_count} AI analyses",
    }

    if rebuild_days is not None and delete_count > 0:
        since_date = (
            datetime.now(timezone.utc) - timedelta(days=rebuild_days)
            if rebuild_days > 0 else None
        )

        where_clauses = [
            account_filter,
            Email.is_trash == False,
            Email.is_spam == False,
        ]
        if since_date is not None:
            where_clauses.append(Email.date >= since_date)

        rebuild_count = await db.scalar(
            select(func.count(Email.id)).where(*where_clauses)
        ) or 0

        if rebuild_count > 0:
            model = await get_model_for_user(user.id)
            await set_ai_progress(user.id, "categorize", rebuild_count, model)

            from backend.workers.tasks import queue_auto_categorize
            for account_id in account_ids:
                await queue_auto_categorize(
                    account_id,
                    days=rebuild_days if rebuild_days > 0 else None,
                )

        label = f"last {rebuild_days} days" if rebuild_days > 0 else "all time"
        result["rebuild_queued"] = rebuild_count
        result["message"] += f". Queued rebuild of {rebuild_count} emails ({label})"

    return result


@router.post("/rebuild-search-index")
async def rebuild_search_index(
    account_id: int = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rebuild PostgreSQL full-text search vectors for emails."""
    from backend.services.search import SearchService

    if account_id:
        acct = await db.scalar(
            select(GoogleAccount.id).where(
                GoogleAccount.id == account_id,
                GoogleAccount.user_id == user.id,
            )
        )
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        await SearchService.rebuild_search_index(db, account_id=account_id)
        return {"message": f"Search index rebuilt for account {account_id}"}

    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]

    if not account_ids:
        return {"message": "No accounts found"}

    for aid in account_ids:
        await SearchService.rebuild_search_index(db, account_id=aid)

    return {"message": f"Search index rebuilt for {len(account_ids)} account(s)"}
