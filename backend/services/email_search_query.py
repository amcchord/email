"""Parse and compile the user-facing email search language.

The parser is deliberately independent of FastAPI and the database session so
the grammar can be exercised without touching a mailbox.  The compiler only
produces SQLAlchemy expressions; all user-provided values remain bind
parameters when those expressions are executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Text, and_, false, func, literal, not_, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.sql.elements import ColumnElement

from backend.models.email import Email


MAX_QUERY_LENGTH = 512
MAX_CLAUSES = 32
MAX_OPERAND_LENGTH = 256

RECOGNIZED_OPERATORS = frozenset({
    "from",
    "to",
    "cc",
    "bcc",
    "subject",
    "body",
    "after",
    "before",
    "is",
    "has",
    "in",
    "account",
    "label",
})
IS_VALUES = frozenset({"read", "unread", "starred", "unstarred", "draft", "sent"})
HAS_VALUES = frozenset({"attachment", "attachments"})
IN_VALUES = frozenset({
    "inbox",
    "sent",
    "drafts",
    "archive",
    "starred",
    "spam",
    "trash",
    "all",
    "anywhere",
})


class SearchQueryError(ValueError):
    """A stable, human-readable error safe to expose as a 422 detail."""


@dataclass(frozen=True)
class SearchClause:
    value: str
    operator: str | None = None
    negated: bool = False
    quoted: bool = False


@dataclass(frozen=True)
class SearchGroup:
    clauses: tuple[SearchClause, ...]


@dataclass(frozen=True)
class ParsedEmailSearch:
    groups: tuple[SearchGroup, ...]

    @property
    def clauses(self) -> tuple[SearchClause, ...]:
        return tuple(clause for group in self.groups for clause in group.clauses)

    @property
    def has_positive_in(self) -> bool:
        return any(
            clause.operator == "in" and not clause.negated
            for clause in self.clauses
        )

    @property
    def needs_labels(self) -> bool:
        return any(clause.operator == "label" for clause in self.clauses)


@dataclass(frozen=True)
class SearchAccount:
    id: int
    email: str
    display_name: str | None = None
    description: str | None = None
    short_label: str | None = None


@dataclass(frozen=True)
class SearchLabel:
    account_id: int
    gmail_label_id: str
    name: str


@dataclass(frozen=True)
class _Token:
    value: str
    quote_start: int | None = None


def _tokenize(query: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    length = len(query)

    while index < length:
        while index < length and query[index].isspace():
            index += 1
        if index >= length:
            break

        value: list[str] = []
        quote_start: int | None = None
        closed_quote = False

        while index < length and not query[index].isspace():
            char = query[index]
            if char in "()":
                raise SearchQueryError("Parentheses are not supported in email search yet.")
            if char == '"':
                if quote_start is not None:
                    raise SearchQueryError("Unexpected quote in email search.")
                if value and value[-1] != ":" and value != ["-"]:
                    raise SearchQueryError("Quotes must wrap a complete search term or operator value.")
                quote_start = len(value)
                index += 1
                while index < length:
                    char = query[index]
                    if char == "\\":
                        index += 1
                        if index >= length:
                            raise SearchQueryError("Search contains a dangling escape.")
                        escaped = query[index]
                        if escaped not in {'"', "\\"}:
                            raise SearchQueryError('Only \\" and \\\\ escapes are supported in quotes.')
                        value.append(escaped)
                        index += 1
                        continue
                    if char == '"':
                        index += 1
                        closed_quote = True
                        break
                    value.append(char)
                    index += 1
                if not closed_quote:
                    raise SearchQueryError("Search contains an unterminated quote.")
                if index < length and not query[index].isspace():
                    raise SearchQueryError("A quoted value must end the search term.")
                break
            if char == "\\" and index == length - 1:
                raise SearchQueryError("Search contains a dangling escape.")
            value.append(char)
            index += 1

        token_value = "".join(value)
        if token_value or quote_start is not None:
            tokens.append(_Token(token_value, quote_start))

    return tokens


def _parse_date(value: str, operator: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise SearchQueryError(
            f'{operator}: expects a valid date in YYYY-MM-DD format.'
        ) from exc
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise SearchQueryError(f'{operator}: expects a valid date in YYYY-MM-DD format.')
    return parsed


def parse_email_search(query: str) -> ParsedEmailSearch:
    """Parse ``query`` into OR groups whose clauses compose with AND."""
    if len(query) > MAX_QUERY_LENGTH:
        raise SearchQueryError(f"Search is limited to {MAX_QUERY_LENGTH} characters.")

    tokens = _tokenize(query.strip())
    if not tokens:
        return ParsedEmailSearch(groups=())

    groups: list[list[SearchClause]] = [[]]
    clause_count = 0

    for token in tokens:
        raw_value = token.value
        quote_start = token.quote_start
        if raw_value.startswith("--"):
            raise SearchQueryError('Use only one leading "-" to exclude a search term.')
        if raw_value == "-" and quote_start is None:
            raise SearchQueryError('Add a search term after "-".')
        negated = raw_value.startswith("-") and (len(raw_value) > 1 or quote_start == 1)
        if negated:
            raw_value = raw_value[1:]
            if quote_start is not None:
                quote_start -= 1

        if raw_value.casefold() == "or" and quote_start is None and not negated:
            if not groups[-1]:
                raise SearchQueryError("OR must have a search term on both sides.")
            groups.append([])
            continue

        clause_count += 1
        if clause_count > MAX_CLAUSES:
            raise SearchQueryError(f"Search is limited to {MAX_CLAUSES} clauses.")

        operator: str | None = None
        value = raw_value
        quoted = quote_start is not None

        # A fully quoted value such as "subject:launch" is text, not syntax.
        if quote_start != 0 and ":" in raw_value:
            candidate, operand = raw_value.split(":", 1)
            candidate = candidate.casefold()
            if candidate in RECOGNIZED_OPERATORS:
                operator = candidate
                value = operand
            elif quote_start is not None:
                raise SearchQueryError("Quotes may follow only a supported search operator.")

        if operator and not value:
            raise SearchQueryError(f"{operator}: requires a value.")
        if not value:
            raise SearchQueryError("A negated search term requires a value.")
        if len(value) > MAX_OPERAND_LENGTH:
            raise SearchQueryError(
                f"Each search value is limited to {MAX_OPERAND_LENGTH} characters."
            )

        if operator in {"after", "before"}:
            _parse_date(value, operator)
        elif operator == "is" and value.casefold() not in IS_VALUES:
            allowed = ", ".join(sorted(IS_VALUES))
            raise SearchQueryError(f"is: must be one of {allowed}.")
        elif operator == "has" and value.casefold() not in HAS_VALUES:
            raise SearchQueryError("has: currently supports attachment.")
        elif operator == "in" and value.casefold() not in IN_VALUES:
            allowed = ", ".join(sorted(IN_VALUES))
            raise SearchQueryError(f"in: must be one of {allowed}.")

        normalized_value = value.casefold() if operator in {"is", "has", "in"} else value
        groups[-1].append(SearchClause(
            operator=operator,
            value=normalized_value,
            negated=negated,
            quoted=quoted,
        ))

    if not groups[-1]:
        raise SearchQueryError("OR must have a search term on both sides.")

    return ParsedEmailSearch(
        groups=tuple(SearchGroup(tuple(group)) for group in groups)
    )


def resolve_timezone(name: str | None) -> ZoneInfo:
    requested = name or "UTC"
    try:
        return ZoneInfo(requested)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SearchQueryError(f'Unknown time zone "{requested}".') from exc


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _literal_contains(column: ColumnElement, value: str) -> ColumnElement[bool]:
    pattern = f"%{_escape_like(value)}%"
    return func.coalesce(column.ilike(pattern, escape="\\"), false())


def _regular_mail() -> ColumnElement[bool]:
    return and_(Email.is_trash.is_(False), Email.is_spam.is_(False))


def _mailbox_clause(value: str) -> ColumnElement[bool]:
    if value == "inbox":
        return and_(
            Email.labels.contains(["INBOX"]),
            Email.is_trash.is_(False),
            Email.is_spam.is_(False),
        )
    if value == "sent":
        return and_(Email.is_sent.is_(True), Email.is_trash.is_(False))
    if value == "drafts":
        return Email.is_draft.is_(True)
    if value == "archive":
        return and_(
            not_(func.coalesce(Email.labels.contains(["INBOX"]), false())),
            Email.is_sent.is_(False),
            Email.is_draft.is_(False),
            Email.is_trash.is_(False),
            Email.is_spam.is_(False),
        )
    if value == "starred":
        return Email.is_starred.is_(True)
    if value == "spam":
        return Email.is_spam.is_(True)
    if value == "trash":
        return Email.is_trash.is_(True)
    if value == "all":
        return _regular_mail()
    if value == "anywhere":
        return true()
    return false()


def _account_clause(value: str, accounts: Sequence[SearchAccount]) -> ColumnElement[bool]:
    folded = value.casefold()
    if value.isdigit():
        ids = [account.id for account in accounts if account.id == int(value)]
    else:
        def fields(account: SearchAccount) -> Iterable[str]:
            return (
                account.email,
                account.display_name or "",
                account.description or "",
                account.short_label or "",
            )

        exact = [
            account.id
            for account in accounts
            if any(field.casefold() == folded for field in fields(account) if field)
        ]
        ids = exact or [
            account.id
            for account in accounts
            if any(folded in field.casefold() for field in fields(account) if field)
        ]
    return Email.account_id.in_(ids) if ids else false()


def _label_clause(value: str, labels: Sequence[SearchLabel]) -> ColumnElement[bool]:
    folded = value.casefold()
    matches = [
        label
        for label in labels
        if label.gmail_label_id == value or label.name.casefold() == folded
    ]
    if not matches:
        return false()
    return or_(*(
        and_(
            Email.account_id == label.account_id,
            Email.labels.contains([label.gmail_label_id]),
        )
        for label in matches
    ))


def _text_clause(value: str, quoted: bool) -> ColumnElement[bool]:
    ts_query = (
        func.phraseto_tsquery("english", value)
        if quoted
        else func.plainto_tsquery("english", value)
    )
    return or_(
        func.coalesce(Email.search_vector.op("@@")(ts_query), false()),
        _literal_contains(Email.subject, value),
        _literal_contains(Email.from_address, value),
        _literal_contains(Email.from_name, value),
        _literal_contains(Email.snippet, value),
        _literal_contains(Email.body_text, value),
    )


def _recipient_contains(column, value: str) -> ColumnElement[bool]:
    """Match recipient values without searching JSON object field names.

    Current rows store ``{"name": ..., "address": ...}`` objects while some
    older rows contain plain strings. Expanding each array element lets us
    search only those values and keeps the user's literal in bind parameters.
    """
    recipients = func.jsonb_array_elements(
        func.coalesce(column, literal([], type_=JSONB))
    ).table_valued("value").alias()
    recipient = recipients.c.value
    pattern = f"%{_escape_like(value)}%"
    scalar_text = recipient.op("#>>")(array([], type_=Text))
    value_match = or_(
        and_(
            func.jsonb_typeof(recipient) == "object",
            or_(
                func.coalesce(recipient.op("->>")("name"), "").ilike(
                    pattern, escape="\\"
                ),
                func.coalesce(recipient.op("->>")("address"), "").ilike(
                    pattern, escape="\\"
                ),
            ),
        ),
        and_(
            func.jsonb_typeof(recipient) == "string",
            func.coalesce(scalar_text, "").ilike(pattern, escape="\\"),
        ),
    )
    return select(1).select_from(recipients).where(value_match).correlate(Email).exists()


def _compile_clause(
    clause: SearchClause,
    *,
    accounts: Sequence[SearchAccount],
    labels: Sequence[SearchLabel],
    zone: ZoneInfo,
) -> ColumnElement[bool]:
    operator = clause.operator
    value = clause.value

    if operator is None:
        expression = _text_clause(value, clause.quoted)
    elif operator == "from":
        expression = or_(
            _literal_contains(Email.from_address, value),
            _literal_contains(Email.from_name, value),
        )
    elif operator in {"to", "cc", "bcc"}:
        column = getattr(Email, f"{operator}_addresses")
        expression = _recipient_contains(column, value)
    elif operator == "subject":
        expression = _literal_contains(Email.subject, value)
    elif operator == "body":
        expression = or_(
            _literal_contains(Email.snippet, value),
            _literal_contains(Email.body_text, value),
        )
    elif operator in {"after", "before"}:
        local_midnight = datetime.combine(_parse_date(value, operator), time.min, tzinfo=zone)
        boundary = local_midnight.astimezone(timezone.utc)
        expression = Email.date >= boundary if operator == "after" else Email.date < boundary
    elif operator == "is":
        expression = {
            "read": Email.is_read.is_(True),
            "unread": Email.is_read.is_(False),
            "starred": Email.is_starred.is_(True),
            "unstarred": Email.is_starred.is_(False),
            "draft": Email.is_draft.is_(True),
            "sent": Email.is_sent.is_(True),
        }[value]
    elif operator == "has":
        expression = Email.has_attachments.is_(True)
    elif operator == "in":
        expression = _mailbox_clause(value)
    elif operator == "account":
        expression = _account_clause(value, accounts)
    elif operator == "label":
        expression = _label_clause(value, labels)
    else:  # Defensive: parser never emits unknown operators.
        expression = _text_clause(value, clause.quoted)

    safe_expression = func.coalesce(expression, false())
    return not_(safe_expression) if clause.negated else safe_expression


def build_email_search_clause(
    parsed: ParsedEmailSearch,
    *,
    accounts: Sequence[SearchAccount],
    labels: Sequence[SearchLabel] = (),
    timezone_name: str | None = None,
) -> ColumnElement[bool]:
    """Compile a parsed query into a bound, NULL-safe SQLAlchemy predicate."""
    if not parsed.groups:
        return true()
    zone = resolve_timezone(timezone_name)
    group_expressions: list[ColumnElement[bool]] = []

    for group in parsed.groups:
        clauses = [
            _compile_clause(clause, accounts=accounts, labels=labels, zone=zone)
            for clause in group.clauses
        ]
        # If any OR branch explicitly searches a mailbox, branches without a
        # positive in: clause stay scoped to regular mail rather than silently
        # expanding into Spam and Trash.
        if parsed.has_positive_in and not any(
            clause.operator == "in" and not clause.negated for clause in group.clauses
        ):
            clauses.insert(0, _regular_mail())
        group_expressions.append(and_(*clauses))

    return or_(*group_expressions)
