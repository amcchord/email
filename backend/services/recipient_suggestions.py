"""Account-scoped correspondent suggestions for Compose.

Suggestions are derived only from already-synchronized message metadata. The
query deliberately reads one index-bounded recent account corpus instead of
turning every keystroke into an unbounded address-book scan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import formataddr, getaddresses
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.email import Email


RECIPIENT_CORPUS_ROW_LIMIT = 4_000
RECIPIENTS_PER_SENT_MESSAGE = 100
MAX_RECIPIENT_SUGGESTIONS = 20

_EMAIL_ADDRESS_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


class RecipientAccountNotFound(LookupError):
    """The requested active account is not owned by the current user."""


@dataclass(frozen=True, slots=True)
class RecipientSuggestion:
    name: str | None
    address: str
    formatted: str


@dataclass(slots=True)
class _Aggregate:
    address: str
    name: str | None = None
    name_seen_at: float = float("-inf")
    last_seen_at: float = float("-inf")
    frequency: int = 0
    outgoing: bool = False


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
    """Return one normalized display name and address, or ``None``.

    Synchronized recipient arrays have existed in both object and legacy
    string shapes, so the reader accepts either without guessing malformed
    multi-address strings.
    """

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


def _seen_at(value: Any) -> float:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return float("-inf")
    if not isinstance(value, datetime):
        return float("-inf")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _prefer_name(current: _Aggregate, name: str | None, seen_at: float) -> None:
    if not name:
        return
    if seen_at > current.name_seen_at:
        current.name = name
        current.name_seen_at = seen_at
        return
    if seen_at == current.name_seen_at and (
        current.name is None or name.casefold() < current.name.casefold()
    ):
        current.name = name


def _add_candidate(
    aggregates: dict[str, _Aggregate],
    *,
    mailbox: tuple[str | None, str] | None,
    seen_at: float,
    outgoing: bool,
    owned_addresses: set[str],
) -> None:
    if mailbox is None:
        return
    name, address = mailbox
    if address in owned_addresses:
        return
    candidate = aggregates.setdefault(address, _Aggregate(address=address))
    candidate.frequency += 1
    candidate.outgoing = candidate.outgoing or outgoing
    candidate.last_seen_at = max(candidate.last_seen_at, seen_at)
    _prefer_name(candidate, name, seen_at)


def _recipient_values(row: Any) -> Iterable[Any]:
    remaining = RECIPIENTS_PER_SENT_MESSAGE
    for field in ("to_addresses", "cc_addresses", "bcc_addresses"):
        values = _row_value(row, field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if remaining <= 0:
                return
            remaining -= 1
            yield value


def _match_tier(candidate: _Aggregate, query: str) -> int | None:
    if not query:
        return 0
    address = candidate.address.casefold()
    name = (candidate.name or "").casefold()
    if query == address or (name and query == name):
        return 0
    if address.startswith(query) or name.startswith(query):
        return 1
    if any(token.startswith(query) for token in re.split(r"[^a-z0-9@._+-]+", name) if token):
        return 1
    if query in address or query in name:
        return 2
    return None


def build_recipient_suggestions(
    *,
    corpus_rows: Iterable[Any],
    owned_addresses: Iterable[str],
    query: str = "",
    limit: int = 8,
) -> list[RecipientSuggestion]:
    """Normalize, deduplicate, and rank a bounded correspondent corpus."""

    owned = {
        mailbox[1]
        for value in owned_addresses
        if (mailbox := _mailbox(value)) is not None
    }
    aggregates: dict[str, _Aggregate] = {}

    for row in corpus_rows:
        if any(
            _row_value(row, flag) is True
            for flag in ("is_draft", "is_spam", "is_trash")
        ):
            continue
        seen_at = _seen_at(_row_value(row, "date"))
        outgoing = _row_value(row, "is_sent") is True
        if not outgoing:
            _add_candidate(
                aggregates,
                mailbox=_mailbox(
                    _row_value(row, "from_address"),
                    _row_value(row, "from_name"),
                ),
                seen_at=seen_at,
                outgoing=False,
                owned_addresses=owned,
            )
            continue

        seen_in_message: set[str] = set()
        for value in _recipient_values(row):
            mailbox = _mailbox(value)
            if mailbox is None or mailbox[1] in seen_in_message:
                continue
            seen_in_message.add(mailbox[1])
            _add_candidate(
                aggregates,
                mailbox=mailbox,
                seen_at=seen_at,
                outgoing=outgoing,
                owned_addresses=owned,
            )

    normalized_query = " ".join(str(query or "").split()).casefold()
    ranked: list[tuple[tuple[Any, ...], _Aggregate]] = []
    for candidate in aggregates.values():
        tier = _match_tier(candidate, normalized_query)
        if tier is None:
            continue
        ranked.append((
            (
                tier,
                0 if candidate.outgoing else 1,
                -candidate.last_seen_at,
                -candidate.frequency,
                candidate.address,
            ),
            candidate,
        ))
    ranked.sort(key=lambda item: item[0])

    safe_limit = max(1, min(int(limit), MAX_RECIPIENT_SUGGESTIONS))
    return [
        RecipientSuggestion(
            name=candidate.name,
            address=candidate.address,
            formatted=formataddr((candidate.name, candidate.address))
            if candidate.name
            else candidate.address,
        )
        for _ranking, candidate in ranked[:safe_limit]
    ]


def _corpus_statement(account_id: int):
    return (
        select(
            Email.from_address.label("from_address"),
            Email.from_name.label("from_name"),
            Email.to_addresses.label("to_addresses"),
            Email.cc_addresses.label("cc_addresses"),
            Email.bcc_addresses.label("bcc_addresses"),
            Email.date.label("date"),
            Email.is_sent.label("is_sent"),
            Email.is_draft.label("is_draft"),
            Email.is_spam.label("is_spam"),
            Email.is_trash.label("is_trash"),
        )
        .where(
            Email.account_id == account_id,
            Email.date.isnot(None),
        )
        .order_by(Email.date.desc())
        .limit(RECIPIENT_CORPUS_ROW_LIMIT)
    )


async def suggest_recipients(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    query: str = "",
    limit: int = 8,
) -> list[RecipientSuggestion]:
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
        raise RecipientAccountNotFound("Account not found")

    corpus_result = await db.execute(_corpus_statement(account_id))
    return build_recipient_suggestions(
        corpus_rows=corpus_result.all(),
        owned_addresses=[_row_value(row, "email", "") for row in account_rows],
        query=query,
        limit=limit,
    )
