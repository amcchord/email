from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, select, func, desc, asc, or_, literal, tuple_
from typing import Annotated, Optional
from uuid import UUID
from backend.database import get_db
from backend.models.user import User
from backend.models.email import Email, Attachment, EmailLabel
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis
from backend.models.snooze import EmailSnooze, SNOOZE_ACTIVE_STATES
from backend.schemas.email import (
    EmailSummary, EmailDetail, EmailListResponse,
    ConversationSummary, ConversationListResponse, ConversationSplitResponse,
    ThreadResponse, EmailActionRequest, LabelResponse, AttachmentResponse,
    EmailAddress, MailActionItemResponse, MailActionOperationResponse,
)
from backend.routers.auth import get_current_user
from backend.services.attachments import (
    AttachmentDownloadError,
    attachment_content_disposition,
    load_attachment_bytes,
    safe_content_type,
)
from backend.services.attachment_previews import (
    MAX_ATTACHMENT_PREVIEW_BYTES,
    AttachmentPreviewError,
    load_and_build_attachment_preview,
)
from backend.services.workflow_context import apply_workflow_routing, delegated_scheduling_sql
from backend.services.mail_actions import (
    MailActionConflict,
    MailActionNotFound,
    MailActionValidationError,
    aggregate_action_state,
    get_mail_action_operation_by_idempotency,
    get_mail_action_operation,
    recent_mail_action_operations,
    retry_mail_action_operation,
    stage_mail_actions,
    try_enqueue_mail_action_drain,
    undo_mail_action_operation,
)
from backend.services.email_search_query import (
    SearchAccount,
    SearchLabel,
    SearchQueryError,
    build_email_search_clause,
    parse_email_search,
)
from backend.services.conversation_rows import (
    load_conversation_page,
    load_split_conversation_page,
)


def jsonb_contains(column, value: str):
    """Safely test whether a JSONB array contains one literal value."""
    return column.contains([value])

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


def _workflow_adjusted_analysis(email: Email) -> Optional[dict]:
    """Return presentation values corrected for known workflow delegation.

    Applying this at read time fixes already-analyzed messages immediately;
    new analyses persist the same corrections in ``AIService``.
    """
    analysis = email.ai_analysis
    if not analysis:
        return None
    return apply_workflow_routing(email, {
        "category": analysis.category,
        "email_type": analysis.email_type,
        "conversation_type": analysis.conversation_type,
        "priority": analysis.priority,
        "action_items": analysis.action_items,
        "context": analysis.context,
        "suggested_reply": analysis.suggested_reply,
        "reply_options": analysis.reply_options,
        "is_subscription": analysis.is_subscription,
        "needs_reply": analysis.needs_reply,
    })


