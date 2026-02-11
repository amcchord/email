from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, desc, asc, or_, text, update, literal_column
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
        # INBOX: has INBOX label, not trash/spam
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
    if ai_category:
        query = query.join(AIAnalysis, AIAnalysis.email_id == Email.id)
        query = query.where(AIAnalysis.category == ai_category)

    # Full-text search
    if search:
        ts_query = func.plainto_tsquery("english", search)
        query = query.where(Email.search_vector.op("@@")(ts_query))

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

    # Build response
    email_summaries = []
    for e in emails:
        ai_cat = None
        ai_pri = None
        if e.ai_analysis:
            ai_cat = e.ai_analysis.category
            ai_pri = e.ai_analysis.priority
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
    if email.ai_analysis:
        ai_summary = email.ai_analysis.summary
        ai_actions = email.ai_analysis.action_items
        ai_cat = email.ai_analysis.category
        ai_pri = email.ai_analysis.priority

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
        # Remove INBOX label
        for eid in request.email_ids:
            result = await db.execute(
                select(Email).where(Email.id == eid, Email.account_id.in_(account_ids))
            )
            email = result.scalar_one_or_none()
            if email and email.labels:
                new_labels = [l for l in email.labels if l != "INBOX"]
                email.labels = new_labels
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    await db.commit()
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
