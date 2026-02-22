import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, asc, and_, cast, Date, literal
from sqlalchemy.dialects.postgresql import JSONB
import redis.asyncio as aioredis
from backend.database import get_db
from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
from backend.models.user import User
from backend.models.email import Email
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis
from backend.routers.auth import get_current_user
from backend.services.ai import AIService, get_model_for_user, get_custom_prompt_model_for_user
from backend.services.credentials import get_google_credentials
from backend.schemas.auth import DEFAULT_AI_PREFERENCES

router = APIRouter(prefix="/api/ai", tags=["ai"])

_AI_PROGRESS_TTL = 86400  # 24 hours


async def _get_redis():
    """Get a short-lived Redis connection."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def set_ai_progress(user_id: int, job_type: str, total: int, model: str):
    """Store a new AI processing job in Redis."""
    r = await _get_redis()
    try:
        meta_key = f"ai_progress:{user_id}"
        counter_key = f"ai_progress:{user_id}:processed"
        pipe = r.pipeline()
        pipe.set(meta_key, json.dumps({
            "type": job_type,
            "total": total,
            "model": model,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }), ex=_AI_PROGRESS_TTL)
        pipe.set(counter_key, 0, ex=_AI_PROGRESS_TTL)
        await pipe.execute()
    finally:
        await r.aclose()


async def increment_ai_progress(user_id: int):
    """Atomically increment the processed counter for a user's AI job."""
    r = await _get_redis()
    try:
        counter_key = f"ai_progress:{user_id}:processed"
        await r.incr(counter_key)
    finally:
        await r.aclose()


async def get_ai_progress(user_id: int) -> dict | None:
    """Read the current AI processing progress for a user."""
    r = await _get_redis()
    try:
        meta_key = f"ai_progress:{user_id}"
        counter_key = f"ai_progress:{user_id}:processed"
        pipe = r.pipeline()
        pipe.get(meta_key)
        pipe.get(counter_key)
        meta_raw, processed_raw = await pipe.execute()
        if not meta_raw:
            return None
        meta = json.loads(meta_raw)
        meta["processed"] = int(processed_raw or 0)
        return meta
    finally:
        await r.aclose()


async def clear_ai_progress(user_id: int):
    """Remove AI processing progress keys."""
    r = await _get_redis()
    try:
        meta_key = f"ai_progress:{user_id}"
        counter_key = f"ai_progress:{user_id}:processed"
        await r.delete(meta_key, counter_key)
    finally:
        await r.aclose()


async def _get_user_account_ids(db: AsyncSession, user: User) -> list[int]:
    """Get Google account IDs accessible by this user.

    Admin users get access to all active accounts.
    Regular users only see their own accounts.
    """
    if user.is_admin:
        acct_result = await db.execute(
            select(GoogleAccount.id).where(GoogleAccount.is_active == True)
        )
    else:
        acct_result = await db.execute(
            select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
        )
    return [r[0] for r in acct_result.all()]