async def _conversation_filter_statement(
    db: AsyncSession,
    *,
    account_rows,
    user_accounts: dict[int, str],
    user_id: int,
    account_id: Optional[int],
    mailbox: str,
    label: Optional[str],
    search: Optional[str],
    tz: Optional[str],
    is_read: Optional[bool],
    is_starred: Optional[bool],
    ai_category: Optional[str],
    exclude_ai_category: Optional[str],
    ai_email_type: Optional[str],
    needs_reply: Optional[bool],
):
    """Build the exact owned message predicate used to qualify conversations."""
    if account_id is not None and account_id not in user_accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    search_plan = None
    if search and search.strip():
        try:
            search_plan = parse_email_search(search)
        except SearchQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    query = select(Email)
    if account_id is not None:
        query = query.where(Email.account_id == account_id)
    else:
        query = query.where(Email.account_id.in_(user_accounts))

    if not search_plan or not search_plan.has_positive_in:
        if mailbox == "STARRED":
            query = query.where(Email.is_starred == True)
        elif mailbox == "TRASH":
            query = query.where(Email.is_trash == True)
        elif mailbox == "SPAM":
            query = query.where(Email.is_spam == True)
        elif mailbox == "DRAFTS":
            query = query.where(Email.is_draft == True)
        elif mailbox == "SENT":
            query = query.where(Email.is_sent == True, Email.is_trash == False)
        elif mailbox == "ALL":
            query = query.where(Email.is_trash == False, Email.is_spam == False)
        else:
            gmail_label = MAILBOX_LABEL_MAP.get(mailbox, mailbox)
            if gmail_label:
                query = query.where(jsonb_contains(Email.labels, gmail_label))
            query = query.where(Email.is_trash == False, Email.is_spam == False)

    if label:
        query = query.where(jsonb_contains(Email.labels, label))

    # Snoozed Inbox conversations are hidden by the authoritative query so
    # totals and page boundaries remain exact. Search and non-Inbox mailboxes
    # intentionally retain them with their reminder metadata in the client.
    if mailbox == "INBOX" and not (search_plan and search_plan.has_positive_in):
        active_snooze = select(literal(1)).where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.account_id == Email.account_id,
            EmailSnooze.state.in_(SNOOZE_ACTIVE_STATES),
            or_(
                EmailSnooze.email_id == Email.id,
                and_(
                    func.btrim(Email.gmail_thread_id) != "",
                    EmailSnooze.gmail_thread_id == Email.gmail_thread_id,
                ),
            ),
        ).correlate(Email).exists()
        query = query.where(~active_snooze)
    if is_read is not None:
        query = query.where(Email.is_read == is_read)
    if is_starred is not None:
        query = query.where(Email.is_starred == is_starred)

    ai_joined = False
    if ai_category:
        query = query.join(AIAnalysis, AIAnalysis.email_id == Email.id)
        query = query.where(AIAnalysis.category == ai_category)
        ai_joined = True
    if exclude_ai_category:
        if not ai_joined:
            query = query.outerjoin(AIAnalysis, AIAnalysis.email_id == Email.id)
            ai_joined = True
        query = query.where(
            or_(AIAnalysis.category == None, AIAnalysis.category != exclude_ai_category)
        )
    if ai_email_type:
        if not ai_joined:
            query = query.join(AIAnalysis, AIAnalysis.email_id == Email.id)
            ai_joined = True
        query = query.where(AIAnalysis.email_type == ai_email_type)
    if needs_reply is not None:
        if not ai_joined:
            query = query.join(AIAnalysis, AIAnalysis.email_id == Email.id)
            ai_joined = True
        query = query.where(AIAnalysis.needs_reply == needs_reply)
        if needs_reply:
            delegated_scheduling = delegated_scheduling_sql(
                AIAnalysis.conversation_type,
                Email.to_addresses,
                Email.cc_addresses,
            )
            query = query.where(
                or_(
                    AIAnalysis.conversation_type.is_(None),
                    ~delegated_scheduling,
                    AIAnalysis.priority >= 2,
                )
            )
            from sqlalchemy.orm import aliased
            SentEmail = aliased(Email, flat=True)
            query = query.where(~select(literal(1)).where(
                SentEmail.gmail_thread_id == Email.gmail_thread_id,
                SentEmail.account_id == Email.account_id,
                SentEmail.is_sent == True,
                SentEmail.is_trash == False,
                SentEmail.date > Email.date,
            ).correlate(Email).exists())

    if search_plan:
        label_rows = []
        if search_plan.needs_labels:
            label_result = await db.execute(
                select(
                    EmailLabel.account_id,
                    EmailLabel.gmail_label_id,
                    EmailLabel.name,
                ).where(EmailLabel.account_id.in_(user_accounts))
            )
            label_rows = label_result.all()
        try:
            search_clause = build_email_search_clause(
                search_plan,
                accounts=[
                    SearchAccount(
                        id=row.id,
                        email=row.email,
                        display_name=row.display_name,
                        description=row.description,
                        short_label=row.short_label,
                    )
                    for row in account_rows
                ],
                labels=[
                    SearchLabel(
                        account_id=row.account_id,
                        gmail_label_id=row.gmail_label_id,
                        name=row.name,
                    )
                    for row in label_rows
                ],
                timezone_name=tz,
            )
        except SearchQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        query = query.where(search_clause)
    return query


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
    tz: Optional[str] = None,
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
        select(
            GoogleAccount.id,
            GoogleAccount.email,
            GoogleAccount.display_name,
            GoogleAccount.description,
            GoogleAccount.short_label,
        ).where(GoogleAccount.user_id == user.id)
    )
    account_rows = acct_result.all()
    user_accounts = {row.id: row.email for row in account_rows}

    if not user_accounts:
        return EmailListResponse(emails=[], total=0, page=page, page_size=page_size, total_pages=0)

    query = select(Email).options(selectinload(Email.ai_analysis))

    # An invalid account scope must never broaden into every owned account.
    if account_id is not None and account_id not in user_accounts:
        raise HTTPException(status_code=404, detail="Account not found")

    search_plan = None
    search_stripped = search.strip() if search else ""
    if search_stripped:
        try:
            search_plan = parse_email_search(search)
        except SearchQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Filter by account. Search operators are compiled inside this immutable
    # ownership boundary and can only narrow it.
    if account_id is not None:
        query = query.where(Email.account_id == account_id)
    else:
        query = query.where(Email.account_id.in_(user_accounts.keys()))

    # A positive in: operator supplies the mailbox scope. Otherwise preserve
    # the route's backward-compatible outer mailbox behavior.
    if not search_plan or not search_plan.has_positive_in:
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
                query = query.where(jsonb_contains(Email.labels, gmail_label))
            query = query.where(Email.is_trash == False)
            query = query.where(Email.is_spam == False)

    if label:
        query = query.where(jsonb_contains(Email.labels, label))

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
            delegated_scheduling = delegated_scheduling_sql(
                AIAnalysis.conversation_type,
                Email.to_addresses,
                Email.cc_addresses,
            )
            query = query.where(
                or_(
                    AIAnalysis.conversation_type.is_(None),
                    ~delegated_scheduling,
                    AIAnalysis.priority >= 2,
                )
            )

            from sqlalchemy.orm import aliased
            SentEmail = aliased(Email, flat=True)
            has_later_reply = (
                select(literal(1))
                .where(
                    SentEmail.gmail_thread_id == Email.gmail_thread_id,
                    SentEmail.account_id == Email.account_id,
                    SentEmail.is_sent == True,
                    SentEmail.is_trash == False,
                    SentEmail.date > Email.date,
                )
                .correlate(Email)
                .exists()
            )
            query = query.where(~has_later_reply)

    if search_plan:
        label_rows = []
        if search_plan.needs_labels:
            label_result = await db.execute(
                select(
                    EmailLabel.account_id,
                    EmailLabel.gmail_label_id,
                    EmailLabel.name,
                ).where(EmailLabel.account_id.in_(user_accounts.keys()))
            )
            label_rows = label_result.all()
        try:
            search_clause = build_email_search_clause(
                search_plan,
                accounts=[
                    SearchAccount(
                        id=row.id,
                        email=row.email,
                        display_name=row.display_name,
                        description=row.description,
                        short_label=row.short_label,
                    )
                    for row in account_rows
                ],
                labels=[
                    SearchLabel(
                        account_id=row.account_id,
                        gmail_label_id=row.gmail_label_id,
                        name=row.name,
                    )
                    for row in label_rows
                ],
                timezone_name=tz,
            )
        except SearchQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        query = query.where(search_clause)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Sort
    _ALLOWED_SORT_FIELDS = {"date", "subject", "sender", "is_read", "has_attachments"}
    if sort_by not in _ALLOWED_SORT_FIELDS:
        sort_by = "date"
    sort_column = Email.from_address if sort_by == "sender" else getattr(Email, sort_by, Email.date)
    if sort_order == "asc":
        query = query.order_by(asc(sort_column).nulls_last(), asc(Email.id))
    else:
        query = query.order_by(desc(sort_column).nulls_last(), desc(Email.id))

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    emails = result.scalars().all()

    # Batch-load ThreadDigest data for threads in this page
    from backend.models.ai import ThreadDigest
    thread_identities = list({
        (e.account_id, e.gmail_thread_id)
        for e in emails
        if str(e.gmail_thread_id or "").strip()
    })
    digest_map = {}
    if thread_identities:
        digest_result = await db.execute(
            select(ThreadDigest).where(
                tuple_(ThreadDigest.account_id, ThreadDigest.gmail_thread_id).in_(
                    thread_identities
                ),
            )
        )
        for d in digest_result.scalars().all():
            digest_map[(d.account_id, d.gmail_thread_id)] = d

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
                    SentReply.account_id == e.account_id,
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
        needs_rpl_ignored = None
        unsub_info = None
        analysis_view = _workflow_adjusted_analysis(e)
        if analysis_view:
            ai_cat = analysis_view["category"]
            ai_pri = analysis_view["priority"]
            ai_etype = analysis_view["email_type"]
            is_sub = analysis_view["is_subscription"]
            needs_rpl = analysis_view["needs_reply"]
            needs_rpl_ignored = e.ai_analysis.needs_reply_ignored
            unsub_info = e.ai_analysis.unsubscribe_info

        # Override needs_reply if a later reply exists in the thread
        if needs_rpl and e.id in replied_email_ids:
            needs_rpl = False

        # Attach thread digest data if available
        digest = digest_map.get((e.account_id, e.gmail_thread_id))
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
            account_id=e.account_id,
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
            is_sent=e.is_sent,
            is_trash=e.is_trash,
            is_spam=e.is_spam,
            has_attachments=e.has_attachments,
            labels=e.labels or [],
            account_email=user_accounts.get(e.account_id),
            ai_category=ai_cat,
            ai_priority=ai_pri,
            ai_email_type=ai_etype,
            is_subscription=is_sub,
            needs_reply=needs_rpl,
            needs_reply_ignored=needs_rpl_ignored,
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


