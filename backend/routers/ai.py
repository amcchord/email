import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, asc, and_, cast, Date
from sqlalchemy.dialects.postgresql import JSONB
from backend.database import get_db

logger = logging.getLogger(__name__)
from backend.models.user import User
from backend.models.email import Email
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis
from backend.routers.auth import get_current_user
from backend.services.ai import AIService, get_model_for_user
from backend.services.credentials import get_google_credentials
from backend.schemas.auth import DEFAULT_AI_PREFERENCES

router = APIRouter(prefix="/api/ai", tags=["ai"])


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

    model = await get_model_for_user(user.id)
    ai = AIService(model=model)
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
    account_ids = await _get_user_account_ids(db, user)

    result = await db.execute(
        select(Email).where(
            Email.gmail_thread_id == thread_id,
            Email.account_id.in_(account_ids),
        ).limit(1)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Thread not found")

    model = await get_model_for_user(user.id)
    ai = AIService(model=model)
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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Trigger auto-categorization of the newest 1000 unanalyzed emails per account."""
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        raise HTTPException(status_code=400, detail="No active accounts found")

    from backend.workers.tasks import queue_auto_categorize
    total_queued = 0
    for account_id in account_ids:
        await queue_auto_categorize(account_id)
        total_queued += 1

    return {
        "message": f"Queued auto-categorization for {total_queued} account(s) (newest 1000 emails each)",
        "accounts_queued": total_queued,
    }


@router.get("/needs-reply")
async def get_needs_reply(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get emails that the user should respond to."""
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"emails": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)

    base_query = (
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
            AIAnalysis.suggested_reply,
        )
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .where(
            account_filter,
            AIAnalysis.needs_reply == True,
            Email.is_trash == False,
            Email.is_spam == False,
        )
    )

    # Count total
    count_result = await db.scalar(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result or 0

    # Fetch page
    result = await db.execute(
        base_query
        .order_by(desc(AIAnalysis.priority), desc(Email.date))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    emails = [
        {
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
            "suggested_reply": row.suggested_reply,
        }
        for row in result.all()
    ]

    return {"emails": emails, "total": total}


@router.get("/subscriptions")
async def get_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get subscription/marketing emails grouped by sender domain."""
    account_ids = await _get_user_account_ids(db, user)

    if not account_ids:
        return {"subscriptions": [], "total": 0}

    account_filter = Email.account_id.in_(account_ids)

    # Get subscription emails with unsubscribe info
    base_query = (
        select(
            Email.id,
            Email.subject,
            Email.from_name,
            Email.from_address,
            Email.date,
            Email.snippet,
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

    count_result = await db.scalar(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result or 0

    result = await db.execute(
        base_query
        .order_by(desc(Email.date))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    # Group by sender domain
    senders = {}
    all_emails = []
    for row in result.all():
        email_data = {
            "id": row.id,
            "subject": row.subject,
            "from_name": row.from_name or row.from_address,
            "from_address": row.from_address,
            "date": row.date.isoformat() if row.date else None,
            "snippet": row.snippet,
            "summary": row.summary,
            "unsubscribe_info": row.unsubscribe_info,
        }
        all_emails.append(email_data)

        # Group by sender domain
        addr = row.from_address or ""
        domain = addr.split("@")[-1] if "@" in addr else addr
        if domain not in senders:
            senders[domain] = {
                "domain": domain,
                "from_name": row.from_name or addr,
                "count": 0,
                "latest_date": row.date.isoformat() if row.date else None,
                "unsubscribe_info": row.unsubscribe_info,
                "sample_email_id": row.id,
            }
        senders[domain]["count"] += 1

    return {
        "emails": all_emails,
        "senders": sorted(senders.values(), key=lambda s: s["count"], reverse=True),
        "total": total,
    }


@router.post("/unsubscribe/{email_id}")
async def unsubscribe_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unsubscribe from an email. Sends unsubscribe email or returns URL."""
    # Verify access
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

    # Get the AI analysis for unsubscribe info
    analysis_result = await db.execute(
        select(AIAnalysis).where(AIAnalysis.email_id == email_id)
    )
    analysis = analysis_result.scalar_one_or_none()

    unsub_info = analysis.unsubscribe_info if analysis else None

    # If no analysis info, try parsing from raw headers directly
    if not unsub_info and email.raw_headers:
        from backend.services.ai import _parse_list_unsubscribe
        unsub_info = _parse_list_unsubscribe(email.raw_headers)

    if not unsub_info:
        raise HTTPException(status_code=400, detail="No unsubscribe method found for this email")

    response_data = {
        "method": unsub_info.get("method"),
        "email_sent": False,
        "url": unsub_info.get("url"),
    }

    # If there's an email method, send the unsubscribe email
    if unsub_info.get("email"):
        from backend.services.gmail import GmailService
        client_id, client_secret = await get_google_credentials(db)
        gmail = GmailService(account, client_id=client_id, client_secret=client_secret)
        try:
            subject = unsub_info.get("mailto_subject", "unsubscribe")
            body_text = unsub_info.get("mailto_body", "")
            if not body_text:
                body_text = "Please unsubscribe me from this mailing list. Thank you."

            await gmail.send_email(
                to=[unsub_info["email"]],
                subject=subject,
                body_text=body_text,
            )
            response_data["email_sent"] = True
            response_data["sent_to"] = unsub_info["email"]
        except Exception as e:
            logger.error(f"Failed to send unsubscribe email for {email_id}: {e}")
            response_data["email_error"] = str(e)

    return response_data


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
        result = await ai.draft_action_reply(todo_id)
        return result
    except Exception as e:
        logger.error(f"Draft action error: {e}")
        # Reset status on failure
        todo.ai_draft_status = None
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to draft: {str(e)}")


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
