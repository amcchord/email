from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, desc, asc, or_, text, update, literal_column, literal
from typing import Optional
from backend.database import get_db


def jsonb_contains(column, value: str):
    """JSONB @> operator with proper PostgreSQL casting."""
    return column.op("@>")(literal_column(f"'{value}'::jsonb"))
from backend.models.user import User
from backend.models.email import Email, Attachment, EmailLabel
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis
from backend.schemas.email import (
    EmailSummary, EmailDetail, EmailListResponse,
    ThreadResponse, EmailActionRequest, LabelResponse, AttachmentResponse,
    EmailAddress,
)
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/emails", tags=["emails"])

MAILBOX_LABEL_MAP = {
    "INBOX": "INBOX",
    "SENT": "SENT",
    "DRAFTS": "DRAFT",
    "STARRED": None,  # Uses is_starred flag
    "SPAM": "SPAM",
    "TRASH": "TRASH",
    "ALL": None,
}


@router.get("/", response_model=EmailListResponse)
async def list_emails(
    account_id: Optional[int] = None,
    mailbox: str = "INBOX",
    label: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = "date",
    sort_order: str = "desc",
    search: Optional[str] = None,
    is_read: Optional[bool] = None,
    is_starred: Optional[bool] = None,
    ai_category: Optional[str] = None,
    exclude_ai_category: Optional[str] = None,
    ai_email_type: Optional[str] = None,
    needs_reply: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Get user's accounts
    acct_result = await db.execute(
        select(GoogleAccount.id, GoogleAccount.email).where(GoogleAccount.user_id == user.id)
    )
    user_accounts = {row[0]: row[1] for row in acct_result.all()}

    if not user_accounts:
        return EmailListResponse(emails=[], total=0, page=page, page_size=page_size, total_pages=0)

    query = select(Email).options(selectinload(Email.ai_analysis))

    # Filter by account
    if account_id and account_id in user_accounts:
        query = query.where(Email.account_id == account_id)
    else:
        query = query.where(Email.account_id.in_(user_accounts.keys()))

    # Filter by mailbox
    if mailbox == "STARRED":
        query = query.where(Email.is_starred == True)
    elif mailbox == "TRASH":
        query = query.where(Email.is_trash == True)
    elif mailbox == "SPAM":
        query = query.where(Email.is_spam == True)
    elif mailbox == "DRAFTS":
        query = query.where(Email.is_draft == True)
    elif mailbox == "SENT":
        query = query.where(Email.is_sent == True)
        query = query.where(Email.is_trash == False)
    elif mailbox == "ALL":
        query = query.where(Email.is_trash == False)
        query = query.where(Email.is_spam == False)
    else:
        # INBOX or custom label/category: has the label, not trash/spam
        gmail_label = MAILBOX_LABEL_MAP.get(mailbox, mailbox)
        if gmail_label:
            query = query.where(jsonb_contains(Email.labels, f'["{gmail_label}"]'))
        query = query.where(Email.is_trash == False)
        query = query.where(Email.is_spam == False)

    if label:
        query = query.where(jsonb_contains(Email.labels, f'["{label}"]'))

    if is_read is not None:
        query = query.where(Email.is_read == is_read)
    if is_starred is not None:
        query = query.where(Email.is_starred == is_starred)

    # AI category filter
    ai_joined = False
    if ai_category:
        query = query.join(AIAnalysis, AIAnalysis.email_id == Email.id)
        query = query.where(AIAnalysis.category == ai_category)
        ai_joined = True

    # Exclude AI category filter
    if exclude_ai_category:
        if not ai_joined:
            query = query.outerjoin(AIAnalysis, AIAnalysis.email_id == Email.id)
            ai_joined = True
        query = query.where(
            or_(AIAnalysis.category == None, AIAnalysis.category != exclude_ai_category)
        )

    # AI email type filter (work/personal)
    if ai_email_type:
        if not ai_joined:
            query = query.join(AIAnalysis, AIAnalysis.email_id == Email.id)
            ai_joined = True
        query = query.where(AIAnalysis.email_type == ai_email_type)

    # Needs reply filter
    if needs_reply is not None:
        if not ai_joined:
            query = query.join(AIAnalysis, AIAnalysis.email_id == Email.id)
            ai_joined = True
        query = query.where(AIAnalysis.needs_reply == needs_reply)

        # When filtering for needs_reply=True, exclude emails where the
        # user already sent a reply later in the same thread.  This
        # mirrors the logic in /api/ai/needs-reply and catches any stale
        # flags that haven't been cleared yet by the post-sync job.
        if needs_reply:
            from sqlalchemy.orm import aliased
            SentEmail = aliased(Email, flat=True)
            has_later_reply = (
                select(literal(1))
                .where(
                    SentEmail.gmail_thread_id == Email.gmail_thread_id,
                    SentEmail.account_id.in_(user_accounts.keys()),
                    SentEmail.is_sent == True,
                    SentEmail.is_trash == False,
                    SentEmail.date > Email.date,
                )
                .correlate(Email)
                .exists()
            )
            query = query.where(~has_later_reply)

    # Full-text search with ILIKE fallback
    if search:
        search_stripped = search.strip()
        if search_stripped:
            ts_query = func.plainto_tsquery("english", search_stripped)
            # Use full-text search when vectors exist, with ILIKE fallback
            search_pattern = f"%{search_stripped}%"
            query = query.where(
                or_(
                    Email.search_vector.op("@@")(ts_query),
                    Email.subject.ilike(search_pattern),
                    Email.from_address.ilike(search_pattern),
                    Email.from_name.ilike(search_pattern),
                )
            )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Sort
    sort_column = getattr(Email, sort_by, Email.date)
    if sort_order == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    emails = result.scalars().all()

    # Batch-load ThreadDigest data for threads in this page
    from backend.models.ai import ThreadDigest
    thread_ids = list(set(e.gmail_thread_id for e in emails if e.gmail_thread_id))
    digest_map = {}
    if thread_ids:
        digest_result = await db.execute(
            select(ThreadDigest).where(
                ThreadDigest.gmail_thread_id.in_(thread_ids),
                ThreadDigest.account_id.in_(user_accounts.keys()),
            )
        )
        for d in digest_result.scalars().all():
            digest_map[d.gmail_thread_id] = d

    # Batch-check which emails have a later sent reply in their thread.
    # This overrides stale needs_reply=true flags in the response even
    # when the stored AIAnalysis hasn't been updated yet.
    replied_email_ids = set()
    emails_with_needs_reply = [
        e for e in emails
        if e.ai_analysis and e.ai_analysis.needs_reply and e.gmail_thread_id
    ]
    if emails_with_needs_reply:
        from sqlalchemy.orm import aliased
        SentReply = aliased(Email, flat=True)
        for e in emails_with_needs_reply:
            has_reply = await db.scalar(
                select(literal(1)).where(
                    SentReply.gmail_thread_id == e.gmail_thread_id,
                    SentReply.account_id.in_(user_accounts.keys()),
                    SentReply.is_sent == True,
                    SentReply.is_trash == False,
                    SentReply.date > e.date,
                ).limit(1)
            )
            if has_reply:
                replied_email_ids.add(e.id)

    # Build response
    email_summaries = []
    for e in emails:
        ai_cat = None
        ai_pri = None
        ai_etype = None
        is_sub = None
        needs_rpl = None
        unsub_info = None
        if e.ai_analysis:
            ai_cat = e.ai_analysis.category
            ai_pri = e.ai_analysis.priority
            ai_etype = e.ai_analysis.email_type
            is_sub = e.ai_analysis.is_subscription
            needs_rpl = e.ai_analysis.needs_reply
            unsub_info = e.ai_analysis.unsubscribe_info

        # Override needs_reply if a later reply exists in the thread
        if needs_rpl and e.id in replied_email_ids:
            needs_rpl = False

        # Attach thread digest data if available
        digest = digest_map.get(e.gmail_thread_id)
        td_type = None
        td_summary = None
        td_outcome = None
        td_resolved = None
        td_count = None
        if digest:
            td_type = digest.conversation_type
            td_summary = digest.summary
            td_outcome = digest.resolved_outcome
            td_resolved = digest.is_resolved
            td_count = digest.message_count

        email_summaries.append(EmailSummary(
            id=e.id,
            gmail_message_id=e.gmail_message_id,
            gmail_thread_id=e.gmail_thread_id,
            subject=e.subject,
            from_address=e.from_address,
            from_name=e.from_name,
            to_addresses=e.to_addresses or [],
            date=e.date,
            snippet=e.snippet,
            is_read=e.is_read,
            is_starred=e.is_starred,
            is_draft=e.is_draft,
            has_attachments=e.has_attachments,
            labels=e.labels or [],
            account_email=user_accounts.get(e.account_id),
            ai_category=ai_cat,
            ai_priority=ai_pri,
            ai_email_type=ai_etype,
            is_subscription=is_sub,
            needs_reply=needs_rpl,
            unsubscribe_info=unsub_info,
            thread_digest_type=td_type,
            thread_digest_summary=td_summary,
            thread_digest_outcome=td_outcome,
            thread_digest_resolved=td_resolved,
            thread_digest_count=td_count,
        ))

    total_pages = (total + page_size - 1) // page_size if total else 0

    return EmailListResponse(
        emails=email_summaries,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{email_id}", response_model=EmailDetail)
async def get_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Email)
        .options(selectinload(Email.attachments), selectinload(Email.ai_analysis))
        .where(Email.id == email_id)
    )
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Verify user has access
    acct = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == email.account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    if not acct.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Email not found")

    attachments = []
    for att in email.attachments:
        attachments.append(AttachmentResponse(
            id=att.id,
            filename=att.filename,
            content_type=att.content_type,
            size_bytes=att.size_bytes,
            is_inline=att.is_inline,
        ))

    ai_summary = None
    ai_actions = None
    ai_cat = None
    ai_pri = None
    ai_etype = None
    is_sub = None
    needs_rpl = None
    unsub_info = None
    ai_model = None
    ai_suggested_reply = None
    ai_reply_options = None
    if email.ai_analysis:
        ai_summary = email.ai_analysis.summary
        ai_actions = email.ai_analysis.action_items
        ai_cat = email.ai_analysis.category
        ai_pri = email.ai_analysis.priority
        ai_etype = email.ai_analysis.email_type
        is_sub = email.ai_analysis.is_subscription
        needs_rpl = email.ai_analysis.needs_reply
        unsub_info = email.ai_analysis.unsubscribe_info
        ai_model = email.ai_analysis.model_used
        ai_suggested_reply = email.ai_analysis.suggested_reply
        ai_reply_options = email.ai_analysis.reply_options

    return EmailDetail(
        id=email.id,
        gmail_message_id=email.gmail_message_id,
        gmail_thread_id=email.gmail_thread_id,
        subject=email.subject,
        from_address=email.from_address,
        from_name=email.from_name,
        to_addresses=email.to_addresses or [],
        cc_addresses=email.cc_addresses or [],
        bcc_addresses=email.bcc_addresses or [],
        date=email.date,
        snippet=email.snippet,
        body_text=email.body_text,
        body_html=email.body_html,
        is_read=email.is_read,
        is_starred=email.is_starred,
        is_draft=email.is_draft,
        has_attachments=email.has_attachments,
        labels=email.labels or [],
        size_bytes=email.size_bytes,
        reply_to=email.reply_to,
        message_id_header=email.message_id_header,
        in_reply_to=email.in_reply_to,
        attachments=attachments,
        ai_summary=ai_summary,
        ai_action_items=ai_actions,
        ai_category=ai_cat,
        ai_priority=ai_pri,
        ai_email_type=ai_etype,
        is_subscription=is_sub,
        needs_reply=needs_rpl,
        unsubscribe_info=unsub_info,
        ai_model_used=ai_model,
        suggested_reply=ai_suggested_reply,
        reply_options=ai_reply_options,
    )


