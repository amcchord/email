"""Private contact profiles derived from bounded synchronized mail metadata.

This module deliberately does not create address-book truth.  Each response is
an exact-account projection of the latest eligible synchronized rows, with an
explicit coverage horizon and no message content or provider call.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import formataddr, getaddresses
import hashlib
import hmac
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.email import Email


CONTACT_CORPUS_ROW_LIMIT = 4_000
CONTACT_RECIPIENTS_PER_SENT_MESSAGE = 100
MAX_CONTACT_PAGE_SIZE = 100
MAX_RECENT_CONTACT_CONVERSATIONS = 20
CONTACT_KEY_VERSION = "contact-profile:v1"

_EMAIL_ADDRESS_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


class ContactNotFound(LookupError):
    """The requested account or contact projection is unavailable to the user."""


@dataclass(frozen=True, slots=True)
class ContactCoverage:
    rows_scanned: int
    row_limit: int
    history_may_be_truncated: bool
    observed_oldest_at: datetime | None
    observed_newest_at: datetime | None


@dataclass(frozen=True, slots=True)
class ContactSummary:
    account_id: int
    contact_key: str
    name: str | None
    address: str
    formatted: str
    relationship: str
    observed_message_count: int
    observed_received_count: int
    observed_sent_count: int
    observed_conversation_count: int
    observed_first_at: datetime
    observed_last_at: datetime
    observed_last_received_at: datetime | None
    observed_last_sent_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecentContactConversation:
    account_id: int
    anchor_email_id: int
    thread_id: str | None
    observed_last_at: datetime
    observed_message_count: int
    direction: str


@dataclass(frozen=True, slots=True)
class ContactQueryPage:
    account_id: int
    page: int
    page_size: int
    total: int
    total_pages: int
    coverage: ContactCoverage
    contacts: list[ContactSummary]


@dataclass(frozen=True, slots=True)
class ContactProfile:
    account_id: int
    contact: ContactSummary
    recent_conversations: list[RecentContactConversation]


@dataclass(slots=True)
class _ConversationAggregate:
    anchor_email_id: int
    thread_id: str | None
    observed_last_at: datetime
    observed_message_count: int = 0
    inbound: bool = False
    outbound: bool = False


@dataclass(slots=True)
class _ContactAggregate:
    address: str
    name: str | None = None
    name_seen_at: datetime | None = None
    observed_message_count: int = 0
    observed_received_count: int = 0
    observed_sent_count: int = 0
    observed_first_at: datetime | None = None
    observed_last_at: datetime | None = None
    observed_last_received_at: datetime | None = None
    observed_last_sent_at: datetime | None = None
    conversations: dict[str, _ConversationAggregate] = field(default_factory=dict)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None and key in mapping:
        return mapping[key]
    return getattr(row, key, default)


def _clean_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", value).split())
    return cleaned[:255] or None


def _mailbox(value: Any, explicit_name: Any = None) -> tuple[str | None, str] | None:
    if isinstance(value, Mapping):
        explicit_name = value.get("name") or value.get("display_name")
        value = value.get("address") or value.get("email")
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or len(raw) > 998 or "\r" in raw or "\n" in raw:
        return None
    parsed = getaddresses([raw])
    if len(parsed) != 1:
        return None
    parsed_name, address = parsed[0]
    address = address.strip().lower()
    if not _EMAIL_ADDRESS_RE.fullmatch(address):
        return None
    name = _clean_name(explicit_name) or _clean_name(parsed_name)
    if name and name.casefold() == address.casefold():
        name = None
    return name, address


def _observed_at(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _positive_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _thread_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", value).strip()
    return cleaned[:255] or None


def _is_eligible_row(row: Any) -> bool:
    return not any(
        _row_value(row, flag) is True
        for flag in ("is_draft", "is_spam", "is_trash")
    )


def _sent_recipient_mailboxes(row: Any) -> Iterable[tuple[str | None, str]]:
    remaining = CONTACT_RECIPIENTS_PER_SENT_MESSAGE
    seen: set[str] = set()
    # Bcc is intentionally excluded from the contact projection.
    for field_name in ("to_addresses", "cc_addresses"):
        values = _row_value(row, field_name, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if remaining <= 0:
                return
            remaining -= 1
            mailbox = _mailbox(value)
            if mailbox is None or mailbox[1] in seen:
                continue
            seen.add(mailbox[1])
            yield mailbox


def contact_key_for_address(
    *,
    user_id: int,
    account_id: int,
    address: str,
    secret_key: str,
) -> str:
    mailbox = _mailbox(address)
    if mailbox is None:
        raise ValueError("Contact address is invalid")
    message = "\0".join((
        CONTACT_KEY_VERSION,
        str(user_id),
        str(account_id),
        mailbox[1],
    )).encode("utf-8")
    return hmac.new(str(secret_key).encode("utf-8"), message, hashlib.sha256).hexdigest()


def _prefer_name(
    aggregate: _ContactAggregate,
    name: str | None,
    observed_at: datetime,
) -> None:
    if not name:
        return
    if aggregate.name_seen_at is None or observed_at > aggregate.name_seen_at:
        aggregate.name = name
        aggregate.name_seen_at = observed_at
        return
    if observed_at == aggregate.name_seen_at and (
        aggregate.name is None or name.casefold() < aggregate.name.casefold()
    ):
        aggregate.name = name


def _conversation_direction(conversation: _ConversationAggregate) -> str:
    if conversation.inbound and conversation.outbound:
        return "bidirectional"
    return "outbound_only" if conversation.outbound else "inbound_only"


def _relationship(aggregate: _ContactAggregate) -> str:
    if aggregate.observed_received_count and aggregate.observed_sent_count:
        return "bidirectional"
    return "outbound_only" if aggregate.observed_sent_count else "inbound_only"


def _update_contact(
    aggregates: dict[str, _ContactAggregate],
    *,
    mailbox: tuple[str | None, str],
    observed_at: datetime,
    outbound: bool,
    email_id: int,
    thread_id: str | None,
    owned_addresses: set[str],
) -> None:
    name, address = mailbox
    if address in owned_addresses:
        return
    aggregate = aggregates.setdefault(address, _ContactAggregate(address=address))
    aggregate.observed_message_count += 1
    aggregate.observed_first_at = min(
        observed_at,
        aggregate.observed_first_at or observed_at,
    )
    aggregate.observed_last_at = max(
        observed_at,
        aggregate.observed_last_at or observed_at,
    )
    if outbound:
        aggregate.observed_sent_count += 1
        aggregate.observed_last_sent_at = max(
            observed_at,
            aggregate.observed_last_sent_at or observed_at,
        )
    else:
        aggregate.observed_received_count += 1
        aggregate.observed_last_received_at = max(
            observed_at,
            aggregate.observed_last_received_at or observed_at,
        )
    _prefer_name(aggregate, name, observed_at)

    identity = f"thread:{thread_id}" if thread_id else f"message:{email_id}"
    conversation = aggregate.conversations.get(identity)
    if conversation is None:
        conversation = _ConversationAggregate(
            anchor_email_id=email_id,
            thread_id=thread_id,
            observed_last_at=observed_at,
        )
        aggregate.conversations[identity] = conversation
    elif (observed_at, email_id) > (
        conversation.observed_last_at,
        conversation.anchor_email_id,
    ):
        conversation.anchor_email_id = email_id
        conversation.observed_last_at = observed_at
    conversation.observed_message_count += 1
    conversation.outbound = conversation.outbound or outbound
    conversation.inbound = conversation.inbound or not outbound


def _match_tier(aggregate: _ContactAggregate, query: str) -> int | None:
    if not query:
        return 0
    address = aggregate.address.casefold()
    name = (aggregate.name or "").casefold()
    if query == address or (name and query == name):
        return 0
    if address.startswith(query) or name.startswith(query):
        return 1
    if any(
        token.startswith(query)
        for token in re.split(r"[^a-z0-9@._+-]+", name)
        if token
    ):
        return 1
    if query in address or query in name:
        return 2
    return None


def _summary(
    aggregate: _ContactAggregate,
    *,
    user_id: int,
    account_id: int,
    secret_key: str,
) -> ContactSummary:
    if aggregate.observed_first_at is None or aggregate.observed_last_at is None:
        raise ValueError("Contact aggregate has no observed dates")
    return ContactSummary(
        account_id=account_id,
        contact_key=contact_key_for_address(
            user_id=user_id,
            account_id=account_id,
            address=aggregate.address,
            secret_key=secret_key,
        ),
        name=aggregate.name,
        address=aggregate.address,
        formatted=(
            formataddr((aggregate.name, aggregate.address))
            if aggregate.name
            else aggregate.address
        ),
        relationship=_relationship(aggregate),
        observed_message_count=aggregate.observed_message_count,
        observed_received_count=aggregate.observed_received_count,
        observed_sent_count=aggregate.observed_sent_count,
        observed_conversation_count=len(aggregate.conversations),
        observed_first_at=aggregate.observed_first_at,
        observed_last_at=aggregate.observed_last_at,
        observed_last_received_at=aggregate.observed_last_received_at,
        observed_last_sent_at=aggregate.observed_last_sent_at,
    )


def _project_contacts(
    *,
    corpus_rows: Iterable[Any],
    owned_addresses: Iterable[str],
) -> tuple[ContactCoverage, dict[str, _ContactAggregate]]:
    owned = {
        mailbox[1]
        for value in owned_addresses
        if (mailbox := _mailbox(value)) is not None
    }
    eligible: list[tuple[datetime, int, Any]] = []
    for row in corpus_rows:
        if not _is_eligible_row(row):
            continue
        observed_at = _observed_at(_row_value(row, "date"))
        email_id = _positive_id(_row_value(row, "id"))
        if observed_at is None or email_id is None:
            continue
        eligible.append((observed_at, email_id, row))
    eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
    history_may_be_truncated = len(eligible) >= CONTACT_CORPUS_ROW_LIMIT
    selected = eligible[:CONTACT_CORPUS_ROW_LIMIT]

    aggregates: dict[str, _ContactAggregate] = {}
    for observed_at, email_id, row in selected:
        outbound = _row_value(row, "is_sent") is True
        thread_id = _thread_id(_row_value(row, "gmail_thread_id"))
        mailboxes = (
            _sent_recipient_mailboxes(row)
            if outbound
            else iter((
                _mailbox(
                    _row_value(row, "from_address"),
                    _row_value(row, "from_name"),
                ),
            ))
        )
        for mailbox in mailboxes:
            if mailbox is None:
                continue
            _update_contact(
                aggregates,
                mailbox=mailbox,
                observed_at=observed_at,
                outbound=outbound,
                email_id=email_id,
                thread_id=thread_id,
                owned_addresses=owned,
            )

    observed_dates = [item[0] for item in selected]
    return ContactCoverage(
        rows_scanned=len(selected),
        row_limit=CONTACT_CORPUS_ROW_LIMIT,
        history_may_be_truncated=history_may_be_truncated,
        observed_oldest_at=min(observed_dates) if observed_dates else None,
        observed_newest_at=max(observed_dates) if observed_dates else None,
    ), aggregates


def build_contact_query_page(
    *,
    corpus_rows: Iterable[Any],
    owned_addresses: Iterable[str],
    user_id: int,
    account_id: int,
    secret_key: str,
    query: str = "",
    relationship: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> ContactQueryPage:
    coverage, aggregates = _project_contacts(
        corpus_rows=corpus_rows,
        owned_addresses=owned_addresses,
    )
    normalized_query = " ".join(str(query or "").split()).casefold()
    ranked: list[tuple[tuple[Any, ...], _ContactAggregate]] = []
    for aggregate in aggregates.values():
        aggregate_relationship = _relationship(aggregate)
        if relationship != "all" and aggregate_relationship != relationship:
            continue
        tier = _match_tier(aggregate, normalized_query)
        if tier is None or aggregate.observed_last_at is None:
            continue
        relationship_tier = {
            "bidirectional": 0,
            "outbound_only": 1,
            "inbound_only": 2,
        }[aggregate_relationship]
        ranked.append((
            (
                tier,
                -aggregate.observed_last_at.timestamp(),
                relationship_tier,
                -aggregate.observed_message_count,
                aggregate.address,
            ),
            aggregate,
        ))
    ranked.sort(key=lambda item: item[0])

    safe_page = max(1, int(page))
    safe_page_size = max(1, min(int(page_size), MAX_CONTACT_PAGE_SIZE))
    total = len(ranked)
    total_pages = (total + safe_page_size - 1) // safe_page_size if total else 0
    start = (safe_page - 1) * safe_page_size
    contacts = [
        _summary(
            aggregate,
            user_id=user_id,
            account_id=account_id,
            secret_key=secret_key,
        )
        for _sort, aggregate in ranked[start:start + safe_page_size]
    ]
    return ContactQueryPage(
        account_id=account_id,
        page=safe_page,
        page_size=safe_page_size,
        total=total,
        total_pages=total_pages,
        coverage=coverage,
        contacts=contacts,
    )


def build_contact_profile(
    *,
    corpus_rows: Iterable[Any],
    owned_addresses: Iterable[str],
    user_id: int,
    account_id: int,
    contact_key: str,
    secret_key: str,
    recent_limit: int = 8,
) -> ContactProfile:
    _coverage, aggregates = _project_contacts(
        corpus_rows=corpus_rows,
        owned_addresses=owned_addresses,
    )
    selected: _ContactAggregate | None = None
    for aggregate in aggregates.values():
        candidate_key = contact_key_for_address(
            user_id=user_id,
            account_id=account_id,
            address=aggregate.address,
            secret_key=secret_key,
        )
        if hmac.compare_digest(candidate_key, str(contact_key)):
            selected = aggregate
            break
    if selected is None:
        raise ContactNotFound("Contact not found")

    safe_limit = max(1, min(int(recent_limit), MAX_RECENT_CONTACT_CONVERSATIONS))
    recent = sorted(
        selected.conversations.values(),
        key=lambda conversation: (
            conversation.observed_last_at,
            conversation.anchor_email_id,
            conversation.thread_id or "",
        ),
        reverse=True,
    )[:safe_limit]
    return ContactProfile(
        account_id=account_id,
        contact=_summary(
            selected,
            user_id=user_id,
            account_id=account_id,
            secret_key=secret_key,
        ),
        recent_conversations=[
            RecentContactConversation(
                account_id=account_id,
                anchor_email_id=conversation.anchor_email_id,
                thread_id=conversation.thread_id,
                observed_last_at=conversation.observed_last_at,
                observed_message_count=conversation.observed_message_count,
                direction=_conversation_direction(conversation),
            )
            for conversation in recent
        ],
    )


def _corpus_statement(account_id: int):
    return (
        select(
            Email.id.label("id"),
            Email.gmail_thread_id.label("gmail_thread_id"),
            Email.from_address.label("from_address"),
            Email.from_name.label("from_name"),
            Email.to_addresses.label("to_addresses"),
            Email.cc_addresses.label("cc_addresses"),
            Email.date.label("date"),
            Email.is_sent.label("is_sent"),
            Email.is_draft.label("is_draft"),
            Email.is_spam.label("is_spam"),
            Email.is_trash.label("is_trash"),
        )
        .where(
            Email.account_id == account_id,
            Email.date.isnot(None),
            Email.is_draft.is_not(True),
            Email.is_spam.is_not(True),
            Email.is_trash.is_not(True),
        )
        .order_by(Email.date.desc(), Email.id.desc())
        .limit(CONTACT_CORPUS_ROW_LIMIT)
    )


async def _load_owned_contact_corpus(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
) -> tuple[list[str], list[Any]]:
    account_result = await db.execute(
        select(
            GoogleAccount.id.label("id"),
            GoogleAccount.email.label("email"),
            GoogleAccount.is_active.label("is_active"),
        ).where(GoogleAccount.user_id == user_id)
    )
    account_rows = account_result.all()
    target = next(
        (
            row
            for row in account_rows
            if int(_row_value(row, "id", 0)) == account_id
            and _row_value(row, "is_active") is True
        ),
        None,
    )
    if target is None:
        raise ContactNotFound("Contact not found")

    corpus_result = await db.execute(_corpus_statement(account_id))
    return (
        [_row_value(row, "email", "") for row in account_rows],
        list(corpus_result.all()),
    )


async def query_contact_profiles(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    secret_key: str,
    query: str = "",
    relationship: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> ContactQueryPage:
    owned_addresses, corpus_rows = await _load_owned_contact_corpus(
        db,
        user_id=user_id,
        account_id=account_id,
    )
    return build_contact_query_page(
        corpus_rows=corpus_rows,
        owned_addresses=owned_addresses,
        user_id=user_id,
        account_id=account_id,
        secret_key=secret_key,
        query=query,
        relationship=relationship,
        page=page,
        page_size=page_size,
    )


async def get_contact_profile(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    contact_key: str,
    secret_key: str,
    recent_limit: int = 8,
) -> ContactProfile:
    owned_addresses, corpus_rows = await _load_owned_contact_corpus(
        db,
        user_id=user_id,
        account_id=account_id,
    )
    return build_contact_profile(
        corpus_rows=corpus_rows,
        owned_addresses=owned_addresses,
        user_id=user_id,
        account_id=account_id,
        contact_key=contact_key,
        secret_key=secret_key,
        recent_limit=recent_limit,
    )
