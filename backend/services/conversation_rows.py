"""PostgreSQL-authoritative conversation rows for mailbox and search results.

The caller supplies the fully owned and filtered message statement.  This
module first identifies matching conversation identities, chooses one stable
newest matching anchor, and only then paginates.  Member aggregates are joined
from every synchronized message in the exact account/thread identity, so a
client never has to infer conversation truth from one message page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, asc, case, desc, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload, selectinload

from backend.models.ai import AIAnalysis
from backend.models.email import Email
from backend.services.workflow_context import TRUSTED_CONTACTS, delegated_scheduling_sql


INBOX_PLACEMENTS = frozenset({"focused", "other"})
OTHER_PLACEMENT_REASONS = frozenset(
    {"delegated_scheduling", "subscription", "low_priority"}
)


@dataclass(frozen=True)
class ConversationRow:
    anchor: Email
    conversation_identity: str
    member_count: int
    matched_count: int
    unread_count: int
    starred_count: int
    attachment_count: int
    member_labels: list[list[str]]
    inbox_placement: str | None = None
    inbox_placement_reason: str | None = None


def _conversation_identity(email_id, gmail_thread_id):
    """Use provider thread identity, falling back to one isolated message."""
    normalized_thread = func.nullif(func.btrim(gmail_thread_id), "")
    return case(
        (normalized_thread.is_(None), func.concat("message:", email_id)),
        else_=func.concat("thread:", normalized_thread),
    )


def _ranked_matches(filtered_messages: Select[Any]):
    conversation_identity = _conversation_identity(Email.id, Email.gmail_thread_id)
    matching = (
        filtered_messages
        .order_by(None)
        .with_only_columns(
            Email.id.label("anchor_email_id"),
            Email.account_id.label("account_id"),
            Email.gmail_thread_id.label("gmail_thread_id"),
            conversation_identity.label("conversation_identity"),
            Email.date.label("matched_date"),
        )
        .cte("matching_messages")
    )
    identity = (matching.c.account_id, matching.c.conversation_identity)
    return select(
        matching.c.anchor_email_id,
        matching.c.account_id,
        matching.c.gmail_thread_id,
        matching.c.conversation_identity,
        matching.c.matched_date,
        func.row_number().over(
            partition_by=identity,
            order_by=(
                matching.c.matched_date.desc().nulls_last(),
                matching.c.anchor_email_id.desc(),
            ),
        ).label("match_rank"),
        func.count().over(partition_by=identity).label("matched_count"),
    ).cte("ranked_matching_messages")


def _conversation_anchors(filtered_messages: Select[Any]):
    ranked = _ranked_matches(filtered_messages)
    return (
        select(
            ranked.c.anchor_email_id,
            ranked.c.account_id,
            ranked.c.gmail_thread_id,
            ranked.c.conversation_identity,
            ranked.c.matched_date,
            ranked.c.matched_count,
        )
        .where(ranked.c.match_rank == 1)
        .cte("conversation_anchors")
    )


def _inbox_placement_reason(email, analysis):
    """Return one stable reason for the authoritative Inbox anchor.

    This uses only already-persisted analysis and exact deterministic workflow
    relationships. Missing or lagging analysis stays Focused so background AI
    work can never silently hide new mail.
    """
    sent_email = aliased(Email, flat=True)
    normalized_thread = func.nullif(func.btrim(email.gmail_thread_id), "")
    later_sent_reply = exists(
        select(literal(1))
        .select_from(sent_email)
        .where(
            normalized_thread.is_not(None),
            sent_email.account_id == email.account_id,
            sent_email.gmail_thread_id == email.gmail_thread_id,
            sent_email.is_sent.is_(True),
            sent_email.is_trash.is_(False),
            sent_email.date > email.date,
        )
        .correlate(email)
    )
    priority = func.coalesce(analysis.priority, 0)
    trusted_addresses = tuple(contact.email.lower() for contact in TRUSTED_CONTACTS)
    trusted_sender = func.lower(func.btrim(func.coalesce(email.from_address, ""))).in_(
        trusted_addresses
    )
    delegated_scheduling = delegated_scheduling_sql(
        analysis.conversation_type,
        email.to_addresses,
        email.cc_addresses,
    )
    active_needs_reply = and_(
        analysis.needs_reply.is_(True),
        analysis.needs_reply_ignored.is_not(True),
        ~delegated_scheduling,
        ~later_sent_reply,
    )
    return case(
        (or_(priority >= 2, analysis.category == "urgent"), "high_priority"),
        (active_needs_reply, "needs_reply"),
        (trusted_sender, "trusted_contact"),
        (and_(delegated_scheduling, priority < 2), "delegated_scheduling"),
        (analysis.is_subscription.is_(True), "subscription"),
        (analysis.category == "can_ignore", "low_priority"),
        (analysis.id.is_(None), "unclassified"),
        else_="direct_or_fyi",
    )


def _placed_conversation_anchors(filtered_messages: Select[Any]):
    anchors = _conversation_anchors(filtered_messages)
    reasoned = (
        select(
            anchors.c.anchor_email_id,
            anchors.c.account_id,
            anchors.c.gmail_thread_id,
            anchors.c.conversation_identity,
            anchors.c.matched_date,
            anchors.c.matched_count,
            _inbox_placement_reason(Email, AIAnalysis).label("inbox_placement_reason"),
        )
        .join(Email, Email.id == anchors.c.anchor_email_id)
        .outerjoin(AIAnalysis, AIAnalysis.email_id == Email.id)
        .cte("reasoned_conversation_anchors")
    )
    placement = case(
        (
            reasoned.c.inbox_placement_reason.in_(OTHER_PLACEMENT_REASONS),
            "other",
        ),
        else_="focused",
    )
    return (
        select(
            reasoned.c.anchor_email_id,
            reasoned.c.account_id,
            reasoned.c.gmail_thread_id,
            reasoned.c.conversation_identity,
            reasoned.c.matched_date,
            reasoned.c.matched_count,
            placement.label("inbox_placement"),
            reasoned.c.inbox_placement_reason,
        )
        .cte("placed_conversation_anchors")
    )


def conversation_count_statement(
    filtered_messages: Select[Any],
    *,
    inbox_placement: str | None = None,
):
    if inbox_placement is None:
        ranked = _ranked_matches(filtered_messages)
        return select(func.count()).select_from(ranked).where(ranked.c.match_rank == 1)
    placed = _placed_conversation_anchors(filtered_messages)
    return (
        select(func.count())
        .select_from(placed)
        .where(placed.c.inbox_placement == inbox_placement)
    )


def conversation_page_statement(
    filtered_messages: Select[Any],
    *,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
    inbox_placement: str | None = None,
):
    anchors = (
        _placed_conversation_anchors(filtered_messages)
        if inbox_placement is not None
        else _conversation_anchors(filtered_messages)
    )
    aggregates = _conversation_aggregates(anchors)

    selected_columns = [
        Email,
        anchors.c.conversation_identity,
        anchors.c.matched_count,
        aggregates.c.member_count,
        aggregates.c.unread_count,
        aggregates.c.starred_count,
        aggregates.c.attachment_count,
        aggregates.c.member_labels,
    ]
    if inbox_placement is not None:
        selected_columns.extend(
            [anchors.c.inbox_placement, anchors.c.inbox_placement_reason]
        )
    statement = (
        select(*selected_columns)
        .options(selectinload(Email.ai_analysis))
        .join(anchors, anchors.c.anchor_email_id == Email.id)
        .join(
            aggregates,
            and_(
                aggregates.c.account_id == anchors.c.account_id,
                aggregates.c.conversation_identity == anchors.c.conversation_identity,
            ),
        )
    )
    if inbox_placement is not None:
        statement = statement.where(anchors.c.inbox_placement == inbox_placement)

    primary_sort = _conversation_sort_expression(sort_by, Email, aggregates)
    direction = asc if sort_order == "asc" else desc
    statement = statement.order_by(
        direction(primary_sort).nulls_last(),
        direction(anchors.c.matched_date).nulls_last(),
        direction(anchors.c.anchor_email_id),
    )
    return statement.offset((page - 1) * page_size).limit(page_size)


def _conversation_aggregates(anchors):
    member_identity = _conversation_identity(Email.id, Email.gmail_thread_id)
    return (
        select(
            Email.account_id.label("account_id"),
            member_identity.label("conversation_identity"),
            func.count(Email.id).label("member_count"),
            func.count(Email.id)
            .filter(Email.is_read.is_(False))
            .label("unread_count"),
            func.count(Email.id)
            .filter(Email.is_starred.is_(True))
            .label("starred_count"),
            func.count(Email.id)
            .filter(Email.has_attachments.is_(True))
            .label("attachment_count"),
            func.jsonb_agg(
                case(
                    (Email.labels.is_(None), func.jsonb_build_array()),
                    else_=Email.labels,
                )
            ).label("member_labels"),
        )
        .join(
            anchors,
            and_(
                anchors.c.account_id == Email.account_id,
                anchors.c.conversation_identity == member_identity,
            ),
        )
        .group_by(Email.account_id, member_identity)
        .cte("conversation_aggregates")
    )


def _conversation_sort_expression(sort_by: str, email, aggregates):
    allowed = {"date", "subject", "sender", "is_read", "has_attachments"}
    selected_sort = sort_by if sort_by in allowed else "date"
    if selected_sort == "sender":
        return email.from_address
    if selected_sort == "is_read":
        # A conversation is read only when every synchronized member is read.
        return aggregates.c.unread_count
    if selected_sort == "has_attachments":
        return aggregates.c.attachment_count
    return getattr(email, selected_sort)


def conversation_split_page_statement(
    filtered_messages: Select[Any],
    *,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
):
    """Return both section pages and totals from one PostgreSQL statement."""
    anchors = _placed_conversation_anchors(filtered_messages)
    aggregates = _conversation_aggregates(anchors)
    direction = asc if sort_order == "asc" else desc
    primary_sort = _conversation_sort_expression(sort_by, Email, aggregates)
    ordering = (
        direction(primary_sort).nulls_last(),
        direction(anchors.c.matched_date).nulls_last(),
        direction(anchors.c.anchor_email_id),
    )
    sectioned = (
        select(
            anchors.c.anchor_email_id,
            anchors.c.account_id,
            anchors.c.conversation_identity,
            anchors.c.matched_count,
            anchors.c.inbox_placement,
            anchors.c.inbox_placement_reason,
            aggregates.c.member_count,
            aggregates.c.unread_count,
            aggregates.c.starred_count,
            aggregates.c.attachment_count,
            aggregates.c.member_labels,
            func.row_number().over(
                partition_by=anchors.c.inbox_placement,
                order_by=ordering,
            ).label("section_rank"),
        )
        .join(Email, Email.id == anchors.c.anchor_email_id)
        .join(
            aggregates,
            and_(
                aggregates.c.account_id == anchors.c.account_id,
                aggregates.c.conversation_identity == anchors.c.conversation_identity,
            ),
        )
        .cte("sectioned_conversation_rows")
    )
    focused_total = (
        select(func.count())
        .select_from(anchors)
        .where(anchors.c.inbox_placement == "focused")
        .scalar_subquery()
    )
    other_total = (
        select(func.count())
        .select_from(anchors)
        .where(anchors.c.inbox_placement == "other")
        .scalar_subquery()
    )
    first_rank = ((page - 1) * page_size) + 1
    last_rank = page * page_size
    page_rows = (
        select(sectioned)
        .where(sectioned.c.section_rank.between(first_rank, last_rank))
        .cte("paged_split_conversations")
    )
    totals = select(
        focused_total.label("focused_total"),
        other_total.label("other_total"),
    ).cte("split_conversation_totals")
    return (
        select(
            Email,
            page_rows.c.conversation_identity,
            page_rows.c.matched_count,
            page_rows.c.member_count,
            page_rows.c.unread_count,
            page_rows.c.starred_count,
            page_rows.c.attachment_count,
            page_rows.c.member_labels,
            page_rows.c.inbox_placement,
            page_rows.c.inbox_placement_reason,
            totals.c.focused_total,
            totals.c.other_total,
        )
        .options(joinedload(Email.ai_analysis))
        .select_from(
            totals
            .outerjoin(page_rows, literal(True))
            .outerjoin(Email, Email.id == page_rows.c.anchor_email_id)
        )
        .order_by(
            case((page_rows.c.inbox_placement == "focused", 0), else_=1),
            page_rows.c.section_rank,
        )
    )


def _conversation_row_from_result(row, *, with_placement: bool):
    return ConversationRow(
        anchor=row[0],
        conversation_identity=str(row.conversation_identity),
        matched_count=int(row.matched_count),
        member_count=int(row.member_count),
        unread_count=int(row.unread_count),
        starred_count=int(row.starred_count),
        attachment_count=int(row.attachment_count),
        member_labels=[list(labels or []) for labels in (row.member_labels or [])],
        inbox_placement=(str(row.inbox_placement) if with_placement else None),
        inbox_placement_reason=(
            str(row.inbox_placement_reason) if with_placement else None
        ),
    )


async def load_split_conversation_page(
    db: AsyncSession,
    filtered_messages: Select[Any],
    *,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
) -> tuple[list[ConversationRow], dict[str, int]]:
    """Load both Split Inbox sections from one coherent database statement."""
    result = await db.execute(
        conversation_split_page_statement(
            filtered_messages,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )
    records = result.all()
    totals = {"focused": 0, "other": 0}
    if records:
        totals = {
            "focused": int(records[0].focused_total or 0),
            "other": int(records[0].other_total or 0),
        }
    return [
        _conversation_row_from_result(row, with_placement=True)
        for row in records
        if row[0] is not None
    ], totals


async def load_conversation_page(
    db: AsyncSession,
    filtered_messages: Select[Any],
    *,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
    inbox_placement: str | None = None,
) -> tuple[list[ConversationRow], int]:
    """Return one exact row per matching account/thread plus exact total."""
    if inbox_placement is not None and inbox_placement not in INBOX_PLACEMENTS:
        raise ValueError("Inbox placement must be focused or other")
    total = int(
        await db.scalar(
            conversation_count_statement(
                filtered_messages,
                inbox_placement=inbox_placement,
            )
        )
        or 0
    )
    if total == 0:
        return [], 0
    result = await db.execute(
        conversation_page_statement(
            filtered_messages,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            inbox_placement=inbox_placement,
        )
    )
    rows = [
        _conversation_row_from_result(
            row,
            with_placement=inbox_placement is not None,
        )
        for row in result.all()
    ]
    return rows, total