async def _serialize_conversation_rows(
    db: AsyncSession,
    rows,
    user_accounts: dict[int, str],
) -> list[ConversationSummary]:
    """Serialize one already-authoritative conversation row set."""
    from backend.models.ai import ThreadDigest

    threaded_identities = [
        (row.anchor.account_id, row.anchor.gmail_thread_id)
        for row in rows
        if str(row.anchor.gmail_thread_id or "").strip()
    ]
    digest_map = {}
    if threaded_identities:
        digest_result = await db.execute(
            select(ThreadDigest).where(
                tuple_(ThreadDigest.account_id, ThreadDigest.gmail_thread_id).in_(
                    threaded_identities
                )
            )
        )
        digest_map = {
            (digest.account_id, digest.gmail_thread_id): digest
            for digest in digest_result.scalars().all()
        }

    conversations = []
    for row in rows:
        email = row.anchor
        analysis_view = _workflow_adjusted_analysis(email)
        ai_category_value = analysis_view["category"] if analysis_view else None
        ai_priority_value = analysis_view["priority"] if analysis_view else None
        ai_email_type_value = analysis_view["email_type"] if analysis_view else None
        is_subscription_value = analysis_view["is_subscription"] if analysis_view else None
        needs_reply_value = analysis_view["needs_reply"] if analysis_view else None
        needs_reply_ignored_value = (
            email.ai_analysis.needs_reply_ignored if email.ai_analysis else None
        )
        unsubscribe_info = email.ai_analysis.unsubscribe_info if email.ai_analysis else None

        if needs_reply_value and str(email.gmail_thread_id or "").strip():
            sent_reply = await db.scalar(
                select(literal(1)).where(
                    Email.account_id == email.account_id,
                    Email.gmail_thread_id == email.gmail_thread_id,
                    Email.is_sent == True,
                    Email.is_trash == False,
                    Email.date > email.date,
                ).limit(1)
            )
            if sent_reply:
                needs_reply_value = False

        label_counts: dict[str, int] = {}
        for member_labels in row.member_labels:
            for value in {str(item) for item in member_labels if str(item)}:
                label_counts[value] = label_counts.get(value, 0) + 1
        labels = sorted(label_counts)
        label_coverage = {
            value: "all" if count == row.member_count else "some"
            for value, count in label_counts.items()
        }
        if row.starred_count == 0:
            star_state = "none"
        elif row.starred_count == row.member_count:
            star_state = "all"
        else:
            star_state = "some"

        digest = digest_map.get((email.account_id, email.gmail_thread_id))
        conversations.append(ConversationSummary(
            conversation_key=f"{email.account_id}:{row.conversation_identity}",
            account_id=email.account_id,
            account_email=user_accounts[email.account_id],
            anchor_email_id=email.id,
            gmail_message_id=email.gmail_message_id,
            gmail_thread_id=email.gmail_thread_id,
            subject=email.subject,
            from_address=email.from_address,
            from_name=email.from_name,
            to_addresses=email.to_addresses or [],
            date=email.date,
            snippet=email.snippet,
            is_draft=email.is_draft,
            is_sent=email.is_sent,
            is_trash=email.is_trash,
            is_spam=email.is_spam,
            is_read=row.unread_count == 0,
            unread_count=row.unread_count,
            is_starred=row.starred_count > 0,
            star_state=star_state,
            has_attachments=row.attachment_count > 0,
            labels=labels,
            label_coverage=label_coverage,
            member_count=row.member_count,
            matched_count=row.matched_count,
            ai_category=ai_category_value,
            ai_priority=ai_priority_value,
            ai_email_type=ai_email_type_value,
            is_subscription=is_subscription_value,
            needs_reply=needs_reply_value,
            needs_reply_ignored=needs_reply_ignored_value,
            unsubscribe_info=unsubscribe_info,
            thread_digest_type=digest.conversation_type if digest else None,
            thread_digest_summary=digest.summary if digest else None,
            thread_digest_outcome=digest.resolved_outcome if digest else None,
            thread_digest_resolved=digest.is_resolved if digest else None,
            thread_digest_count=digest.message_count if digest else None,
            inbox_placement=row.inbox_placement,
            inbox_placement_reason=row.inbox_placement_reason,
        ))
    return conversations