@router.get("/thread/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Get user's account IDs
    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]

    result = await db.execute(
        select(Email)
        .options(selectinload(Email.attachments), selectinload(Email.ai_analysis))
        .where(
            Email.gmail_thread_id == thread_id,
            Email.account_id.in_(account_ids),
        ).order_by(asc(Email.date))
    )
    emails = result.scalars().all()

    if not emails:
        raise HTTPException(status_code=404, detail="Thread not found")

    participants_set = {}
    email_details = []
    for e in emails:
        if e.from_address and e.from_address not in participants_set:
            participants_set[e.from_address] = EmailAddress(
                name=e.from_name, address=e.from_address
            )
        for to in (e.to_addresses or []):
            addr = to.get("address", "") if isinstance(to, dict) else to
            if addr and addr not in participants_set:
                name = to.get("name", "") if isinstance(to, dict) else ""
                participants_set[addr] = EmailAddress(name=name, address=addr)

        attachments = [
            AttachmentResponse(
                id=att.id,
                filename=att.filename,
                content_type=att.content_type,
                size_bytes=att.size_bytes,
                is_inline=att.is_inline,
            )
            for att in e.attachments
        ]

        email_details.append(EmailDetail(
            id=e.id,
            gmail_message_id=e.gmail_message_id,
            gmail_thread_id=e.gmail_thread_id,
            subject=e.subject,
            from_address=e.from_address,
            from_name=e.from_name,
            to_addresses=e.to_addresses or [],
            cc_addresses=e.cc_addresses or [],
            bcc_addresses=e.bcc_addresses or [],
            date=e.date,
            snippet=e.snippet,
            body_text=e.body_text,
            body_html=e.body_html,
            is_read=e.is_read,
            is_starred=e.is_starred,
            is_draft=e.is_draft,
            has_attachments=e.has_attachments,
            labels=e.labels or [],
            size_bytes=e.size_bytes,
            reply_to=e.reply_to,
            message_id_header=e.message_id_header,
            in_reply_to=e.in_reply_to,
            attachments=attachments,
        ))

    return ThreadResponse(
        thread_id=thread_id,
        subject=emails[0].subject,
        emails=email_details,
        participants=list(participants_set.values()),
    )


