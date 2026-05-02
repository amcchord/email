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




# Register sub-modules that add endpoints to `router`. The import is at
# the bottom so the `router` symbol exists when those modules import it.
from backend.routers import (  # noqa: E402,F401
    ai_subscriptions,
    ai_replies,
    ai_maintenance,
)
