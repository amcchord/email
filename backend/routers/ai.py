from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.models.email import Email
from backend.models.account import GoogleAccount
from backend.routers.auth import get_current_user
from backend.services.ai import AIService

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/analyze/{email_id}")
async def analyze_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Verify access
    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    acct = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == email.account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    if not acct.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Email not found")

    ai = AIService()
    analysis = await ai.analyze_email(email_id, db)
    if not analysis:
        raise HTTPException(status_code=500, detail="Analysis failed")

    return {
        "category": analysis.category,
        "priority": analysis.priority,
        "summary": analysis.summary,
        "action_items": analysis.action_items,
        "key_topics": analysis.key_topics,
        "sentiment": analysis.sentiment,
        "suggested_reply": analysis.suggested_reply,
        "context": analysis.context,
    }


@router.post("/analyze/thread/{thread_id}")
async def analyze_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Verify access
    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]

    result = await db.execute(
        select(Email).where(
            Email.gmail_thread_id == thread_id,
            Email.account_id.in_(account_ids),
        ).limit(1)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Thread not found")

    ai = AIService()
    analysis = await ai.analyze_thread(thread_id)
    if not analysis:
        raise HTTPException(status_code=500, detail="Thread analysis failed")

    return analysis


@router.post("/batch-categorize")
async def batch_categorize(
    email_ids: list[int],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Verify access
    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]

    # Queue for background processing
    from backend.workers.tasks import queue_analysis
    await queue_analysis(email_ids)

    return {"message": f"Queued {len(email_ids)} emails for AI analysis"}
