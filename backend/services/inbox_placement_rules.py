"""Owner-scoped local operations for user-trainable Inbox placement rules."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.inbox_placement_rule import InboxPlacementRule
from backend.schemas.inbox_placement_rule import (
    MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT,
    InboxPlacementRuleReplace,
    InboxPlacementRuleUpsert,
)
from backend.services.mailbox_identity import (
    MailboxIdentityError,
    mailbox_domain,
    normalize_stored_mailbox,
)


SCOPE_ORDER = {"conversation": 0, "sender": 1, "domain": 2}
MAX_CONVERSATION_LABEL_CHARS = 160
_SQL_STORED_MAILBOX_PATTERN = (
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.*$"
)


class InboxPlacementRuleError(Exception):
    """Base class for stable rule API failures."""


class InboxPlacementRuleNotFound(InboxPlacementRuleError):
    pass


class InboxPlacementRuleConflict(InboxPlacementRuleError):
    pass


class InboxPlacementRuleCandidateUnavailable(InboxPlacementRuleError):
    pass


@dataclass(frozen=True)
class InboxPlacementRuleView:
    rule: InboxPlacementRule
    account_email: str
    display_value: str


@dataclass(frozen=True)
class InboxPlacementCandidate:
    account_id: int
    account_email: str
    anchor_email_id: int
    conversation_label: str
    sender_address: str
    sender_domain: str
    rules: list[InboxPlacementRuleView]


def conversation_rule_value(email) -> object:
    """Stable provider identity used only inside the private database."""
    normalized_thread = func.nullif(func.btrim(email.gmail_thread_id), "")
    return case(
        (
            normalized_thread.is_(None),
            func.concat("message:", email.gmail_message_id),
        ),
        else_=func.concat("thread:", normalized_thread),
    )


def sender_rule_value(email) -> object:
    """Return the SQL-equivalent canonical sender, or NULL when unsafe.

    Gmail synchronization stores the parsed mailbox rather than the original
    display header. Keep this expression deliberately no more permissive than
    ``normalize_stored_mailbox``: malformed or non-ASCII stored values must
    never accidentally match an existing user rule.
    """
    stored = func.btrim(func.coalesce(email.from_address, ""))
    local_part = func.split_part(stored, "@", 1)
    domain = func.rtrim(func.split_part(stored, "@", 2), ".")
    normalized = func.concat(
        func.lower(local_part),
        "@",
        func.lower(domain),
    )
    return case(
        (
            and_(
                stored.op("~")(_SQL_STORED_MAILBOX_PATTERN),
                func.char_length(domain) <= 253,
                func.char_length(normalized) <= 320,
            ),
            normalized,
        ),
        else_=None,
    )


def domain_rule_value(email) -> object:
    normalized_sender = sender_rule_value(email)
    return case(
        (
            normalized_sender.is_not(None),
            func.split_part(normalized_sender, "@", 2),
        ),
        else_=None,
    )


def _python_conversation_rule_value(email: Email) -> str:
    thread_id = str(email.gmail_thread_id or "").strip()
    if thread_id:
        return f"thread:{thread_id}"
    message_id = str(email.gmail_message_id or "").strip()
    if not message_id:
        raise InboxPlacementRuleCandidateUnavailable(
            "This conversation does not have a stable synchronized identity"
        )
    return f"message:{message_id}"


def _conversation_label(subject: str | None) -> str:
    label = " ".join(str(subject or "").split()) or "(No subject)"
    if len(label) <= MAX_CONVERSATION_LABEL_CHARS:
        return label
    return f"{label[: MAX_CONVERSATION_LABEL_CHARS - 1].rstrip()}…"


def _owned_account_statement(
    *, user_id: int, account_id: int, active_only: bool = False
):
    statement = select(GoogleAccount).where(
        GoogleAccount.id == account_id,
        GoogleAccount.user_id == user_id,
    )
    if active_only:
        statement = statement.where(GoogleAccount.is_active.is_(True))
    return statement


def _owned_rule_statement(*, user_id: int, rule_id: UUID):
    return (
        select(InboxPlacementRule, GoogleAccount.email)
        .join(GoogleAccount, GoogleAccount.id == InboxPlacementRule.account_id)
        .where(
            InboxPlacementRule.id == rule_id,
            GoogleAccount.user_id == user_id,
        )
    )


def _current_inbox_email_predicate(email=Email):
    return and_(
        email.labels.contains(["INBOX"]),
        email.is_trash.is_(False),
        email.is_spam.is_(False),
        email.is_draft.is_(False),
        email.is_sent.is_(False),
    )


async def _require_owned_account(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    active_only: bool,
    lock: bool = False,
) -> GoogleAccount:
    statement = _owned_account_statement(
        user_id=user_id,
        account_id=account_id,
        active_only=active_only,
    )
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    account = result.scalar_one_or_none()
    if account is None:
        raise InboxPlacementRuleNotFound("Inbox placement rule not found")
    return account


async def _require_current_inbox_anchor(
    db: AsyncSession,
    *,
    account_id: int,
    anchor_email_id: int,
) -> Email:
    result = await db.execute(
        select(Email).where(
            Email.id == anchor_email_id,
            Email.account_id == account_id,
            _current_inbox_email_predicate(),
        )
    )
    email = result.scalar_one_or_none()
    if email is None:
        raise InboxPlacementRuleNotFound("Inbox placement rule not found")

    thread_id = str(email.gmail_thread_id or "").strip()
    if thread_id:
        latest_id = await db.scalar(
            select(Email.id)
            .where(
                Email.account_id == account_id,
                Email.gmail_thread_id == email.gmail_thread_id,
                _current_inbox_email_predicate(),
            )
            .order_by(Email.date.desc().nulls_last(), Email.id.desc())
            .limit(1)
        )
        if latest_id != email.id:
            raise InboxPlacementRuleNotFound("Inbox placement rule not found")
    return email


def _selector_values(email: Email) -> dict[str, str]:
    values = {"conversation": _python_conversation_rule_value(email)}
    try:
        sender = normalize_stored_mailbox(email.from_address or "")
    except MailboxIdentityError:
        # A malformed synchronized sender must not disable safe conversation
        # training. Sender/domain scopes simply remain unavailable, and POST
        # still fails closed if a client explicitly requests either one.
        return values
    values["sender"] = sender
    values["domain"] = mailbox_domain(sender)
    return values


async def _matching_rules(
    db: AsyncSession,
    *,
    account_id: int,
    selectors: dict[str, str],
    lock: bool = False,
) -> list[InboxPlacementRule]:
    statement = select(InboxPlacementRule).where(
        InboxPlacementRule.account_id == account_id,
        or_(
            *(
                and_(
                    InboxPlacementRule.scope == scope,
                    InboxPlacementRule.match_value == value,
                )
                for scope, value in selectors.items()
            )
        ),
    )
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return sorted(
        result.scalars().all(),
        key=lambda rule: (SCOPE_ORDER[rule.scope], rule.row_id),
    )


async def _conversation_display_values(
    db: AsyncSession,
    rules: list[InboxPlacementRule],
) -> dict[int, str]:
    thread_keys: list[tuple[int, str]] = []
    message_keys: list[tuple[int, str]] = []
    for rule in rules:
        if rule.scope != "conversation":
            continue
        if rule.match_value.startswith("thread:"):
            thread_keys.append((rule.account_id, rule.match_value.removeprefix("thread:")))
        elif rule.match_value.startswith("message:"):
            message_keys.append((rule.account_id, rule.match_value.removeprefix("message:")))

    clauses = []
    if thread_keys:
        clauses.append(tuple_(Email.account_id, Email.gmail_thread_id).in_(thread_keys))
    if message_keys:
        clauses.append(tuple_(Email.account_id, Email.gmail_message_id).in_(message_keys))
    if not clauses:
        return {}

    result = await db.execute(
        select(
            Email.account_id,
            Email.gmail_thread_id,
            Email.gmail_message_id,
            Email.subject,
        )
        .where(or_(*clauses))
        .order_by(Email.date.desc().nulls_last(), Email.id.desc())
    )
    labels: dict[tuple[int, str], str] = {}
    for row in result.all():
        thread_id = str(row.gmail_thread_id or "").strip()
        if thread_id:
            labels.setdefault(
                (row.account_id, f"thread:{thread_id}"),
                _conversation_label(row.subject),
            )
        labels.setdefault(
            (row.account_id, f"message:{row.gmail_message_id}"),
            _conversation_label(row.subject),
        )
    return {
        rule.row_id: labels.get(
            (rule.account_id, rule.match_value),
            "Conversation unavailable",
        )
        for rule in rules
        if rule.scope == "conversation"
    }


async def _views(
    db: AsyncSession,
    rows: list[tuple[InboxPlacementRule, str]],
) -> list[InboxPlacementRuleView]:
    rules = [rule for rule, _account_email in rows]
    conversation_labels = await _conversation_display_values(db, rules)
    return [
        InboxPlacementRuleView(
            rule=rule,
            account_email=account_email,
            display_value=(
                conversation_labels.get(rule.row_id, "Conversation unavailable")
                if rule.scope == "conversation"
                else rule.match_value
            ),
        )
        for rule, account_email in rows
    ]


async def list_inbox_placement_rules(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int | None,
) -> list[InboxPlacementRuleView]:
    if account_id is not None:
        await _require_owned_account(
            db,
            user_id=user_id,
            account_id=account_id,
            active_only=False,
        )
    statement = (
        select(InboxPlacementRule, GoogleAccount.email)
        .join(GoogleAccount, GoogleAccount.id == InboxPlacementRule.account_id)
        .where(GoogleAccount.user_id == user_id)
        .order_by(
            GoogleAccount.email,
            InboxPlacementRule.scope,
            InboxPlacementRule.match_value,
            InboxPlacementRule.row_id,
        )
    )
    if account_id is not None:
        statement = statement.where(InboxPlacementRule.account_id == account_id)
    result = await db.execute(statement)
    return await _views(db, list(result.all()))


async def get_inbox_placement_candidate(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    anchor_email_id: int,
) -> InboxPlacementCandidate:
    account = await _require_owned_account(
        db,
        user_id=user_id,
        account_id=account_id,
        active_only=True,
    )
    email = await _require_current_inbox_anchor(
        db,
        account_id=account_id,
        anchor_email_id=anchor_email_id,
    )
    selectors = _selector_values(email)
    rules = await _matching_rules(
        db,
        account_id=account_id,
        selectors=selectors,
    )
    sender = selectors.get("sender", "")
    rows = [(rule, account.email) for rule in rules]
    return InboxPlacementCandidate(
        account_id=account.id,
        account_email=account.email,
        anchor_email_id=email.id,
        conversation_label=_conversation_label(email.subject),
        sender_address=sender,
        sender_domain=selectors.get("domain", ""),
        rules=await _views(db, rows),
    )


def _same_rule_state(rule: InboxPlacementRule, *, placement: str, enabled: bool) -> bool:
    return rule.placement == placement and rule.enabled is enabled


async def upsert_inbox_placement_rule(
    db: AsyncSession,
    *,
    user_id: int,
    request: InboxPlacementRuleUpsert,
) -> tuple[InboxPlacementRuleView, bool]:
    account = await _require_owned_account(
        db,
        user_id=user_id,
        account_id=request.account_id,
        active_only=True,
        lock=True,
    )
    email = await _require_current_inbox_anchor(
        db,
        account_id=account.id,
        anchor_email_id=request.anchor_email_id,
    )
    selectors = _selector_values(email)
    match_value = selectors.get(request.scope)
    if match_value is None:
        raise InboxPlacementRuleCandidateUnavailable(
            "This message does not have a valid sender for that rule scope"
        )

    create_result = await db.execute(
        select(InboxPlacementRule).where(
            InboxPlacementRule.account_id == account.id,
            InboxPlacementRule.create_id == request.create_id,
        )
    )
    create_replay = create_result.scalar_one_or_none()
    matching_result = await db.execute(
        select(InboxPlacementRule)
        .where(
            InboxPlacementRule.account_id == account.id,
            InboxPlacementRule.scope == request.scope,
            InboxPlacementRule.match_value == match_value,
        )
        .with_for_update()
    )
    rule = matching_result.scalar_one_or_none()

    if request.expected_revision == 0:
        if create_replay is not None:
            if (
                create_replay is rule
                and create_replay.revision == 1
                and _same_rule_state(
                    create_replay,
                    placement=request.placement,
                    enabled=request.enabled,
                )
            ):
                return (
                    InboxPlacementRuleView(
                        rule=create_replay,
                        account_email=account.email,
                        display_value=(
                            _conversation_label(email.subject)
                            if request.scope == "conversation"
                            else match_value
                        ),
                    ),
                    False,
                )
            raise InboxPlacementRuleConflict(
                "That Inbox placement rule request ID is already used"
            )
        if rule is not None:
            raise InboxPlacementRuleConflict(
                "A rule already exists for that exact account and target"
            )
        count = int(
            await db.scalar(
                select(func.count(InboxPlacementRule.row_id)).where(
                    InboxPlacementRule.account_id == account.id
                )
            )
            or 0
        )
        if count >= MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT:
            raise InboxPlacementRuleConflict(
                f"An account can keep at most {MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT} Inbox placement rules"
            )
        rule = InboxPlacementRule(
            create_id=request.create_id,
            account_id=account.id,
            scope=request.scope,
            match_value=match_value,
            placement=request.placement,
            enabled=request.enabled,
            revision=1,
        )
        db.add(rule)
        created = True
    else:
        if rule is None:
            raise InboxPlacementRuleConflict(
                "That rule changed elsewhere; refresh the Inbox rule candidate"
            )
        if rule.revision == request.expected_revision + 1 and _same_rule_state(
            rule,
            placement=request.placement,
            enabled=request.enabled,
        ):
            return (
                InboxPlacementRuleView(
                    rule=rule,
                    account_email=account.email,
                    display_value=(
                        _conversation_label(email.subject)
                        if request.scope == "conversation"
                        else match_value
                    ),
                ),
                False,
            )
        if rule.revision != request.expected_revision:
            raise InboxPlacementRuleConflict(
                "That rule changed elsewhere; refresh the Inbox rule candidate"
            )
        if _same_rule_state(
            rule,
            placement=request.placement,
            enabled=request.enabled,
        ):
            return (
                InboxPlacementRuleView(
                    rule=rule,
                    account_email=account.email,
                    display_value=(
                        _conversation_label(email.subject)
                        if request.scope == "conversation"
                        else match_value
                    ),
                ),
                False,
            )
        rule.placement = request.placement
        rule.enabled = request.enabled
        rule.revision += 1
        created = False

    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise InboxPlacementRuleConflict(
            "That Inbox placement rule changed elsewhere; refresh it"
        ) from error
    await db.refresh(rule)
    return (
        InboxPlacementRuleView(
            rule=rule,
            account_email=account.email,
            display_value=(
                _conversation_label(email.subject)
                if request.scope == "conversation"
                else match_value
            ),
        ),
        created,
    )


async def replace_inbox_placement_rule(
    db: AsyncSession,
    *,
    user_id: int,
    rule_id: UUID,
    request: InboxPlacementRuleReplace,
) -> InboxPlacementRuleView:
    result = await db.execute(
        _owned_rule_statement(user_id=user_id, rule_id=rule_id).with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise InboxPlacementRuleNotFound("Inbox placement rule not found")
    rule, account_email = row
    same = _same_rule_state(
        rule,
        placement=request.placement,
        enabled=request.enabled,
    )
    if rule.revision == request.revision + 1 and same:
        return (await _views(db, [(rule, account_email)]))[0]
    if rule.revision != request.revision:
        raise InboxPlacementRuleConflict(
            "That Inbox placement rule changed elsewhere; refresh it"
        )
    if not same:
        rule.placement = request.placement
        rule.enabled = request.enabled
        rule.revision += 1
        await db.commit()
        await db.refresh(rule)
    return (await _views(db, [(rule, account_email)]))[0]


async def delete_inbox_placement_rule(
    db: AsyncSession,
    *,
    user_id: int,
    rule_id: UUID,
    revision: int,
) -> None:
    result = await db.execute(
        _owned_rule_statement(user_id=user_id, rule_id=rule_id).with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise InboxPlacementRuleNotFound("Inbox placement rule not found")
    rule, _account_email = row
    if rule.revision != revision:
        raise InboxPlacementRuleConflict(
            "That Inbox placement rule changed elsewhere; refresh it"
        )
    await db.delete(rule)
    await db.commit()