@router.post("/actions")
async def email_actions(
    request: EmailActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from backend.services.gmail import GmailService

    # Verify user owns these emails
    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]

    base_filter = [
        Email.id.in_(request.email_ids),
        Email.account_id.in_(account_ids),
    ]

    action = request.action

    # Gmail label sync mapping
    gmail_sync = {
        "mark_read": {"remove": ["UNREAD"]},
        "mark_unread": {"add": ["UNREAD"]},
        "star": {"add": ["STARRED"]},
        "unstar": {"remove": ["STARRED"]},
        "trash": {"add": ["TRASH"]},
        "untrash": {"remove": ["TRASH"]},
        "spam": {"add": ["SPAM"], "remove": ["INBOX"]},
        "unspam": {"remove": ["SPAM"], "add": ["INBOX"]},
        "archive": {"remove": ["INBOX"]},
    }

    # Apply local DB changes
    if action == "mark_read":
        await db.execute(update(Email).where(*base_filter).values(is_read=True))
    elif action == "mark_unread":
        await db.execute(update(Email).where(*base_filter).values(is_read=False))
    elif action == "star":
        await db.execute(update(Email).where(*base_filter).values(is_starred=True))
    elif action == "unstar":
        await db.execute(update(Email).where(*base_filter).values(is_starred=False))
    elif action == "trash":
        await db.execute(update(Email).where(*base_filter).values(is_trash=True))
    elif action == "untrash":
        await db.execute(update(Email).where(*base_filter).values(is_trash=False))
    elif action == "spam":
        await db.execute(update(Email).where(*base_filter).values(is_spam=True))
    elif action == "unspam":
        await db.execute(update(Email).where(*base_filter).values(is_spam=False))
    elif action == "archive":
        for eid in request.email_ids:
            result = await db.execute(
                select(Email).where(Email.id == eid, Email.account_id.in_(account_ids))
            )
            email_obj = result.scalar_one_or_none()
            if email_obj and email_obj.labels:
                new_labels = [l for l in email_obj.labels if l != "INBOX"]
                email_obj.labels = new_labels
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    await db.commit()

    # Sync to Gmail in background (best-effort)
    sync_info = gmail_sync.get(action)
    if sync_info:
        # Fetch emails with their gmail_message_id and account
        email_result = await db.execute(
            select(Email.gmail_message_id, Email.account_id).where(
                Email.id.in_(request.email_ids),
                Email.account_id.in_(account_ids),
            )
        )
        email_rows = email_result.all()

        # Group by account
        by_account = {}
        for gmail_msg_id, acct_id in email_rows:
            if acct_id not in by_account:
                by_account[acct_id] = []
            by_account[acct_id].append(gmail_msg_id)

        for acct_id, msg_ids in by_account.items():
            try:
                acct_obj = await db.execute(
                    select(GoogleAccount).where(GoogleAccount.id == acct_id)
                )
                account = acct_obj.scalar_one_or_none()
                if account:
                    gmail_svc = GmailService(account)
                    for msg_id in msg_ids:
                        try:
                            await gmail_svc.modify_labels(
                                msg_id,
                                add_labels=sync_info.get("add"),
                                remove_labels=sync_info.get("remove"),
                            )
                        except Exception as sync_err:
                            import logging
                            logging.getLogger(__name__).warning(
                                f"Gmail sync failed for {msg_id}: {sync_err}"
                            )
            except Exception:
                pass

    return {"message": f"Action '{action}' applied to {len(request.email_ids)} emails"}


@router.get("/labels/all", response_model=list[LabelResponse])
async def get_labels(
    account_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]

    query = select(EmailLabel).where(EmailLabel.account_id.in_(account_ids))
    if account_id:
        query = query.where(EmailLabel.account_id == account_id)
    query = query.order_by(EmailLabel.name)

    result = await db.execute(query)
    labels = result.scalars().all()
    return [LabelResponse.model_validate(l) for l in labels]