@router.get("/conversations/split", response_model=ConversationSplitResponse)
async def list_split_conversations(
    account_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str = "date",
    sort_order: str = "desc",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return both Split Inbox sections from one coherent SQL statement."""
    account_result = await db.execute(
        select(
            GoogleAccount.id,
            GoogleAccount.email,
            GoogleAccount.display_name,
            GoogleAccount.description,
            GoogleAccount.short_label,
        ).where(GoogleAccount.user_id == user.id)
    )
    account_rows = account_result.all()
    user_accounts = {row.id: row.email for row in account_rows}
    if not user_accounts:
        empty = ConversationListResponse(
            conversations=[], total=0, page=page, page_size=page_size, total_pages=0
        )
        return ConversationSplitResponse(focused=empty, other=empty, total=0)

    filtered = await _conversation_filter_statement(
        db,
        account_rows=account_rows,
        user_accounts=user_accounts,
        user_id=user.id,
        account_id=account_id,
        mailbox="INBOX",
        label=None,
        search=None,
        tz=None,
        is_read=None,
        is_starred=None,
        ai_category=None,
        exclude_ai_category=None,
        ai_email_type=None,
        needs_reply=None,
    )
    rows, totals = await load_split_conversation_page(
        db,
        filtered,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    conversations = await _serialize_conversation_rows(db, rows, user_accounts)

    def section(placement: str):
        total = totals[placement]
        return ConversationListResponse(
            conversations=[
                row for row in conversations if row.inbox_placement == placement
            ],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if total else 0,
        )

    return ConversationSplitResponse(
        focused=section("focused"),
        other=section("other"),
        total=totals["focused"] + totals["other"],
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    account_id: Optional[int] = None,
    mailbox: str = "INBOX",
    label: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = "date",
    sort_order: str = "desc",
    search: Optional[str] = None,
    tz: Optional[str] = None,
    is_read: Optional[bool] = None,
    is_starred: Optional[bool] = None,
    ai_category: Optional[str] = None,
    exclude_ai_category: Optional[str] = None,
    ai_email_type: Optional[str] = None,
    needs_reply: Optional[bool] = None,
    inbox_placement: Annotated[
        Optional[str], Query(pattern="^(focused|other)$")
    ] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List one authoritative row per exact owned account/conversation."""
    placement_conflicts = any(
        value is not None
        for value in (
            label,
            search,
            is_read,
            is_starred,
            ai_category,
            exclude_ai_category,
            ai_email_type,
            needs_reply,
        )
    )
    if inbox_placement is not None and (
        mailbox != "INBOX" or placement_conflicts
    ):
        raise HTTPException(
            status_code=422,
            detail="Inbox placement is only available for the standard Inbox",
        )
    account_result = await db.execute(
        select(
            GoogleAccount.id,
            GoogleAccount.email,
            GoogleAccount.display_name,
            GoogleAccount.description,
            GoogleAccount.short_label,
        ).where(GoogleAccount.user_id == user.id)
    )
    account_rows = account_result.all()
    user_accounts = {row.id: row.email for row in account_rows}
    if not user_accounts:
        return ConversationListResponse(
            conversations=[], total=0, page=page, page_size=page_size, total_pages=0
        )

    filtered = await _conversation_filter_statement(
        db,
        account_rows=account_rows,
        user_accounts=user_accounts,
        user_id=user.id,
        account_id=account_id,
        mailbox=mailbox,
        label=label,
        search=search,
        tz=tz,
        is_read=is_read,
        is_starred=is_starred,
        ai_category=ai_category,
        exclude_ai_category=exclude_ai_category,
        ai_email_type=ai_email_type,
        needs_reply=needs_reply,
    )
    rows, total = await load_conversation_page(
        db,
        filtered,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        inbox_placement=inbox_placement,
    )

    conversations = await _serialize_conversation_rows(db, rows, user_accounts)

    total_pages = (total + page_size - 1) // page_size if total else 0
    return ConversationListResponse(
        conversations=conversations,
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
    account = acct.scalar_one_or_none()
    if not account:
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
    needs_rpl_ignored = None
    unsub_info = None
    ai_model = None
    ai_suggested_reply = None
    ai_reply_options = None
    analysis_view = _workflow_adjusted_analysis(email)
    if analysis_view:
        ai_summary = email.ai_analysis.summary
        ai_actions = analysis_view["action_items"]
        ai_cat = analysis_view["category"]
        ai_pri = analysis_view["priority"]
        ai_etype = analysis_view["email_type"]
        is_sub = analysis_view["is_subscription"]
        needs_rpl = analysis_view["needs_reply"]
        needs_rpl_ignored = email.ai_analysis.needs_reply_ignored
        unsub_info = email.ai_analysis.unsubscribe_info
        ai_model = email.ai_analysis.model_used
        ai_suggested_reply = analysis_view["suggested_reply"]
        ai_reply_options = analysis_view["reply_options"]

    return EmailDetail(
        id=email.id,
        account_id=account.id,
        account_email=account.email,
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
        is_sent=email.is_sent,
        is_trash=email.is_trash,
        is_spam=email.is_spam,
        has_attachments=email.has_attachments,
        labels=email.labels or [],
        size_bytes=email.size_bytes,
        reply_to=email.reply_to,
        message_id_header=email.message_id_header,
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
        attachments=attachments,
        ai_summary=ai_summary,
        ai_action_items=ai_actions,
        ai_category=ai_cat,
        ai_priority=ai_pri,
        ai_email_type=ai_etype,
        is_subscription=is_sub,
        needs_reply=needs_rpl,
        needs_reply_ignored=needs_rpl_ignored,
        unsubscribe_info=unsub_info,
        ai_model_used=ai_model,
        suggested_reply=ai_suggested_reply,
        reply_options=ai_reply_options,
    )


async def _owned_attachment_row(
    email_id: int,
    attachment_id: int,
    db: AsyncSession,
    user_id: int,
) -> tuple[Email, Attachment, GoogleAccount]:
    """Load one exact attachment without disclosing foreign or mismatched IDs."""
    result = await db.execute(
        select(Email, Attachment, GoogleAccount)
        .join(Attachment, Attachment.email_id == Email.id)
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .where(
            Email.id == email_id,
            Attachment.id == attachment_id,
            GoogleAccount.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if not row:
        # Missing, foreign, and wrong-message IDs are intentionally indistinguishable.
        raise HTTPException(status_code=404, detail="Attachment not found")
    return row


@router.get("/{email_id}/attachments/{attachment_id}/download")
async def download_attachment(
    email_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download one attachment after strict account and message membership checks."""
    email, attachment, account = await _owned_attachment_row(
        email_id,
        attachment_id,
        db,
        user.id,
    )

    try:
        content = await load_attachment_bytes(db, email, attachment, account)
    except AttachmentDownloadError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.public_detail,
        ) from exc

    return Response(
        content=content,
        headers={
            "Content-Type": safe_content_type(attachment.content_type),
            "Content-Disposition": attachment_content_disposition(attachment.filename),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.get("/{email_id}/attachments/{attachment_id}/preview")
async def preview_attachment(
    email_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a byte-classified isolated preview after the same ownership check."""
    email, attachment, account = await _owned_attachment_row(
        email_id,
        attachment_id,
        db,
        user.id,
    )
    if (
        attachment.size_bytes is not None
        and attachment.size_bytes > MAX_ATTACHMENT_PREVIEW_BYTES
    ):
        raise HTTPException(
            status_code=413,
            detail="This attachment is too large to preview",
    )
    try:
        preview = await load_and_build_attachment_preview(
            lambda: load_attachment_bytes(db, email, attachment, account)
        )
    except AttachmentDownloadError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.public_detail,
        ) from exc
    except AttachmentPreviewError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.public_detail,
        ) from exc

    return Response(
        content=preview.content,
        headers={
            "Content-Type": preview.content_type,
            "Content-Disposition": attachment_content_disposition(
                attachment.filename,
                disposition="inline",
            ),
            "X-Attachment-Preview-Kind": preview.kind,
            "X-Attachment-Preview-Truncated": str(preview.truncated).lower(),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": (
                "sandbox; default-src 'none'; script-src 'none'; "
                "object-src 'none'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'self'"
            ),
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


@router.get("/thread/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    account_id: Optional[int] = Query(None, gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Keep the account identity attached to every thread member. Reply clients
    # must not guess a sending account when a user owns multiple mailboxes.
    account_query = select(GoogleAccount.id, GoogleAccount.email).where(
        GoogleAccount.user_id == user.id
    )
    if account_id is not None:
        account_query = account_query.where(GoogleAccount.id == account_id)
    acct_result = await db.execute(account_query)
    account_emails = {row[0]: row[1] for row in acct_result.all()}
    account_ids = list(account_emails)
    if not account_ids:
        raise HTTPException(status_code=404, detail="Thread not found")

    order_clause = desc(Email.date) if order == "desc" else asc(Email.date)
    result = await db.execute(
        select(Email)
        .options(selectinload(Email.attachments), selectinload(Email.ai_analysis))
        .where(
            Email.gmail_thread_id == thread_id,
            Email.account_id.in_(account_ids),
        ).order_by(order_clause)
    )
    emails = result.scalars().all()

    if not emails:
        raise HTTPException(status_code=404, detail="Thread not found")
    if account_id is None and len({email.account_id for email in emails}) > 1:
        raise HTTPException(
            status_code=409,
            detail="Account scope is required for this conversation",
        )

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
            account_id=e.account_id,
            account_email=account_emails[e.account_id],
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
            is_sent=e.is_sent,
            is_trash=e.is_trash,
            is_spam=e.is_spam,
            has_attachments=e.has_attachments,
            labels=e.labels or [],
            size_bytes=e.size_bytes,
            reply_to=e.reply_to,
            message_id_header=e.message_id_header,
            in_reply_to=e.in_reply_to,
            references_header=e.references_header,
            attachments=attachments,
        ))

    return ThreadResponse(
        thread_id=thread_id,
        subject=emails[0].subject,
        emails=email_details,
        participants=list(participants_set.values()),
    )


def _mail_action_operation_response(actions) -> MailActionOperationResponse:
    first = actions[0]
    return MailActionOperationResponse(
        request_id=first.request_id,
        idempotency_key=first.idempotency_key,
        action=first.action,
        state=aggregate_action_state(actions),
        accepted_count=len(actions),
        undo_until=max(action.undo_until for action in actions),
        created_at=min(action.created_at for action in actions),
        items=[MailActionItemResponse.model_validate(action) for action in actions],
    )


def _raise_mail_action_http_error(error: Exception):
    if isinstance(error, MailActionNotFound):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, MailActionConflict):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, MailActionValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.post(
    "/actions",
    response_model=MailActionOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def email_actions(
    request: EmailActionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if request.label is not None:
        raise HTTPException(status_code=422, detail="Custom label actions are not supported")
    try:
        actions, created = await stage_mail_actions(
            db,
            user_id=user.id,
            email_ids=request.email_ids,
            action=request.action,
            idempotency_key=request.idempotency_key,
            label_id=request.label_id,
            scope=request.scope,
        )
    except (MailActionNotFound, MailActionConflict, MailActionValidationError) as error:
        _raise_mail_action_http_error(error)
    if created:
        background_tasks.add_task(try_enqueue_mail_action_drain)
    return _mail_action_operation_response(actions)


@router.get("/actions/recent", response_model=list[MailActionOperationResponse])
async def recent_email_actions(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    operations = await recent_mail_action_operations(db, user_id=user.id, limit=limit)
    return [_mail_action_operation_response(actions) for actions in operations]


@router.get(
    "/actions/by-idempotency/{idempotency_key}",
    response_model=MailActionOperationResponse,
)
async def get_email_action_by_idempotency(
    idempotency_key: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        actions = await get_mail_action_operation_by_idempotency(
            db,
            user_id=user.id,
            idempotency_key=idempotency_key,
        )
    except MailActionNotFound as error:
        _raise_mail_action_http_error(error)
    return _mail_action_operation_response(actions)


@router.get("/actions/{request_id}", response_model=MailActionOperationResponse)
async def get_email_action(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        actions = await get_mail_action_operation(
            db,
            user_id=user.id,
            request_id=request_id,
        )
    except MailActionNotFound as error:
        _raise_mail_action_http_error(error)
    return _mail_action_operation_response(actions)


@router.post("/actions/{request_id}/undo", response_model=MailActionOperationResponse)
async def undo_email_action(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        actions = await undo_mail_action_operation(
            db,
            user_id=user.id,
            request_id=request_id,
        )
    except (MailActionNotFound, MailActionConflict) as error:
        _raise_mail_action_http_error(error)
    return _mail_action_operation_response(actions)


@router.post("/actions/{request_id}/retry", response_model=MailActionOperationResponse)
async def retry_email_action(
    request_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        actions = await retry_mail_action_operation(
            db,
            user_id=user.id,
            request_id=request_id,
        )
    except (MailActionNotFound, MailActionConflict) as error:
        _raise_mail_action_http_error(error)
    background_tasks.add_task(try_enqueue_mail_action_drain)
    return _mail_action_operation_response(actions)


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
