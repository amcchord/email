"""Subscription / unsubscribe endpoints.

Split out of `backend/routers/ai.py` to keep individual files reviewable. All
endpoints register on the same `router` instance defined in
`backend.routers.ai`, so URL paths are unchanged.
"""
import json as _json
import logging

from fastapi import Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session as _async_session
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis, UnsubscribeTracking
from backend.models.email import Email
from backend.models.user import User
from backend.routers.ai import router, _get_user_account_ids
from backend.routers.auth import get_current_user
from backend.services.ai import _parse_list_unsubscribe, get_unsubscribe_model_for_user
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService
from backend.services.unsubscribe import UnsubscribeService

logger = logging.getLogger(__name__)


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

    unsub_model = await get_unsubscribe_model_for_user(user.id)

    await db.close()

    async def event_generator():
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
    account_ids = await _get_user_account_ids(db, user)

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

    spam_ok = False
    if email.gmail_message_id:
        client_id, client_secret = await get_google_credentials(db)
        gmail = GmailService(account, client_id=client_id, client_secret=client_secret)
        unsub_service = UnsubscribeService()
        spam_ok = await unsub_service.mark_as_spam(gmail, email.gmail_message_id)

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
