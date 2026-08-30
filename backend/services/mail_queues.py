"""Reusable mail-queue queries shared by the AI router and the e-ink
Day Ahead display.

The "needs a reply", "awaiting response", and "unread" counts power both
the Flow dashboard (`backend/routers/ai.py`) and the portrait Day Ahead
screen (`backend/services/eink/day_client.py`). Keeping the query logic in
one place means the two surfaces can never drift -- a fix to the
thread-dedup / reply-exclusion rules lands in both at once.

Each builder is pure SQLAlchemy construction (no I/O); the `fetch_*`
helpers run them against a session and return `(total, rows)` so callers
can layer their own presentation + side effects on top.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, desc, func, literal, or_
from sqlalchemy import func as sqla_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis, ThreadDigest
from backend.models.email import Email
from backend.routers.emails import jsonb_contains
from backend.services.workflow_context import delegated_scheduling_sql


# ── Needs a reply ───────────────────────────────────────────────────────


def _needs_reply_deduped(account_ids: list[int], *, exclude_category: Optional[str] = None):
    """Build the deduped subquery of emails that need a reply.

    Keeps the latest needs-reply email per Gmail thread, excludes threads
    that already have a later sent reply (same thread or via In-Reply-To),
    then collapses cross-account duplicates by Message-ID. Mirror of the
    query in `backend/routers/ai.py::get_needs_reply`.
    """
    account_filter = Email.account_id.in_(account_ids)
    delegated_scheduling = delegated_scheduling_sql(
        AIAnalysis.conversation_type,
        Email.to_addresses,
        Email.cc_addresses,
    )

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
            (AIAnalysis.needs_reply_snoozed_until == None)
            | (AIAnalysis.needs_reply_snoozed_until <= datetime.now(timezone.utc)),
            Email.is_trash == False,
            Email.is_spam == False,
            AIAnalysis.is_subscription == False,
            # Andrea owns routine scheduling. Keep high/urgent exceptions in
            # Austin's personal reply queue, including for analyses created
            # before the workflow prompt was improved.
            or_(~delegated_scheduling, AIAnalysis.priority >= 2),
            ~has_later_reply,
            ~has_direct_reply_to,
            *([AIAnalysis.category != exclude_category] if exclude_category else []),
        )
        .distinct(Email.gmail_thread_id)
        .order_by(Email.gmail_thread_id, desc(Email.date))
    ).subquery()

    dedup_key = func.coalesce(
        deduped_by_thread.c.message_id_header,
        deduped_by_thread.c.gmail_thread_id,
    )
    deduped = (
        select(deduped_by_thread)
        .distinct(dedup_key)
        .order_by(dedup_key, desc(deduped_by_thread.c.date))
    ).subquery()
    return deduped


async def fetch_needs_reply(
    db: AsyncSession,
    account_ids: list[int],
    *,
    limit: int = 20,
    offset: int = 0,
    exclude_category: Optional[str] = None,
) -> tuple[int, list[Any]]:
    """Return `(total, rows)` for the needs-reply queue, newest first.

    `rows` are SQLAlchemy result rows carrying the columns selected in
    `_needs_reply_deduped` (id, subject, from_name, from_address, date, ...).
    """
    if not account_ids:
        return 0, []
    deduped = _needs_reply_deduped(account_ids, exclude_category=exclude_category)
    total = await db.scalar(select(func.count()).select_from(deduped)) or 0
    result = await db.execute(
        select(deduped)
        .order_by(desc(deduped.c.date))
        .offset(offset)
        .limit(limit)
    )
    return total, list(result.all())


# ── Awaiting response ───────────────────────────────────────────────────


def _awaiting_response_deduped(account_ids: list[int]):
    """Build the deduped subquery of sent emails still awaiting a reply.

    Mirror of `backend/routers/ai.py::get_awaiting_response`: sent within
    the last 14 days, no later received reply in the thread, thread not
    resolved (per ThreadDigest), and not a short closing reply (AI flag or
    heuristic), collapsed cross-account by Message-ID.
    """
    account_filter = Email.account_id.in_(account_ids)
    delegated_scheduling = delegated_scheduling_sql(
        ThreadDigest.conversation_type,
        Email.to_addresses,
        Email.cc_addresses,
    )

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

    SentAnalysis = aliased(AIAnalysis, flat=True)

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
    raw_body = sqla_func.coalesce(Email.body_text, Email.snippet, "")
    stripped_body = sqla_func.regexp_replace(
        raw_body,
        r"\r?\nOn [^\n]+wrote:\s*[\s\S]*$",
        "",
        "n",
    )
    stripped_body = sqla_func.regexp_replace(
        stripped_body,
        r"\r?\n-- ?\r?\n[\s\S]*$",
        "",
        "n",
    )
    stripped_len = sqla_func.length(sqla_func.trim(stripped_body))

    is_short_closing_reply = and_(
        has_prior_received,
        stripped_len < 200,
    )

    ai_says_no_reply = SentAnalysis.expects_reply == False
    heuristic_closing = and_(
        SentAnalysis.expects_reply.is_(None),
        is_short_closing_reply,
    )
    should_exclude = or_(ai_says_no_reply, heuristic_closing)

    fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)

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
            or_(
                ThreadDigest.is_resolved == False,
                ThreadDigest.is_resolved.is_(None),
            ),
            or_(
                ThreadDigest.conversation_type.is_(None),
                ~delegated_scheduling,
            ),
            ~should_exclude,
        )
        .distinct(Email.gmail_thread_id)
        .order_by(Email.gmail_thread_id, desc(Email.date))
    ).subquery()

    ar_dedup_key = func.coalesce(
        deduped_by_thread.c.message_id_header,
        deduped_by_thread.c.gmail_thread_id,
    )
    deduped = (
        select(deduped_by_thread)
        .distinct(ar_dedup_key)
        .order_by(ar_dedup_key, desc(deduped_by_thread.c.date))
    ).subquery()
    return deduped


async def fetch_awaiting_response(
    db: AsyncSession,
    account_ids: list[int],
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[Any]]:
    """Return `(total, rows)` for the awaiting-response queue, newest first.

    Pure read: unlike the router endpoint, this does NOT enqueue missing
    thread digests -- that side effect stays in the router so the e-ink
    assembler can call this cheaply.
    """
    if not account_ids:
        return 0, []
    deduped = _awaiting_response_deduped(account_ids)
    total = await db.scalar(select(func.count()).select_from(deduped)) or 0
    result = await db.execute(
        select(deduped)
        .order_by(desc(deduped.c.date))
        .offset(offset)
        .limit(limit)
    )
    return total, list(result.all())


# ── Unread ──────────────────────────────────────────────────────────────


async def fetch_unread_counts(
    db: AsyncSession,
    account_ids: list[int],
) -> tuple[int, dict[int, int]]:
    """Return `(total_unread, {account_id: unread})` for INBOX, non-junk.

    Mirror of `backend/routers/public_api.py::emails_unread_count`.
    """
    if not account_ids:
        return 0, {}
    base_filter = [
        Email.account_id.in_(account_ids),
        Email.is_read == False,
        Email.is_trash == False,
        Email.is_spam == False,
        jsonb_contains(Email.labels, '["INBOX"]'),
    ]
    total = await db.scalar(select(func.count(Email.id)).where(*base_filter)) or 0
    per_account = await db.execute(
        select(Email.account_id, func.count(Email.id))
        .where(*base_filter)
        .group_by(Email.account_id)
    )
    counts = {row[0]: row[1] for row in per_account.all()}
    return total, counts
