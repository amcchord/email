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

from sqlalchemy import Select, and_, asc, case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.email import Email


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


def conversation_count_statement(filtered_messages: Select[Any]):
    ranked = _ranked_matches(filtered_messages)
    return select(func.count()).select_from(ranked).where(ranked.c.match_rank == 1)


def conversation_page_statement(
    filtered_messages: Select[Any],
    *,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
):
    ranked = _ranked_matches(filtered_messages)
    anchors = (
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
    member_identity = _conversation_identity(Email.id, Email.gmail_thread_id)
    aggregates = (
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

    statement = (
        select(
            Email,
            anchors.c.conversation_identity,
            anchors.c.matched_count,
            aggregates.c.member_count,
            aggregates.c.unread_count,
            aggregates.c.starred_count,
            aggregates.c.attachment_count,
            aggregates.c.member_labels,
        )
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

    allowed = {"date", "subject", "sender", "is_read", "has_attachments"}
    selected_sort = sort_by if sort_by in allowed else "date"
    if selected_sort == "sender":
        primary_sort = Email.from_address
    elif selected_sort == "is_read":
        # A conversation is read only when every synchronized member is read.
        primary_sort = aggregates.c.unread_count
    elif selected_sort == "has_attachments":
        primary_sort = aggregates.c.attachment_count
    else:
        primary_sort = getattr(Email, selected_sort)

    direction = asc if sort_order == "asc" else desc
    statement = statement.order_by(
        direction(primary_sort).nulls_last(),
        direction(anchors.c.matched_date).nulls_last(),
        direction(anchors.c.anchor_email_id),
    )
    return statement.offset((page - 1) * page_size).limit(page_size)


async def load_conversation_page(
    db: AsyncSession,
    filtered_messages: Select[Any],
    *,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
) -> tuple[list[ConversationRow], int]:
    """Return one exact row per matching account/thread plus exact total."""
    total = int(await db.scalar(conversation_count_statement(filtered_messages)) or 0)
    if total == 0:
        return [], 0
    result = await db.execute(
        conversation_page_statement(
            filtered_messages,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )
    rows = [
        ConversationRow(
            anchor=row[0],
            conversation_identity=str(row.conversation_identity),
            matched_count=int(row.matched_count),
            member_count=int(row.member_count),
            unread_count=int(row.unread_count),
            starred_count=int(row.starred_count),
            attachment_count=int(row.attachment_count),
            member_labels=[list(labels or []) for labels in (row.member_labels or [])],
        )
        for row in result.all()
    ]
    return rows, total