@router.get("/stats")
async def get_ai_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get AI analysis statistics: total emails, analyzed counts, unanalyzed counts by date range."""
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {
            "total_emails": 0,
            "total_analyzed": 0,
            "models": {},
            "unanalyzed": {"30d": 0, "90d": 0, "1y": 0, "all": 0},
        }

    account_filter = Email.account_id.in_(account_ids)
    non_junk = and_(Email.is_trash == False, Email.is_spam == False)
    analyzed_subquery = select(AIAnalysis.email_id)

    now = datetime.now(timezone.utc)

    # Total emails (non-trash/spam)
    total_emails = await db.scalar(
        select(func.count(Email.id)).where(account_filter, non_junk)
    ) or 0

    # Total analyzed
    total_analyzed = await db.scalar(
        select(func.count(AIAnalysis.id))
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(account_filter, non_junk)
    ) or 0

    # Model breakdown
    model_result = await db.execute(
        select(AIAnalysis.model_used, func.count(AIAnalysis.id))
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(account_filter, non_junk)
        .group_by(AIAnalysis.model_used)
    )
    models = {r[0] or "unknown": r[1] for r in model_result.all()}

    # Unanalyzed counts by date range
    unanalyzed_counts = {}
    for label, days in [("30d", 30), ("90d", 90), ("1y", 365)]:
        since = now - timedelta(days=days)
        count = await db.scalar(
            select(func.count(Email.id)).where(
                account_filter,
                non_junk,
                ~Email.id.in_(analyzed_subquery),
                Email.date >= since,
            )
        ) or 0
        unanalyzed_counts[label] = count

    # All unanalyzed
    unanalyzed_counts["all"] = await db.scalar(
        select(func.count(Email.id)).where(
            account_filter,
            non_junk,
            ~Email.id.in_(analyzed_subquery),
        )
    ) or 0

    return {
        "total_emails": total_emails,
        "total_analyzed": total_analyzed,
        "models": models,
        "unanalyzed": unanalyzed_counts,
    }


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

    account_ids = await _get_user_account_ids(db, user)
    if email.account_id not in account_ids:
        raise HTTPException(status_code=404, detail="Email not found")

    # Load account description and email for context
    acct_result = await db.execute(
        select(GoogleAccount.description, GoogleAccount.email).where(GoogleAccount.id == email.account_id)
    )
    acct_row = acct_result.first()
    acct_desc = acct_row[0] if acct_row else None
    acct_email = acct_row[1] if acct_row else None

    model = await get_model_for_user(user.id)
    ai = AIService(model=model)
    analysis = await ai.analyze_email(
        email_id, db,
        user_context=user.about_me,
        account_description=acct_desc,
        account_email=acct_email,
    )
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
        "reply_options": analysis.reply_options,
        "context": analysis.context,
    }


@router.post("/analyze/thread/{thread_id}")
async def analyze_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Verify access
    account_ids = await _get_user_account_ids(db, user)

    result = await db.execute(
        select(Email).where(
            Email.gmail_thread_id == thread_id,
            Email.account_id.in_(account_ids),
        ).limit(1)
    )
    thread_email = result.scalar_one_or_none()
    if not thread_email:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Load account description for context
    acct_result = await db.execute(
        select(GoogleAccount.description).where(GoogleAccount.id == thread_email.account_id)
    )
    acct_desc = acct_result.scalar_one_or_none()

    model = await get_model_for_user(user.id)
    ai = AIService(model=model)
    analysis = await ai.analyze_thread(
        thread_id,
        user_context=user.about_me,
        account_description=acct_desc,
    )
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
    account_ids = await _get_user_account_ids(db, user)

    # Queue for background processing
    from backend.workers.tasks import queue_analysis
    await queue_analysis(email_ids)

    return {"message": f"Queued {len(email_ids)} emails for AI analysis"}


@router.get("/trends")
async def get_ai_trends(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get AI-powered trends and insights."""
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {
            "needs_attention": [],
            "category_over_time": [],
            "top_topics": [],
            "urgent_senders": [],
            "summary": None,
            "total_analyzed": 0,
            "total_unanalyzed": 0,
        }

    account_filter = Email.account_id.in_(account_ids)

    # Total analyzed vs unanalyzed
    total_analyzed = await db.scalar(
        select(func.count(AIAnalysis.id))
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(account_filter)
    ) or 0

    total_emails = await db.scalar(
        select(func.count(Email.id)).where(account_filter)
    ) or 0

    total_unanalyzed = total_emails - total_analyzed

    # Needs attention: urgent + needs_response, unread, last 7 days
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    needs_attention_result = await db.execute(
        select(
            Email.id,
            Email.subject,
            Email.from_name,
            Email.from_address,
            Email.date,
            AIAnalysis.category,
            AIAnalysis.priority,
            AIAnalysis.summary,
        )
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .where(
            account_filter,
            Email.is_read == False,
            AIAnalysis.category.in_(["needs_response", "urgent"]),
            Email.date >= seven_days_ago,
        )
        .order_by(desc(AIAnalysis.priority), desc(Email.date))
        .limit(20)
    )
    needs_attention = [
        {
            "id": row.id,
            "subject": row.subject,
            "from_name": row.from_name or row.from_address,
            "from_address": row.from_address,
            "date": row.date.isoformat() if row.date else None,
            "category": row.category,
            "priority": row.priority,
            "summary": row.summary,
        }
        for row in needs_attention_result.all()
    ]

    # Category distribution over time (last 14 days, by day)
    fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)
    cat_time_result = await db.execute(
        select(
            cast(Email.date, Date).label("day"),
            AIAnalysis.category,
            func.count(AIAnalysis.id).label("count"),
        )
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(account_filter, Email.date >= fourteen_days_ago)
        .group_by("day", AIAnalysis.category)
        .order_by("day")
    )
    category_over_time = [
        {"date": str(row.day), "category": row.category, "count": row.count}
        for row in cat_time_result.all()
    ]

    # Top topics from key_topics (aggregate from recent analyses)
    topic_result = await db.execute(
        select(AIAnalysis.key_topics)
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(account_filter, Email.date >= fourteen_days_ago)
        .where(AIAnalysis.key_topics.isnot(None))
        .limit(200)
    )
    topic_counts = {}
    for row in topic_result.all():
        topics = row.key_topics
        if isinstance(topics, list):
            for topic in topics:
                if topic:
                    key = topic.lower().strip()
                    topic_counts[key] = topic_counts.get(key, 0) + 1

    top_topics = sorted(
        [{"topic": k, "count": v} for k, v in topic_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:15]

    # Senders who send urgent/needs_response emails most
    urgent_senders_result = await db.execute(
        select(
            Email.from_address,
            Email.from_name,
            func.count(AIAnalysis.id).label("count"),
        )
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .where(
            account_filter,
            AIAnalysis.category.in_(["needs_response", "urgent"]),
        )
        .group_by(Email.from_address, Email.from_name)
        .order_by(func.count(AIAnalysis.id).desc())
        .limit(10)
    )
    urgent_senders = [
        {"address": row.from_address, "name": row.from_name or row.from_address, "count": row.count}
        for row in urgent_senders_result.all()
    ]

    # Smart summary
    summary_parts = []
    urgent_count = sum(1 for e in needs_attention if e["category"] == "urgent")
    response_count = sum(1 for e in needs_attention if e["category"] == "needs_response")
    if urgent_count > 0:
        summary_parts.append(f"{urgent_count} urgent email{'s' if urgent_count != 1 else ''}")
    if response_count > 0:
        summary_parts.append(f"{response_count} email{'s' if response_count != 1 else ''} needing response")
    if total_unanalyzed > 0:
        summary_parts.append(f"{total_unanalyzed} unanalyzed email{'s' if total_unanalyzed != 1 else ''}")

    summary = None
    if summary_parts:
        summary = "You have " + ", ".join(summary_parts) + "."

    return {
        "needs_attention": needs_attention,
        "category_over_time": category_over_time,
        "top_topics": top_topics,
        "urgent_senders": urgent_senders,
        "summary": summary,
        "total_analyzed": total_analyzed,
        "total_unanalyzed": total_unanalyzed,
    }


@router.post("/auto-categorize")
async def auto_categorize(
    days: int = Query(None, description="Number of days to look back (e.g. 30, 90, 365). Omit for all unanalyzed."),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Trigger auto-categorization of unanalyzed emails.

    Optionally filter by date range (days parameter). Without days,
    processes all unanalyzed emails.
    """
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        raise HTTPException(status_code=400, detail="No active accounts found")

    since_date = None
    if days is not None and days > 0:
        since_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Count unanalyzed emails across all accounts
    subquery = select(AIAnalysis.email_id)
    total_to_process = 0
    for account_id in account_ids:
        where_clauses = [
            Email.account_id == account_id,
            ~Email.id.in_(subquery),
            Email.is_trash == False,
            Email.is_spam == False,
        ]
        if since_date is not None:
            where_clauses.append(Email.date >= since_date)

        count = await db.scalar(
            select(func.count(Email.id)).where(*where_clauses)
        ) or 0
        total_to_process += count

    # Store progress in Redis
    if total_to_process > 0:
        model = await get_model_for_user(user.id)
        await set_ai_progress(user.id, "categorize", total_to_process, model)

    from backend.workers.tasks import queue_auto_categorize
    total_queued = 0
    for account_id in account_ids:
        await queue_auto_categorize(account_id, days=days)
        total_queued += 1

    label = f"last {days} days" if days else "all time"
    return {
        "message": f"Queued auto-categorization for {total_queued} account(s) ({total_to_process} emails to process, {label})",
        "accounts_queued": total_queued,
        "total_to_process": total_to_process,
    }


@router.get("/processing/status")
async def get_processing_status(
    user: User = Depends(get_current_user),
):
    """Get the current AI processing progress for the user."""
    progress = await get_ai_progress(user.id)

    if not progress:
        return {"active": False}

    total = progress.get("total", 0)
    processed = progress.get("processed", 0)

    # If processing is complete, clear the keys and signal completion
    if total > 0 and processed >= total:
        await clear_ai_progress(user.id)
        return {
            "active": False,
            "just_finished": True,
            "type": progress.get("type"),
            "total": total,
            "processed": processed,
            "model": progress.get("model"),
        }

    return {
        "active": True,
        "type": progress.get("type"),
        "total": total,
        "processed": processed,
        "model": progress.get("model"),
    }


@router.get("/needs-reply")
async def get_needs_reply(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    exclude_category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get emails that the user should respond to."""
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"emails": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)

    # Correlated subquery: check whether a sent email exists in the same
    # thread with a date AFTER the candidate "needs reply" email.  This
    # avoids the old bug where any sent message in the thread (including
    # the user's original outbound message) would blanket-exclude the
    # whole thread.
    from sqlalchemy.orm import aliased
    SentEmail = aliased(Email, flat=True)
    has_later_reply = (
        select(literal(1))
        .where(
            SentEmail.gmail_thread_id == Email.gmail_thread_id,
            SentEmail.account_id.in_(account_ids),
            SentEmail.is_sent == True,
            SentEmail.is_trash == False,
            SentEmail.date > Email.date,
        )
        .correlate(Email)
        .exists()
    )

    # Cross-thread reply detection: check whether a sent email's
    # In-Reply-To header matches this email's Message-ID.  This catches
    # replies that Gmail placed in a different thread (e.g. after a
    # threadId 404 retry or subject change).  Deterministic -- if B's
    # In-Reply-To equals A's Message-ID, B IS a reply to A.
    SentEmail2 = aliased(Email, flat=True)
    has_direct_reply_to = (
        select(literal(1))
        .where(
            SentEmail2.in_reply_to == Email.message_id_header,
            SentEmail2.account_id.in_(account_ids),
            SentEmail2.is_sent == True,
            SentEmail2.is_trash == False,
            Email.message_id_header.isnot(None),
        )
        .correlate(Email)
        .exists()
    )

    # Inner query: use DISTINCT ON (gmail_thread_id) to keep only the
    # latest "needs reply" email per thread.  DISTINCT ON requires the
    # ORDER BY to start with the DISTINCT ON columns.
    deduped_by_thread = (
        select(
            Email.id,
            Email.subject,
            Email.from_name,
            Email.from_address,
            Email.date,
            Email.snippet,
            Email.is_read,
            Email.gmail_thread_id,
            Email.message_id_header,
            GoogleAccount.email.label("account_email"),
            AIAnalysis.category,
            AIAnalysis.priority,
            AIAnalysis.summary,
            AIAnalysis.suggested_reply,
            AIAnalysis.reply_options,
        )
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .where(
            account_filter,
            AIAnalysis.needs_reply == True,
            AIAnalysis.needs_reply_ignored == False,
            # Exclude snoozed emails (snoozed_until is NULL or in the past)
            (AIAnalysis.needs_reply_snoozed_until == None) | (AIAnalysis.needs_reply_snoozed_until <= datetime.now(timezone.utc)),
            Email.is_trash == False,
            Email.is_spam == False,
            AIAnalysis.is_subscription == False,
            ~has_later_reply,
            ~has_direct_reply_to,
            *([AIAnalysis.category != exclude_category] if exclude_category else []),
        )
        .distinct(Email.gmail_thread_id)
        .order_by(Email.gmail_thread_id, desc(Email.date))
    ).subquery()

    # Second dedup layer: collapse cross-account duplicates.  The same
    # email delivered to multiple connected accounts shares the same
    # Message-ID header but gets different gmail_thread_ids.  COALESCE
    # falls back to gmail_thread_id when message_id_header is NULL.
    dedup_key = func.coalesce(
        deduped_by_thread.c.message_id_header,
        deduped_by_thread.c.gmail_thread_id,
    )
    deduped = (
        select(deduped_by_thread)
        .distinct(dedup_key)
        .order_by(dedup_key, desc(deduped_by_thread.c.date))
    ).subquery()

    # Count total (after dedup)
    count_result = await db.scalar(
        select(func.count()).select_from(deduped)
    )
    total = count_result or 0

    # Outer query: re-sort by date descending for display and paginate
    result = await db.execute(
        select(deduped)
        .order_by(desc(deduped.c.date))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    now_utc = datetime.now(timezone.utc)
    thirty_days_ago = now_utc - timedelta(days=30)

    emails = []
    for row in result.all():
        category = row.category
        priority = row.priority

        # Emails older than 30 days can't still be urgent – mark as expired
        if row.date and row.date < thirty_days_ago:
            if category in ("urgent", "needs_response"):
                category = "expired"
            priority = 0

        emails.append({
            "id": row.id,
            "subject": row.subject,
            "from_name": row.from_name or row.from_address,
            "from_address": row.from_address,
            "date": row.date.isoformat() if row.date else None,
            "snippet": row.snippet,
            "is_read": row.is_read,
            "gmail_thread_id": row.gmail_thread_id,
            "account_email": row.account_email,
            "category": category,
            "priority": priority,
            "summary": row.summary,
            "suggested_reply": row.suggested_reply,
            "reply_options": row.reply_options,
        })

    return {"emails": emails, "total": total}


@router.post("/needs-reply/{email_id}/ignore")
async def ignore_needs_reply(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a needs-reply email as ignored so it no longer appears in the list."""
    account_ids = await _get_user_account_ids(db, user)
    result = await db.execute(
        select(AIAnalysis)
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(AIAnalysis.email_id == email_id, Email.account_id.in_(account_ids))
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Email not found")
    analysis.needs_reply_ignored = True
    await db.commit()
    return {"ok": True}


@router.post("/needs-reply/{email_id}/unignore")
async def unignore_needs_reply(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore an ignored needs-reply email back to the active list."""
    account_ids = await _get_user_account_ids(db, user)
    result = await db.execute(
        select(AIAnalysis)
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(AIAnalysis.email_id == email_id, Email.account_id.in_(account_ids))
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Email not found")
    analysis.needs_reply_ignored = False
    await db.commit()
    return {"ok": True}


@router.post("/needs-reply/{email_id}/snooze")
async def snooze_needs_reply(
    email_id: int,
    duration: str = Query(..., pattern="^(1h|3h|tomorrow|next_week)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Snooze a needs-reply email for a preset duration."""
    account_ids = await _get_user_account_ids(db, user)
    result = await db.execute(
        select(AIAnalysis)
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(AIAnalysis.email_id == email_id, Email.account_id.in_(account_ids))
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Email not found")

    now = datetime.now(timezone.utc)
    if duration == "1h":
        snooze_until = now + timedelta(hours=1)
    elif duration == "3h":
        snooze_until = now + timedelta(hours=3)
    elif duration == "tomorrow":
        tomorrow = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        snooze_until = tomorrow
    elif duration == "next_week":
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = (now + timedelta(days=days_until_monday)).replace(hour=9, minute=0, second=0, microsecond=0)
        snooze_until = next_monday
    else:
        raise HTTPException(status_code=400, detail="Invalid duration")

    analysis.needs_reply_snoozed_until = snooze_until
    await db.commit()
    return {"ok": True, "snoozed_until": snooze_until.isoformat()}


@router.post("/needs-reply/{email_id}/unsnooze")
async def unsnooze_needs_reply(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove snooze from a needs-reply email so it reappears immediately."""
    account_ids = await _get_user_account_ids(db, user)
    result = await db.execute(
        select(AIAnalysis)
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(AIAnalysis.email_id == email_id, Email.account_id.in_(account_ids))
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Email not found")
    analysis.needs_reply_snoozed_until = None
    await db.commit()
    return {"ok": True}


@router.get("/needs-reply/ignored")
async def get_needs_reply_ignored(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get needs-reply emails that the user has ignored."""
    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        return {"emails": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)

    query = (
        select(
            Email.id,
            Email.subject,
            Email.from_name,
            Email.from_address,
            Email.date,
            Email.snippet,
            Email.is_read,
            Email.gmail_thread_id,
            AIAnalysis.category,
            AIAnalysis.priority,
            AIAnalysis.summary,
        )
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .where(
            account_filter,
            AIAnalysis.needs_reply == True,
            AIAnalysis.needs_reply_ignored == True,
            Email.is_trash == False,
            Email.is_spam == False,
        )
        .order_by(desc(Email.date))
    )

    count_result = await db.scalar(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result or 0

    result = await db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )

    emails = []
    for row in result.all():
        emails.append({
            "id": row.id,
            "subject": row.subject,
            "from_name": row.from_name or row.from_address,
            "from_address": row.from_address,
            "date": row.date.isoformat() if row.date else None,
            "snippet": row.snippet,
            "is_read": row.is_read,
            "gmail_thread_id": row.gmail_thread_id,
            "category": row.category,
            "priority": row.priority,
            "summary": row.summary,
        })

    return {"emails": emails, "total": total}


@router.get("/needs-reply/snoozed")
async def get_needs_reply_snoozed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get needs-reply emails that are currently snoozed."""
    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        return {"emails": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)
    now_utc = datetime.now(timezone.utc)

    query = (
        select(
            Email.id,
            Email.subject,
            Email.from_name,
            Email.from_address,
            Email.date,
            Email.snippet,
            Email.is_read,
            Email.gmail_thread_id,
            AIAnalysis.category,
            AIAnalysis.priority,
            AIAnalysis.summary,
            AIAnalysis.needs_reply_snoozed_until,
        )
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .where(
            account_filter,
            AIAnalysis.needs_reply == True,
            AIAnalysis.needs_reply_snoozed_until != None,
            AIAnalysis.needs_reply_snoozed_until > now_utc,
            Email.is_trash == False,
            Email.is_spam == False,
        )
        .order_by(asc(AIAnalysis.needs_reply_snoozed_until))
    )

    count_result = await db.scalar(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result or 0

    result = await db.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )

    emails = []
    for row in result.all():
        emails.append({
            "id": row.id,
            "subject": row.subject,
            "from_name": row.from_name or row.from_address,
            "from_address": row.from_address,
            "date": row.date.isoformat() if row.date else None,
            "snippet": row.snippet,
            "is_read": row.is_read,
            "gmail_thread_id": row.gmail_thread_id,
            "category": row.category,
            "priority": row.priority,
            "summary": row.summary,
            "snoozed_until": row.needs_reply_snoozed_until.isoformat() if row.needs_reply_snoozed_until else None,
        })

    return {"emails": emails, "total": total}


@router.get("/awaiting-response")
async def get_awaiting_response(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get emails the user sent that haven't received a reply yet.

    Filters out threads that are resolved (per AI ThreadDigest) and
    short reply-like closing messages that don't expect a response.
    """
    from sqlalchemy.orm import aliased
    from sqlalchemy import or_, func as sqla_func
    from backend.models.ai import ThreadDigest

    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"emails": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)

    # Find sent emails where no reply has been received in the same thread
    # after the sent email's date
    ReplyEmail = aliased(Email, flat=True)
    has_reply = (
        select(literal(1))
        .where(
            ReplyEmail.gmail_thread_id == Email.gmail_thread_id,
            ReplyEmail.account_id.in_(account_ids),
            ReplyEmail.is_sent == False,
            ReplyEmail.is_trash == False,
            ReplyEmail.date > Email.date,
        )
        .correlate(Email)
        .exists()
    )

    # AI classification: if expects_reply has been set to False, exclude.
    # LEFT JOIN with AIAnalysis to check the expects_reply field.
    SentAnalysis = aliased(AIAnalysis, flat=True)

    # Heuristic fallback for emails not yet classified by AI.
    # Strips quoted reply text from body_text before measuring length,
    # so replies like "Yes okay to lock it in!" aren't inflated by
    # quoted "On ... wrote:" blocks.
    PriorEmail = aliased(Email, flat=True)
    has_prior_received = (
        select(literal(1))
        .where(
            PriorEmail.gmail_thread_id == Email.gmail_thread_id,
            PriorEmail.account_id.in_(account_ids),
            PriorEmail.is_sent == False,
            PriorEmail.is_trash == False,
            PriorEmail.date < Email.date,
        )
        .correlate(Email)
        .exists()
    )
    # Strip quoted content: remove everything after "On ... wrote:" and
    # lines starting with ">", then measure the remaining length.
    raw_body = sqla_func.coalesce(Email.body_text, Email.snippet, '')
    stripped_body = sqla_func.regexp_replace(
        raw_body,
        r'\r?\nOn [^\n]+wrote:\s*[\s\S]*$',
        '',
        'n',
    )
    stripped_body = sqla_func.regexp_replace(
        stripped_body,
        r'\r?\n-- ?\r?\n[\s\S]*$',
        '',
        'n',
    )
    stripped_len = sqla_func.length(sqla_func.trim(stripped_body))

    is_short_closing_reply = and_(
        has_prior_received,
        stripped_len < 200,
    )

    # An email should be excluded when either:
    # (a) AI classified it as not expecting a reply, OR
    # (b) AI hasn't classified it yet but the heuristic says it's a
    #     short closing reply.
    ai_says_no_reply = (SentAnalysis.expects_reply == False)
    heuristic_closing = and_(
        SentAnalysis.expects_reply.is_(None),
        is_short_closing_reply,
    )
    should_exclude = or_(ai_says_no_reply, heuristic_closing)

    fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)

    # Use DISTINCT ON to get only the latest sent email per thread.
    # LEFT JOIN with ThreadDigest to exclude resolved threads and
    # LEFT JOIN with AIAnalysis to check expects_reply.
    deduped_by_thread = (
        select(
            Email.id,
            Email.subject,
            Email.to_addresses,
            Email.date,
            Email.snippet,
            Email.gmail_thread_id,
            Email.account_id,
            Email.message_id_header,
            GoogleAccount.email.label("account_email"),
        )
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .outerjoin(
            ThreadDigest,
            and_(
                ThreadDigest.gmail_thread_id == Email.gmail_thread_id,
                ThreadDigest.account_id == Email.account_id,
            ),
        )
        .outerjoin(
            SentAnalysis,
            SentAnalysis.email_id == Email.id,
        )
        .where(
            account_filter,
            Email.is_sent == True,
            Email.is_trash == False,
            Email.is_spam == False,
            Email.date >= fourteen_days_ago,
            ~has_reply,
            # Exclude threads the AI has marked as resolved
            or_(
                ThreadDigest.is_resolved == False,
                ThreadDigest.is_resolved.is_(None),
            ),
            # Exclude emails that don't expect a reply (AI or heuristic)
            ~should_exclude,
        )
        .distinct(Email.gmail_thread_id)
        .order_by(Email.gmail_thread_id, desc(Email.date))
    ).subquery()

    # Second dedup layer: collapse cross-account duplicates.  The same
    # sent email visible in multiple accounts shares the same Message-ID.
    ar_dedup_key = func.coalesce(
        deduped_by_thread.c.message_id_header,
        deduped_by_thread.c.gmail_thread_id,
    )
    deduped = (
        select(deduped_by_thread)
        .distinct(ar_dedup_key)
        .order_by(ar_dedup_key, desc(deduped_by_thread.c.date))
    ).subquery()

    # Count total
    count_result = await db.scalar(
        select(func.count()).select_from(deduped)
    )
    total = count_result or 0

    # Paginate
    result = await db.execute(
        select(deduped)
        .order_by(desc(deduped.c.date))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    emails = []
    thread_account_pairs = []
    for row in result.all():
        to_addrs = row.to_addresses or []
        # Extract first recipient name/address
        first_to = ""
        if to_addrs:
            first = to_addrs[0]
            if isinstance(first, dict):
                first_to = first.get("name") or first.get("address", "")
            else:
                first_to = str(first)

        emails.append({
            "id": row.id,
            "subject": row.subject,
            "to_name": first_to,
            "to_addresses": to_addrs,
            "date": row.date.isoformat() if row.date else None,
            "snippet": row.snippet,
            "gmail_thread_id": row.gmail_thread_id,
            "account_email": row.account_email,
        })
        thread_account_pairs.append((row.gmail_thread_id, row.account_id))

    # Ensure digest coverage: find awaiting-response threads that lack a
    # ThreadDigest and enqueue background generation so the next page load
    # benefits from the is_resolved filter.
    if thread_account_pairs:
        try:
            await _enqueue_missing_digests(db, thread_account_pairs)
        except Exception:
            logger.debug("Failed to enqueue missing digests", exc_info=True)

    return {"emails": emails, "total": total}


async def _enqueue_missing_digests(
    db: AsyncSession,
    thread_account_pairs: list[tuple[str, int]],
):
    """Enqueue digest generation for threads that don't have one yet.

    Only enqueues threads with 2+ messages (digest requirement).
    Runs as a fire-and-forget background task to avoid slowing the response.
    """
    from backend.models.ai import ThreadDigest

    if not thread_account_pairs:
        return

    # Deduplicate
    unique_pairs = list(set(thread_account_pairs))

    # Check which threads already have a digest
    thread_ids = [tid for tid, _ in unique_pairs]
    existing_result = await db.execute(
        select(
            ThreadDigest.gmail_thread_id,
            ThreadDigest.account_id,
        ).where(
            ThreadDigest.gmail_thread_id.in_(thread_ids),
        )
    )
    existing = set((r[0], r[1]) for r in existing_result.all())

    missing = [
        (tid, aid) for tid, aid in unique_pairs
        if (tid, aid) not in existing
    ]

    if not missing:
        return

    # Enqueue a background job to generate digests for the missing threads
    from backend.workers.tasks import parse_redis_url
    from arq import create_pool

    redis = await create_pool(parse_redis_url(settings.redis_url))
    try:
        await redis.enqueue_job(
            "generate_digests_for_threads",
            missing,
        )
    finally:
        await redis.close()

    logger.debug(
        f"Enqueued digest generation for {len(missing)} awaiting-response threads"
    )


@router.get("/subscriptions")
async def get_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("all", description="Filter: all, active, unsubscribed"),
    search: str = Query("", description="Search by sender name or domain"),
    sort: str = Query("count", description="Sort: count, date, name"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get subscription/marketing emails grouped by sender domain."""
    from backend.models.ai import UnsubscribeTracking

    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"subscriptions": [], "senders": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)

    base_query = (
        select(
            Email.id,
            Email.subject,
            Email.from_name,
            Email.from_address,
            Email.date,
            Email.snippet,
            Email.gmail_message_id,
            AIAnalysis.summary,
            AIAnalysis.unsubscribe_info,
        )
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .where(
            account_filter,
            AIAnalysis.is_subscription == True,
            Email.is_trash == False,
            Email.is_spam == False,
        )
    )

    if search:
        search_pattern = f"%{search.lower()}%"
        base_query = base_query.where(
            func.lower(func.coalesce(Email.from_name, Email.from_address)).like(search_pattern)
            | func.lower(Email.from_address).like(search_pattern)
        )

    result = await db.execute(base_query.order_by(desc(Email.date)))

    tracking_result = await db.execute(
        select(UnsubscribeTracking).where(
            UnsubscribeTracking.user_id == user.id,
        )
    )
    tracking_by_domain = {}
    for t in tracking_result.scalars().all():
        existing = tracking_by_domain.get(t.sender_domain)
        if not existing or t.unsubscribed_at > existing.unsubscribed_at:
            tracking_by_domain[t.sender_domain] = t

    senders = {}
    all_emails = []
    for row in result.all():
        addr = row.from_address or ""
        domain = addr.split("@")[-1] if "@" in addr else addr
        domain_tracking = tracking_by_domain.get(domain)

        is_unsubscribed = domain_tracking is not None
        if status == "active" and is_unsubscribed:
            continue
        if status == "unsubscribed" and not is_unsubscribed:
            continue

        email_data = {
            "id": row.id,
            "subject": row.subject,
            "from_name": row.from_name or row.from_address,
            "from_address": row.from_address,
            "date": row.date.isoformat() if row.date else None,
            "snippet": row.snippet,
            "gmail_message_id": row.gmail_message_id,
            "summary": row.summary,
            "unsubscribe_info": row.unsubscribe_info,
            "unsubscribed_at": domain_tracking.unsubscribed_at.isoformat() if domain_tracking else None,
            "unsubscribe_status": domain_tracking.status if domain_tracking else None,
        }
        all_emails.append(email_data)

        if domain not in senders:
            senders[domain] = {
                "domain": domain,
                "from_name": row.from_name or addr,
                "from_address": addr,
                "count": 0,
                "latest_date": row.date.isoformat() if row.date else None,
                "latest_subject": row.subject,
                "latest_snippet": row.snippet,
                "unsubscribe_info": row.unsubscribe_info,
                "sample_email_id": row.id,
                "unsubscribed_at": domain_tracking.unsubscribed_at.isoformat() if domain_tracking else None,
                "unsubscribe_status": domain_tracking.status if domain_tracking else None,
                "unsubscribe_method": domain_tracking.method if domain_tracking else None,
                "emails_received_after": domain_tracking.emails_received_after if domain_tracking else 0,
                "honors_unsubscribe": True if not domain_tracking else domain_tracking.emails_received_after == 0,
                "marked_spam": domain_tracking.marked_spam if domain_tracking else False,
            }
        senders[domain]["count"] += 1

    sender_list = list(senders.values())
    if sort == "count":
        sender_list.sort(key=lambda s: s["count"], reverse=True)
    elif sort == "date":
        sender_list.sort(key=lambda s: s["latest_date"] or "", reverse=True)
    elif sort == "name":
        sender_list.sort(key=lambda s: (s["from_name"] or "").lower())

    total = len(sender_list)
    paginated_senders = sender_list[(page - 1) * page_size : page * page_size]

    return {
        "emails": all_emails,
        "senders": paginated_senders,
        "total": total,
    }


async def _get_email_unsub_context(db: AsyncSession, email_id: int, user: User):
    """Shared helper to load email, account, and unsubscribe info for an email_id."""
    from backend.models.ai import UnsubscribeTracking

    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    account_ids = await _get_user_account_ids(db, user)
    if email.account_id not in account_ids:
        raise HTTPException(status_code=404, detail="Email not found")

    acct_result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.id == email.account_id)
    )
    account = acct_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    analysis_result = await db.execute(
        select(AIAnalysis).where(AIAnalysis.email_id == email_id)
    )
    analysis = analysis_result.scalar_one_or_none()
    unsub_info = analysis.unsubscribe_info if analysis else None

    if not unsub_info and email.raw_headers:
        from backend.services.ai import _parse_list_unsubscribe
        unsub_info = _parse_list_unsubscribe(email.raw_headers)

    if not unsub_info:
        raise HTTPException(status_code=400, detail="No unsubscribe method found for this email")

    return email, account, unsub_info


@router.post("/unsubscribe/{email_id}")
async def unsubscribe_email(
    email_id: int,
    preview: bool = Query(False),
    mark_spam: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unsubscribe from an email.

    With preview=true, returns the unsubscribe info without acting.
    With preview=false (default), sends unsubscribe email and/or records tracking.
    With mark_spam=true (default), also marks the email as spam in Gmail.
    """
    from backend.models.ai import UnsubscribeTracking
    from backend.services.gmail import GmailService
    from backend.services.unsubscribe import UnsubscribeService

    email, account, unsub_info = await _get_email_unsub_context(db, email_id, user)

    unsub_email_to = unsub_info.get("email")
    subject = unsub_info.get("mailto_subject", "unsubscribe")
    body_text = unsub_info.get("mailto_body", "")
    if not body_text:
        body_text = "Please unsubscribe me from this mailing list. Thank you."

    if preview:
        response_data = {
            "method": unsub_info.get("method"),
            "email_sent": False,
            "url": unsub_info.get("url"),
        }
        if unsub_email_to:
            response_data["preview"] = {
                "to": unsub_email_to,
                "subject": subject,
                "body": body_text,
            }
        return response_data

    from_addr = email.from_address or ""
    sender_domain = from_addr.split("@")[-1] if "@" in from_addr else from_addr

    client_id, client_secret = await get_google_credentials(db)
    gmail = GmailService(account, client_id=client_id, client_secret=client_secret)

    from backend.services.ai import get_unsubscribe_model_for_user
    unsub_model = await get_unsubscribe_model_for_user(user.id)
    unsub_service = UnsubscribeService(model=unsub_model)

    response_data = {
        "method": unsub_info.get("method"),
        "email_sent": False,
        "url": unsub_info.get("url"),
        "marked_spam": False,
    }

    tracking = UnsubscribeTracking(
        user_id=user.id,
        email_id=email_id,
        sender_domain=sender_domain,
        sender_address=from_addr,
        unsubscribe_to=unsub_email_to,
        method=unsub_info.get("method", "email"),
        status="in_progress",
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)

    if unsub_email_to:
        event = await unsub_service.unsubscribe_via_email(gmail, unsub_info)
        if event.status == "success":
            response_data["email_sent"] = True
            response_data["sent_to"] = unsub_email_to
            tracking.status = "success"
        else:
            tracking.status = "failed"
            tracking.error_message = event.error
            response_data["email_error"] = event.error
    elif unsub_info.get("url"):
        # For URL-based, just record that we'll need the streaming endpoint
        tracking.status = "pending"
        response_data["needs_browser"] = True

    if mark_spam and email.gmail_message_id:
        spam_ok = await unsub_service.mark_as_spam(gmail, email.gmail_message_id)
        response_data["marked_spam"] = spam_ok
        tracking.marked_spam = spam_ok

    await db.commit()

    return response_data


@router.get("/unsubscribe/{email_id}/stream")
async def unsubscribe_stream(
    email_id: int,
    mark_spam: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """SSE endpoint that streams live progress of a Playwright-based URL unsubscribe.

    We extract all needed scalar values from the DI-scoped DB session up front,
    then the generator creates its own session so nothing depends on DI lifecycle.
    """
    import json as _json
    from fastapi.responses import StreamingResponse
    from backend.database import async_session as _async_session

    # Validate access and extract all primitives while the DI session is alive
    email, account, unsub_info = await _get_email_unsub_context(db, email_id, user)

    unsub_url = unsub_info.get("url")
    if not unsub_url:
        raise HTTPException(status_code=400, detail="No unsubscribe URL found for this email")

    from_addr = email.from_address or ""
    sender_domain = from_addr.split("@")[-1] if "@" in from_addr else from_addr
    user_email = str(account.email)
    user_id = int(user.id)
    gmail_message_id = str(email.gmail_message_id) if email.gmail_message_id else None
    account_id = int(account.id)

    # Read user's preferred unsubscribe model
    from backend.services.ai import get_unsubscribe_model_for_user
    unsub_model = await get_unsubscribe_model_for_user(user.id)

    # Explicitly close the DI session now so it isn't left dangling
    await db.close()

    async def event_generator():
        from backend.models.ai import UnsubscribeTracking
        from backend.services.gmail import GmailService
        from backend.services.unsubscribe import UnsubscribeService

        unsub_service = UnsubscribeService(model=unsub_model)
        screenshots = []
        llm_log = []
        final_status = "failed"

        async with _async_session() as stream_db:
            try:
                tracking = UnsubscribeTracking(
                    user_id=user_id,
                    email_id=email_id,
                    sender_domain=sender_domain,
                    sender_address=from_addr,
                    unsubscribe_to=None,
                    method="url",
                    status="in_progress",
                )
                stream_db.add(tracking)
                await stream_db.commit()
                await stream_db.refresh(tracking)
                tracking_id = tracking.id

                async for event in unsub_service.unsubscribe_via_url(unsub_url, user_email):
                    event_data = event.to_dict()
                    yield f"data: {_json.dumps(event_data)}\n\n"

                    if event.screenshot_b64:
                        screenshots.append(event.screenshot_b64)
                    if event.llm_reasoning:
                        llm_log.append({
                            "step": event.step,
                            "reasoning": event.llm_reasoning,
                        })

                    if event.status in ("success", "failed"):
                        final_status = event.status

                # Update tracking record with results
                result = await stream_db.execute(
                    select(UnsubscribeTracking).where(UnsubscribeTracking.id == tracking_id)
                )
                tracking = result.scalar_one()
                tracking.status = final_status
                tracking.screenshots = screenshots[-3:] if screenshots else []
                tracking.llm_log = llm_log
                if final_status == "failed":
                    last_log = llm_log[-1] if llm_log else {}
                    tracking.error_message = last_log.get("reasoning", "Unknown error")

                # Mark as spam if requested and unsubscribe succeeded
                if mark_spam and gmail_message_id and final_status == "success":
                    try:
                        acct_result = await stream_db.execute(
                            select(GoogleAccount).where(GoogleAccount.id == account_id)
                        )
                        acct = acct_result.scalar_one()
                        client_id, client_secret = await get_google_credentials(stream_db)
                        gmail = GmailService(acct, client_id=client_id, client_secret=client_secret)
                        spam_ok = await unsub_service.mark_as_spam(gmail, gmail_message_id)
                        tracking.marked_spam = spam_ok
                        if spam_ok:
                            yield f"data: {_json.dumps({'step': 'spam', 'message': 'Marked as spam in Gmail', 'status': 'success'})}\n\n"
                    except Exception as e:
                        logger.error(f"Failed to mark as spam during stream: {e}")

                await stream_db.commit()

            except Exception as e:
                logger.error(f"Unsubscribe stream error: {e}", exc_info=True)
                yield f"data: {_json.dumps({'step': 'error', 'message': str(e), 'status': 'failed'})}\n\n"

        yield f"data: {_json.dumps({'step': 'finished', 'message': 'Done', 'status': final_status})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/unsubscribe/bulk")
async def bulk_unsubscribe(
    email_ids: list[int] = Query(..., description="List of email IDs to unsubscribe from"),
    mark_spam: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk unsubscribe from multiple emails. Processes email-method ones immediately,
    returns URL-method ones as needing the streaming endpoint."""
    from backend.models.ai import UnsubscribeTracking
    from backend.services.gmail import GmailService
    from backend.services.unsubscribe import UnsubscribeService

    account_ids = await _get_user_account_ids(db, user)

    from backend.services.ai import get_unsubscribe_model_for_user
    unsub_model = await get_unsubscribe_model_for_user(user.id)
    unsub_service = UnsubscribeService(model=unsub_model)
    results = []

    for eid in email_ids:
        try:
            result = await db.execute(select(Email).where(Email.id == eid))
            email = result.scalar_one_or_none()
            if not email or email.account_id not in account_ids:
                results.append({"email_id": eid, "status": "error", "message": "Not found"})
                continue

            analysis_result = await db.execute(
                select(AIAnalysis).where(AIAnalysis.email_id == eid)
            )
            analysis = analysis_result.scalar_one_or_none()
            unsub_info = analysis.unsubscribe_info if analysis else None

            if not unsub_info and email.raw_headers:
                from backend.services.ai import _parse_list_unsubscribe
                unsub_info = _parse_list_unsubscribe(email.raw_headers)

            if not unsub_info:
                results.append({"email_id": eid, "status": "error", "message": "No unsubscribe method"})
                continue

            from_addr = email.from_address or ""
            sender_domain = from_addr.split("@")[-1] if "@" in from_addr else from_addr

            acct_result = await db.execute(
                select(GoogleAccount).where(GoogleAccount.id == email.account_id)
            )
            account = acct_result.scalar_one_or_none()
            if not account:
                results.append({"email_id": eid, "status": "error", "message": "Account not found"})
                continue

            client_id, client_secret = await get_google_credentials(db)
            gmail = GmailService(account, client_id=client_id, client_secret=client_secret)

            unsub_email_to = unsub_info.get("email")
            method = unsub_info.get("method", "url")

            if unsub_email_to:
                event = await unsub_service.unsubscribe_via_email(gmail, unsub_info)
                tracking = UnsubscribeTracking(
                    user_id=user.id,
                    email_id=eid,
                    sender_domain=sender_domain,
                    sender_address=from_addr,
                    unsubscribe_to=unsub_email_to,
                    method="email",
                    status=event.status,
                    error_message=event.error,
                )
                db.add(tracking)

                if mark_spam and email.gmail_message_id:
                    spam_ok = await unsub_service.mark_as_spam(gmail, email.gmail_message_id)
                    tracking.marked_spam = spam_ok

                results.append({
                    "email_id": eid,
                    "status": event.status,
                    "method": "email",
                    "message": event.message,
                })
            else:
                # URL-based: queue for streaming
                tracking = UnsubscribeTracking(
                    user_id=user.id,
                    email_id=eid,
                    sender_domain=sender_domain,
                    sender_address=from_addr,
                    unsubscribe_to=None,
                    method="url",
                    status="pending",
                )
                db.add(tracking)
                results.append({
                    "email_id": eid,
                    "status": "pending",
                    "method": "url",
                    "message": "Needs browser automation - use /unsubscribe/{id}/stream",
                    "needs_browser": True,
                })

        except Exception as e:
            logger.error(f"Bulk unsubscribe error for email {eid}: {e}")
            results.append({"email_id": eid, "status": "error", "message": str(e)})

    await db.commit()

    return {
        "results": results,
        "total": len(results),
        "successful": sum(1 for r in results if r["status"] == "success"),
        "pending_browser": sum(1 for r in results if r.get("needs_browser")),
        "failed": sum(1 for r in results if r["status"] in ("error", "failed")),
    }


@router.post("/subscriptions/{email_id}/block")
async def block_sender(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Block a subscription sender by marking as spam. Used when no unsubscribe method exists."""
    from backend.models.ai import UnsubscribeTracking
    from backend.services.gmail import GmailService
    from backend.services.unsubscribe import UnsubscribeService

    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    account_ids = await _get_user_account_ids(db, user)
    if email.account_id not in account_ids:
        raise HTTPException(status_code=404, detail="Email not found")

    acct_result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.id == email.account_id)
    )
    account = acct_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from_addr = email.from_address or ""
    sender_domain = from_addr.split("@")[-1] if "@" in from_addr else from_addr

    # Mark as spam in Gmail
    spam_ok = False
    if email.gmail_message_id:
        client_id, client_secret = await get_google_credentials(db)
        gmail = GmailService(account, client_id=client_id, client_secret=client_secret)
        unsub_service = UnsubscribeService()
        spam_ok = await unsub_service.mark_as_spam(gmail, email.gmail_message_id)

    # Record tracking
    tracking = UnsubscribeTracking(
        user_id=user.id,
        email_id=email_id,
        sender_domain=sender_domain,
        sender_address=from_addr,
        unsubscribe_to=None,
        method="block",
        status="success",
        marked_spam=spam_ok,
    )
    db.add(tracking)
    await db.commit()

    return {"blocked": True, "marked_spam": spam_ok}


@router.get("/digests")
async def get_thread_digests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conversation_type: str = Query(None, description="Filter by conversation type: scheduling, discussion, notification, transactional, other"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get thread digests with AI-generated summaries and conversation type detection.

    Thread digests collapse multi-message threads into single entries.
    Scheduling threads show the resolved outcome instead of all the back-and-forth.
    """
    from backend.models.ai import ThreadDigest

    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"digests": [], "total": 0}

    where_clauses = [
        ThreadDigest.account_id.in_(account_ids),
    ]
    if conversation_type:
        where_clauses.append(ThreadDigest.conversation_type == conversation_type)

    # Count total
    count_result = await db.scalar(
        select(func.count(ThreadDigest.id)).where(*where_clauses)
    )
    total = count_result or 0

    # Fetch paginated digests
    result = await db.execute(
        select(ThreadDigest)
        .where(*where_clauses)
        .order_by(desc(ThreadDigest.latest_date))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    digests = result.scalars().all()

    return {
        "digests": [
            {
                "id": d.id,
                "thread_id": d.gmail_thread_id,
                "account_id": d.account_id,
                "conversation_type": d.conversation_type,
                "summary": d.summary,
                "resolved_outcome": d.resolved_outcome,
                "is_resolved": d.is_resolved,
                "key_topics": d.key_topics or [],
                "message_count": d.message_count,
                "participants": d.participants or [],
                "subject": d.subject,
                "latest_date": d.latest_date.isoformat() if d.latest_date else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in digests
        ],
        "total": total,
    }


@router.get("/bundles")
async def get_email_bundles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("active", description="Filter by status: active, resolved, stale"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get topic-based email bundles that group related emails across threads and accounts.

    Bundles are user-level and can span multiple accounts.
    """
    from backend.models.ai import EmailBundle

    where_clauses = [
        EmailBundle.user_id == user.id,
    ]
    if status:
        where_clauses.append(EmailBundle.status == status)

    # Count total
    count_result = await db.scalar(
        select(func.count(EmailBundle.id)).where(*where_clauses)
    )
    total = count_result or 0

    # Fetch paginated bundles
    result = await db.execute(
        select(EmailBundle)
        .where(*where_clauses)
        .order_by(desc(EmailBundle.latest_date))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    bundles = result.scalars().all()

    return {
        "bundles": [
            {
                "id": b.id,
                "title": b.title,
                "summary": b.summary,
                "key_topics": b.key_topics or [],
                "email_ids": b.email_ids or [],
                "thread_ids": b.thread_ids or [],
                "account_ids": b.account_ids or [],
                "email_count": b.email_count,
                "thread_count": b.thread_count,
                "latest_date": b.latest_date.isoformat() if b.latest_date else None,
                "status": b.status,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "updated_at": b.updated_at.isoformat() if b.updated_at else None,
            }
            for b in bundles
        ],
        "total": total,
    }


@router.get("/threads")
async def get_thread_summaries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get thread summaries with message counts and participants."""
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"threads": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)

    # Get threads that have more than 1 message, ordered by latest activity
    thread_query = (
        select(
            Email.gmail_thread_id,
            func.count(Email.id).label("message_count"),
            func.max(Email.date).label("latest_date"),
            func.min(Email.date).label("earliest_date"),
            func.bool_or(Email.is_read == False).label("has_unread"),
        )
        .where(
            account_filter,
            Email.is_trash == False,
            Email.is_spam == False,
        )
        .group_by(Email.gmail_thread_id)
        .having(func.count(Email.id) > 1)
    )

    # Count total threads
    count_result = await db.scalar(
        select(func.count()).select_from(thread_query.subquery())
    )
    total = count_result or 0

    # Get paginated threads
    thread_result = await db.execute(
        thread_query
        .order_by(desc("latest_date"))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    thread_rows = thread_result.all()

    threads = []
    for row in thread_rows:
        thread_id = row.gmail_thread_id

        # Get subject and participants for this thread
        emails_result = await db.execute(
            select(
                Email.subject,
                Email.from_name,
                Email.from_address,
            )
            .where(
                Email.gmail_thread_id == thread_id,
                account_filter,
            )
            .order_by(asc(Email.date))
        )
        thread_emails = emails_result.all()

        subject = thread_emails[0].subject if thread_emails else "(no subject)"
        participants = []
        seen_addrs = set()
        for te in thread_emails:
            addr = te.from_address
            if addr and addr not in seen_addrs:
                seen_addrs.add(addr)
                participants.append({
                    "name": te.from_name or addr,
                    "address": addr,
                })

        # Check if any message in thread needs reply
        needs_reply_result = await db.scalar(
            select(func.count(AIAnalysis.id))
            .join(Email, Email.id == AIAnalysis.email_id)
            .where(
                Email.gmail_thread_id == thread_id,
                account_filter,
                AIAnalysis.needs_reply == True,
            )
        )

        threads.append({
            "thread_id": thread_id,
            "subject": subject,
            "message_count": row.message_count,
            "latest_date": row.latest_date.isoformat() if row.latest_date else None,
            "earliest_date": row.earliest_date.isoformat() if row.earliest_date else None,
            "has_unread": row.has_unread,
            "participants": participants,
            "needs_reply": (needs_reply_result or 0) > 0,
        })

    return {"threads": threads, "total": total}


@router.post("/draft-action")
async def draft_action(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Have AI draft a reply for a todo item's action item."""
    from backend.models.todo import TodoItem

    todo_id = body.get("todo_id")
    if not todo_id:
        raise HTTPException(status_code=400, detail="todo_id is required")

    # Verify ownership
    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    if not todo.email_id:
        raise HTTPException(status_code=400, detail="Todo has no source email to draft against")

    # Mark as drafting
    todo.ai_draft_status = "drafting"
    await db.commit()

    try:
        model = await get_model_for_user(user.id)
        ai = AIService(model=model)
        result = await ai.draft_action_reply(todo_id, user_context=user.about_me)
        return result
    except Exception as e:
        logger.error(f"Draft action error: {e}")
        # Reset status on failure
        todo.ai_draft_status = None
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to draft: {str(e)}")


@router.post("/generate-reply")
async def generate_reply(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a custom AI reply based on a user-provided prompt."""
    email_id = body.get("email_id")
    prompt = body.get("prompt", "").strip()
    if not email_id:
        raise HTTPException(status_code=400, detail="email_id is required")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    # Verify access
    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    account_ids = await _get_user_account_ids(db, user)
    if email.account_id not in account_ids:
        raise HTTPException(status_code=404, detail="Email not found")

    # Load account description and email for context
    acct_result = await db.execute(
        select(GoogleAccount.description, GoogleAccount.email).where(GoogleAccount.id == email.account_id)
    )
    acct_row = acct_result.first()
    acct_desc = acct_row[0] if acct_row else None
    acct_email = acct_row[1] if acct_row else None

    try:
        model = await get_custom_prompt_model_for_user(user.id)
        ai = AIService(model=model)
        result = await ai.generate_custom_reply(
            email_id,
            user_prompt=prompt,
            user_context=user.about_me,
            account_description=acct_desc,
            account_email=acct_email,
        )
        return result
    except Exception as e:
        logger.error(f"Generate reply error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate reply: {str(e)}")


@router.post("/approve-action/{todo_id}")
async def approve_action(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve and send an AI-drafted reply for a todo item."""
    from backend.models.todo import TodoItem
    from backend.services.gmail import GmailService

    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    if not todo.ai_draft_body:
        raise HTTPException(status_code=400, detail="No draft to send")
    if not todo.ai_draft_to:
        raise HTTPException(status_code=400, detail="No recipient for draft")

    # Get the source email for thread/subject context
    email = None
    if todo.email_id:
        email_result = await db.execute(select(Email).where(Email.id == todo.email_id))
        email = email_result.scalar_one_or_none()

    # Find the account to send from
    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        raise HTTPException(status_code=400, detail="No email account available")

    acct_result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.id == account_ids[0])
    )
    account = acct_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=400, detail="Account not found")

    # Build subject
    subject = ""
    thread_id = None
    in_reply_to = None
    if email:
        subject = email.subject or ""
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
        thread_id = email.gmail_thread_id
        in_reply_to = email.message_id_header

    client_id, client_secret = await get_google_credentials(db)
    gmail = GmailService(account, client_id=client_id, client_secret=client_secret)

    try:
        body_html = f"<p>{todo.ai_draft_body.replace(chr(10), '<br>')}</p>"
        await gmail.send_email(
            to=[todo.ai_draft_to],
            subject=subject,
            body_text=todo.ai_draft_body,
            body_html=body_html,
            in_reply_to=in_reply_to,
            references=in_reply_to,
            thread_id=thread_id,
        )

        todo.ai_draft_status = "sent"
        todo.status = "done"
        from datetime import datetime, timezone
        todo.completed_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "id": todo.id,
            "ai_draft_status": "sent",
            "status": "done",
            "message": f"Reply sent to {todo.ai_draft_to}",
        }

    except Exception as e:
        logger.error(f"Send draft error for todo {todo_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send: {str(e)}")


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

    # Determine target model
    target_model = body.get("model")
    if not target_model:
        target_model = await get_model_for_user(user.id)

    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        return {"queued": 0, "model": target_model, "message": "No accounts found"}

    account_filter = Email.account_id.in_(account_ids)

    # Find analyses with a different model (limited to newest 1000 emails)
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
        return {"queued": 0, "model": target_model, "message": "All emails already processed with this model"}

    # Delete the stale analyses
    stale_ids = [r[0] for r in stale_rows]
    email_ids = [r[1] for r in stale_rows]

    from sqlalchemy import delete
    await db.execute(
        delete(AIAnalysis).where(AIAnalysis.id.in_(stale_ids))
    )
    await db.commit()

    # Store progress state in Redis before queuing
    await set_ai_progress(user.id, "reprocess", len(email_ids), target_model)

    # Queue re-analysis via worker
    from backend.workers.tasks import queue_analysis
    # Split into chunks of 100 for the worker
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
    rebuild_days: int = Query(None, description="If provided, immediately re-queue analysis for the last N days after deletion."),
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

    # Count how many will be deleted
    delete_count = await db.scalar(
        select(func.count(AIAnalysis.id))
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(account_filter)
    ) or 0

    if delete_count > 0:
        # Delete all AI analyses for this user's accounts
        from sqlalchemy import delete
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

    # Optionally rebuild
    if rebuild_days is not None and delete_count > 0:
        since_date = datetime.now(timezone.utc) - timedelta(days=rebuild_days) if rebuild_days > 0 else None

        # Count how many emails will be reprocessed
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
                await queue_auto_categorize(account_id, days=rebuild_days if rebuild_days > 0 else None)

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

    # Verify user owns the account if specified
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

    # Rebuild for all user accounts
    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]

    if not account_ids:
        return {"message": "No accounts found"}

    for aid in account_ids:
        await SearchService.rebuild_search_index(db, account_id=aid)

    return {"message": f"Search index rebuilt for {len(account_ids)} account(s)"}
