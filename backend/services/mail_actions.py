"""Durable, ordered Gmail label actions.

The database is the source of truth for accepted work.  Redis is used only to
wake a drainer sooner; the cron sweeper can always recover work from this
outbox after a process or queue failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import UUID, uuid4

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import and_, case, exists, func, or_, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.config import get_settings
from backend.database import async_session
from backend.models.account import GoogleAccount
from backend.models.email import Email, EmailLabel
from backend.models.mail_action import (
    ACTIVE_MAIL_ACTION_STATES,
    MAIL_ACTION_TYPES,
    MailAction,
)
from backend.models.snooze import EmailSnooze
from backend.services.account_lock import account_advisory_lock
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService
from backend.utils.security import encrypt_value


logger = logging.getLogger(__name__)

MAIL_ACTION_QUEUE_NAME = "arq:cron"
MAIL_ACTION_UNDO_SECONDS = 10
MAIL_ACTION_LEASE_SECONDS = 120
MAIL_ACTION_MAX_ATTEMPTS = 8
MAIL_ACTION_MAX_BATCH = 200
MAIL_ACTION_DRAIN_BATCH = 50
MAIL_ACTION_DRAIN_MAX_ACTIONS = 8
MAIL_ACTION_GMAIL_TRANSPORT_TIMEOUT_SECONDS = 30.0
MAIL_ACTION_REDIS_IO_TIMEOUT_SECONDS = 1.0

ACTION_LABEL_DELTAS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "mark_read": ((), ("UNREAD",)),
    "mark_unread": (("UNREAD",), ()),
    "star": (("STARRED",), ()),
    "unstar": ((), ("STARRED",)),
    "archive": ((), ("INBOX",)),
    "unarchive": (("INBOX",), ()),
    "trash": (("TRASH",), ()),
    "untrash": ((), ("TRASH",)),
    "spam": (("SPAM",), ("INBOX",)),
    "unspam": (("INBOX",), ("SPAM",)),
}
LABEL_ACTION_TYPES = ("add_label", "remove_label", "move_to_label")


class MailActionError(RuntimeError):
    """Base class for errors that map to an action API response."""


class MailActionNotFound(MailActionError):
    pass


class MailActionConflict(MailActionError):
    pass


class MailActionValidationError(MailActionError):
    pass


@dataclass(frozen=True)
class ErrorDisposition:
    retryable: bool
    code: str
    message: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _consume_background_result(task: asyncio.Future) -> None:
    """Retrieve a detached task exception so timeout cleanup stays quiet."""
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


async def _await_bounded(awaitable, *, timeout: float):
    """Return on deadline even if third-party cancellation cleanup misbehaves."""
    task = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
    except BaseException:
        task.cancel()
        task.add_done_callback(_consume_background_result)
        raise
    if task in done:
        return task.result()
    task.cancel()
    task.add_done_callback(_consume_background_result)
    raise TimeoutError("Best-effort mail action I/O exceeded its deadline")


def _normalized_labels(labels: Iterable[object] | None) -> list[str]:
    return sorted({str(label) for label in (labels or []) if str(label)})


def canonical_mail_state(
    labels: Iterable[object] | None,
    *,
    is_read: bool | None = None,
    is_starred: bool | None = None,
    is_trash: bool | None = None,
    is_spam: bool | None = None,
) -> dict:
    """Return one internally consistent label/flag snapshot.

    When explicit flags are supplied they repair older rows whose booleans and
    stored label list disagree.  Gmail responses omit those flags and derive
    them directly from the canonical returned labels.
    """
    normalized = set(_normalized_labels(labels))
    flag_labels = {
        "UNREAD": None if is_read is None else not is_read,
        "STARRED": is_starred,
        "TRASH": is_trash,
        "SPAM": is_spam,
    }
    for label, present in flag_labels.items():
        if present is True:
            normalized.add(label)
        elif present is False:
            normalized.discard(label)

    ordered = sorted(normalized)
    return {
        "labels": ordered,
        "is_read": "UNREAD" not in normalized,
        "is_starred": "STARRED" in normalized,
        "is_trash": "TRASH" in normalized,
        "is_spam": "SPAM" in normalized,
    }


def snapshot_email_state(email: Email) -> dict:
    return canonical_mail_state(
        email.labels,
        is_read=email.is_read,
        is_starred=email.is_starred,
        is_trash=email.is_trash,
        is_spam=email.is_spam,
    )


def state_after_action(before_state: dict, action: str) -> tuple[dict, list[str], list[str]]:
    if action not in ACTION_LABEL_DELTAS:
        raise MailActionValidationError(f"Unsupported mail action: {action}")
    add_labels, remove_labels = ACTION_LABEL_DELTAS[action]
    after_state = state_after_label_delta(before_state, add_labels, remove_labels)
    return after_state, list(add_labels), list(remove_labels)


def state_after_label_delta(
    before_state: dict,
    add_labels: Iterable[object] | None,
    remove_labels: Iterable[object] | None,
) -> dict:
    labels = set(_normalized_labels(before_state.get("labels")))
    labels.difference_update(_normalized_labels(remove_labels))
    labels.update(_normalized_labels(add_labels))
    return canonical_mail_state(labels)


def apply_mail_state(email: Email, state: dict) -> None:
    normalized = canonical_mail_state(state.get("labels"))
    email.labels = normalized["labels"]
    email.is_read = normalized["is_read"]
    email.is_starred = normalized["is_starred"]
    email.is_trash = normalized["is_trash"]
    email.is_spam = normalized["is_spam"]


def action_payload_hash(
    email_ids: Iterable[int],
    action: str,
    *,
    label_id: int | None = None,
    scope: str = "messages",
) -> str:
    payload_data: dict[str, object] = {
        "action": action,
        "email_ids": sorted(email_ids),
    }
    if action in LABEL_ACTION_TYPES or label_id is not None:
        payload_data["label_id"] = label_id
    if scope != "messages":
        payload_data["scope"] = scope
    payload = json.dumps(
        payload_data,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def label_action_delta(action: str, gmail_label_id: str) -> tuple[list[str], list[str]]:
    """Return the exact provider delta for one validated user-label action."""
    if action == "add_label":
        return [gmail_label_id], []
    if action == "remove_label":
        return [], [gmail_label_id]
    if action == "move_to_label":
        return [gmail_label_id], ["INBOX"]
    raise MailActionValidationError(f"Unsupported label action: {action}")


async def _label_action_context(
    db: AsyncSession,
    *,
    user_id: int,
    selected_email_ids: list[int],
    label_id: int,
) -> tuple[list[Email], EmailLabel, list[Email]]:
    """Resolve and lock one owned label plus every local conversation member.

    Anchor messages are read before the expanded target query so all Email
    rows are subsequently locked once, in primary-key order. This avoids the
    lock inversion that would result from locking an arbitrary anchor first
    and then discovering an older sibling in the same conversation.
    """
    label_result = await db.execute(
        select(EmailLabel)
        .join(GoogleAccount, GoogleAccount.id == EmailLabel.account_id)
        .where(
            EmailLabel.id == label_id,
            GoogleAccount.user_id == user_id,
        )
        .with_for_update(of=EmailLabel)
    )
    label = label_result.scalar_one_or_none()
    if label is None:
        raise MailActionNotFound("Label not found")
    if (label.label_type or "").casefold() != "user":
        raise MailActionValidationError("Only user labels can be changed")
    gmail_label_id = str(label.gmail_label_id or "").strip()
    if not gmail_label_id:
        raise MailActionValidationError("Label is stale and must be synchronized")

    anchor_result = await db.execute(
        select(Email)
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .where(
            Email.id.in_(selected_email_ids),
            GoogleAccount.user_id == user_id,
        )
        .order_by(Email.id)
    )
    anchors = list(anchor_result.scalars().all())
    if (
        len(anchors) != len(selected_email_ids)
        or {email.id for email in anchors} != set(selected_email_ids)
    ):
        raise MailActionNotFound("One or more emails were not found")
    account_ids = {email.account_id for email in anchors}
    if len(account_ids) != 1 or label.account_id not in account_ids:
        raise MailActionValidationError(
            "Label actions require messages and a user label from one account"
        )

    thread_ids = sorted({
        email.gmail_thread_id
        for email in anchors
        if str(email.gmail_thread_id or "").strip()
    })
    fallback_email_ids = sorted({
        email.id
        for email in anchors
        if not str(email.gmail_thread_id or "").strip()
    })
    identity_clause = or_(
        Email.gmail_thread_id.in_(thread_ids) if thread_ids else False,
        Email.id.in_(fallback_email_ids) if fallback_email_ids else False,
    )
    expanded_result = await db.execute(
        select(Email)
        .where(
            Email.account_id == label.account_id,
            identity_clause,
        )
        .order_by(Email.id)
        .limit(MAIL_ACTION_MAX_BATCH + 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    expanded = list(expanded_result.scalars().all())
    if len(expanded) > MAIL_ACTION_MAX_BATCH:
        raise MailActionValidationError(
            f"Label actions can affect at most {MAIL_ACTION_MAX_BATCH} conversation messages"
        )
    expanded_by_id = {email.id: email for email in expanded}
    if not set(selected_email_ids).issubset(expanded_by_id):
        raise MailActionNotFound("One or more emails were not found")
    locked_anchors = [expanded_by_id[email_id] for email_id in selected_email_ids]
    return expanded, label, locked_anchors


async def _conversation_action_context(
    db: AsyncSession,
    *,
    user_id: int,
    selected_email_ids: list[int],
) -> tuple[list[Email], list[Email]]:
    """Resolve anchors and lock every exact account/thread member once.

    Gmail thread identifiers are account-local.  Anchors are deliberately read
    before any Email row is locked, then the complete expanded set is locked in
    primary-key order.  This gives bulk operations across accounts one stable
    lock order and prevents client-visible pagination from defining scope.
    """
    anchor_result = await db.execute(
        select(Email)
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .where(
            Email.id.in_(selected_email_ids),
            GoogleAccount.user_id == user_id,
        )
        .order_by(Email.id)
    )
    anchors = list(anchor_result.scalars().all())
    if (
        len(anchors) != len(selected_email_ids)
        or {email.id for email in anchors} != set(selected_email_ids)
    ):
        raise MailActionNotFound("One or more emails were not found")

    identities = sorted({
        (email.account_id, email.gmail_thread_id)
        for email in anchors
        if str(email.gmail_thread_id or "").strip()
    })
    fallback_email_ids = sorted({
        email.id
        for email in anchors
        if not str(email.gmail_thread_id or "").strip()
    })
    identity_clause = or_(
        tuple_(Email.account_id, Email.gmail_thread_id).in_(identities)
        if identities else False,
        Email.id.in_(fallback_email_ids) if fallback_email_ids else False,
    )
    expanded_result = await db.execute(
        select(Email)
        .where(identity_clause)
        .order_by(Email.id)
        .limit(MAIL_ACTION_MAX_BATCH + 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    expanded = list(expanded_result.scalars().all())
    if len(expanded) > MAIL_ACTION_MAX_BATCH:
        raise MailActionValidationError(
            f"Conversation actions can affect at most {MAIL_ACTION_MAX_BATCH} messages"
        )
    expanded_by_id = {email.id: email for email in expanded}
    if not set(selected_email_ids).issubset(expanded_by_id):
        raise MailActionNotFound("One or more emails were not found")
    locked_anchors = [expanded_by_id[email_id] for email_id in selected_email_ids]
    return expanded, locked_anchors


def aggregate_action_state(actions: list[MailAction]) -> str:
    states = {action.state for action in actions}
    return next(iter(states)) if len(states) == 1 else "partial"


def _idempotency_advisory_key(user_id: int, idempotency_key: UUID) -> int:
    digest = hashlib.sha256(f"{user_id}:{idempotency_key}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def _lock_idempotency_key(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: UUID,
) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _idempotency_advisory_key(user_id, idempotency_key)},
    )


async def _actions_for_idempotency(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: UUID,
    for_update: bool = False,
) -> list[MailAction]:
    statement = (
        select(MailAction)
        .where(
            MailAction.user_id == user_id,
            MailAction.idempotency_key == idempotency_key,
        )
        .order_by(MailAction.id)
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return list(result.scalars().all())


async def stage_mail_actions(
    db: AsyncSession,
    *,
    user_id: int,
    email_ids: list[int],
    action: str,
    idempotency_key: UUID,
    label_id: int | None = None,
    scope: str = "messages",
    now: datetime | None = None,
) -> tuple[list[MailAction], bool]:
    """Atomically stage a fully-owned operation and its optimistic state."""
    if action not in MAIL_ACTION_TYPES:
        raise MailActionValidationError(f"Unsupported mail action: {action}")
    if not email_ids or len(email_ids) > MAIL_ACTION_MAX_BATCH:
        raise MailActionValidationError("Mail actions require 1 to 200 emails")
    if len(set(email_ids)) != len(email_ids):
        raise MailActionValidationError("Mail action email IDs must be unique")
    if scope not in {"messages", "conversations"}:
        raise MailActionValidationError("Mail action scope is invalid")
    is_label_action = action in LABEL_ACTION_TYPES
    if is_label_action and label_id is None:
        raise MailActionValidationError("label_id is required for label actions")
    if not is_label_action and label_id is not None:
        raise MailActionValidationError("label_id is only supported for label actions")

    ordered_ids = sorted(email_ids)
    payload_hash = action_payload_hash(
        ordered_ids,
        action,
        label_id=label_id if is_label_action else None,
        scope=scope,
    )
    await _lock_idempotency_key(
        db,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )

    existing_actions = await _actions_for_idempotency(
        db,
        user_id=user_id,
        idempotency_key=idempotency_key,
        for_update=True,
    )
    if existing_actions:
        if any(item.payload_hash != payload_hash for item in existing_actions):
            raise MailActionConflict("Idempotency key was already used for another payload")
        return existing_actions, False

    label_add: list[str] | None = None
    label_remove: list[str] | None = None
    if is_label_action:
        emails, resolved_label, anchors = await _label_action_context(
            db,
            user_id=user_id,
            selected_email_ids=ordered_ids,
            label_id=label_id,
        )
        if action == "move_to_label" and any(
            "INBOX" not in snapshot_email_state(email)["labels"]
            for email in anchors
        ):
            raise MailActionValidationError(
                "Move to a label is only available for Inbox conversations"
            )
        label_add, label_remove = label_action_delta(
            action, str(resolved_label.gmail_label_id)
        )
    elif scope == "conversations":
        emails, _anchors = await _conversation_action_context(
            db,
            user_id=user_id,
            selected_email_ids=ordered_ids,
        )
    else:
        email_result = await db.execute(
            select(Email)
            .join(GoogleAccount, GoogleAccount.id == Email.account_id)
            .where(
                Email.id.in_(ordered_ids),
                GoogleAccount.user_id == user_id,
            )
            .order_by(Email.id)
            .with_for_update()
        )
        emails = list(email_result.scalars().all())
        if len(emails) != len(ordered_ids) or {email.id for email in emails} != set(ordered_ids):
            raise MailActionNotFound("One or more emails were not found")
    if action == "unarchive" and any(email.is_trash or email.is_spam for email in emails):
        raise MailActionValidationError(
            "Trash and spam must be restored with their dedicated actions"
        )

    accepted_at = now or utcnow()
    undo_until = accepted_at + timedelta(seconds=MAIL_ACTION_UNDO_SECONDS)
    request_id = uuid4()
    actions: list[MailAction] = []

    for email in emails:
        before_state = snapshot_email_state(email)
        if is_label_action:
            add_labels = list(label_add or [])
            remove_labels = list(label_remove or [])
            after_state = state_after_label_delta(
                before_state, add_labels, remove_labels
            )
        else:
            after_state, add_labels, remove_labels = state_after_action(before_state, action)
        email.mail_action_version = int(email.mail_action_version or 0) + 1
        base_state, chain_start_sequence = await _mail_action_chain_base(
            db,
            email=email,
            next_sequence=email.mail_action_version,
            before_state=before_state,
        )
        apply_mail_state(email, after_state)

        item = MailAction(
            request_id=request_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            user_id=user_id,
            account_id=email.account_id,
            email_id=email.id,
            gmail_message_id=email.gmail_message_id,
            sequence=email.mail_action_version,
            chain_start_sequence=chain_start_sequence,
            action=action,
            base_state=base_state,
            before_state=before_state,
            after_state=after_state,
            add_labels=add_labels,
            remove_labels=remove_labels,
            state="staged",
            execute_after=undo_until,
            undo_until=undo_until,
            next_attempt_at=undo_until,
            attempt_count=0,
            max_attempts=MAIL_ACTION_MAX_ATTEMPTS,
            created_at=accepted_at,
            updated_at=accepted_at,
        )
        db.add(item)
        actions.append(item)

    await db.flush()
    await db.commit()
    await _publish_action_event(user_id, request_id)
    return actions, True


async def _mail_action_chain_base(
    db: AsyncSession,
    *,
    email: Email,
    next_sequence: int,
    before_state: dict,
) -> tuple[dict, int]:
    result = await db.execute(
        select(MailAction)
        .where(
            MailAction.email_id == email.id,
            MailAction.state.in_(ACTIVE_MAIL_ACTION_STATES),
        )
        .order_by(MailAction.sequence.desc())
        .limit(1)
    )
    active = result.scalar_one_or_none()
    if active is None:
        return canonical_mail_state(before_state.get("labels")), next_sequence
    return (
        canonical_mail_state(active.base_state.get("labels")),
        active.chain_start_sequence,
    )


async def get_mail_action_operation(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: UUID,
    for_update: bool = False,
) -> list[MailAction]:
    statement = (
        select(MailAction)
        .where(MailAction.user_id == user_id, MailAction.request_id == request_id)
        .order_by(MailAction.id)
    )
    if for_update:
        # Undo and retry deliberately read once before locking Email rows,
        # then re-read the operation under a row lock. Force the locked read
        # to overwrite identity-map state so a concurrent worker claim cannot
        # be mistaken for the earlier staged snapshot.
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    result = await db.execute(statement)
    actions = list(result.scalars().all())
    if not actions:
        raise MailActionNotFound("Mail action not found")
    return actions


async def get_mail_action_operation_by_idempotency(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: UUID,
) -> list[MailAction]:
    """Return the exact owned operation for lost-response reconciliation."""
    actions = await _actions_for_idempotency(
        db,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    if not actions:
        raise MailActionNotFound("Mail action not found")
    return actions


async def recent_mail_action_operations(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int,
) -> list[list[MailAction]]:
    unresolved_failure = func.max(
        case((MailAction.state == "failed", 1), else_=0)
    ).label("unresolved_failure")
    visible_requests = (
        select(
            MailAction.request_id.label("request_id"),
            func.max(MailAction.created_at).label("created_at"),
            unresolved_failure,
        )
        .where(MailAction.user_id == user_id)
        .group_by(MailAction.request_id)
        .order_by(unresolved_failure.desc(), func.max(MailAction.created_at).desc())
        .limit(limit)
    )
    request_result = await db.execute(visible_requests)
    request_ids = [row.request_id for row in request_result.all()]
    if not request_ids:
        return []

    action_result = await db.execute(
        select(MailAction)
        .where(
            MailAction.user_id == user_id,
            MailAction.request_id.in_(request_ids),
        )
        .order_by(MailAction.created_at.desc(), MailAction.id)
    )
    grouped: dict[UUID, list[MailAction]] = {request_id: [] for request_id in request_ids}
    for action in action_result.scalars().all():
        grouped[action.request_id].append(action)
    return [grouped[request_id] for request_id in request_ids]


async def undo_mail_action_operation(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: UUID,
    now: datetime | None = None,
) -> list[MailAction]:
    current_time = now or utcnow()
    initial_actions = await get_mail_action_operation(
        db,
        user_id=user_id,
        request_id=request_id,
    )
    if all(action.state == "cancelled" for action in initial_actions):
        return initial_actions
    if any(action.state != "staged" for action in initial_actions):
        raise MailActionConflict("Mail action has already started")
    if any(action.undo_until < current_time for action in initial_actions):
        raise MailActionConflict("Mail action undo window has expired")
    if any(action.email_id is None for action in initial_actions):
        raise MailActionConflict("Mail action can no longer be restored")

    email_ids = sorted(
        action.email_id for action in initial_actions if action.email_id is not None
    )
    email_result = await db.execute(
        select(Email).where(Email.id.in_(email_ids)).order_by(Email.id).with_for_update()
    )
    emails = {email.id: email for email in email_result.scalars().all()}
    actions = await get_mail_action_operation(
        db,
        user_id=user_id,
        request_id=request_id,
        for_update=True,
    )
    if any(action.state != "staged" for action in actions):
        raise MailActionConflict("Mail action has already started")
    if any(action.undo_until < current_time for action in actions):
        raise MailActionConflict("Mail action undo window has expired")
    if any(action.email_id is None for action in actions):
        raise MailActionConflict("Mail action can no longer be restored")
    if len(emails) != len(actions):
        raise MailActionConflict("Mail action can no longer be restored")
    for action in actions:
        if await _later_action_blocks_recovery(db, action):
            raise MailActionConflict("A newer action exists for one or more emails")

    for action in actions:
        action.state = "cancelled"
        action.cancelled_at = current_time
        action.updated_at = current_time
        action.next_attempt_at = None
        action.lease_token = None
        action.lease_expires_at = None
        effective_state = await _effective_state_after_transition(
            db,
            action=action,
            transition_state="cancelled",
        )
        apply_mail_state(emails[action.email_id], effective_state)
    await db.commit()
    await _publish_action_event(user_id, request_id)
    return actions


async def retry_mail_action_operation(
    db: AsyncSession,
    *,
    user_id: int,
    request_id: UUID,
    now: datetime | None = None,
) -> list[MailAction]:
    current_time = now or utcnow()
    initial_actions = await get_mail_action_operation(
        db,
        user_id=user_id,
        request_id=request_id,
    )
    initial_failed = [action for action in initial_actions if action.state == "failed"]
    if not initial_failed:
        raise MailActionConflict("Mail action has no failed items to retry")
    if any(action.email_id is None for action in initial_failed):
        raise MailActionConflict("Failed mail action can no longer be retried")
    failed_ids = [action.id for action in initial_failed]
    blocked_result = await db.execute(
        select(exists().where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.state.in_(("returned", "cancelled", "dismissed", "failed")),
            or_(
                EmailSnooze.archive_action_id.in_(failed_ids),
                EmailSnooze.return_action_id.in_(failed_ids),
            ),
        ))
    )
    blocked_by_terminal_snooze = bool(blocked_result.scalar_one())
    if blocked_by_terminal_snooze:
        raise MailActionConflict("This mail action belongs to a completed snooze")

    email_ids = sorted(
        action.email_id for action in initial_failed if action.email_id is not None
    )
    email_result = await db.execute(
        select(Email).where(Email.id.in_(email_ids)).order_by(Email.id).with_for_update()
    )
    emails = {email.id: email for email in email_result.scalars().all()}
    actions = await get_mail_action_operation(
        db,
        user_id=user_id,
        request_id=request_id,
        for_update=True,
    )
    failed = [action for action in actions if action.state == "failed"]
    if not failed or any(action.email_id is None for action in failed):
        raise MailActionConflict("Failed mail action can no longer be retried")
    if len(emails) != len(failed):
        raise MailActionConflict("Failed mail action can no longer be retried")

    for action in failed:
        email = emails[action.email_id]
        if action.action == "unarchive" and (email.is_trash or email.is_spam):
            raise MailActionConflict(
                "Trash and spam must be restored with their dedicated actions"
            )
        if await _later_action_blocks_recovery(db, action):
            raise MailActionConflict("A newer action exists for one or more failed items")
        action.state = "retry_wait"
        action.attempt_count = 0
        action.next_attempt_at = current_time
        action.failed_at = None
        action.error_code = None
        action.error_message = None
        action.updated_at = current_time
        effective_state = await _effective_state_after_transition(
            db,
            action=action,
            transition_state="retry_wait",
        )
        apply_mail_state(email, effective_state)
    await db.commit()
    await _publish_action_event(user_id, request_id)
    return actions


async def overlay_active_mail_actions(
    db: AsyncSession,
    *,
    email: Email,
) -> bool:
    result = await db.execute(
        select(MailAction)
        .where(
            MailAction.email_id == email.id,
            MailAction.state.in_(ACTIVE_MAIL_ACTION_STATES),
        )
        .order_by(MailAction.sequence)
    )
    actions = list(result.scalars().all())
    if not actions:
        return False
    base_state = snapshot_email_state(email)
    state = base_state
    chain_start_sequence = actions[0].sequence
    for action in actions:
        action.base_state = base_state
        action.chain_start_sequence = chain_start_sequence
        action.before_state = state
        state = state_after_label_delta(state, action.add_labels, action.remove_labels)
        action.after_state = state
    apply_mail_state(email, state)
    return True


async def _later_action_blocks_recovery(db: AsyncSession, action: MailAction) -> bool:
    result = await db.execute(
        select(
            exists().where(
                MailAction.email_id == action.email_id,
                MailAction.sequence > action.sequence,
                MailAction.state.in_((*ACTIVE_MAIL_ACTION_STATES, "applied")),
            )
        )
    )
    return bool(result.scalar_one())


async def _effective_state_after_transition(
    db: AsyncSession,
    *,
    action: MailAction,
    transition_state: str,
    applied_state: dict | None = None,
) -> dict:
    """Fold later intent over the transition's confirmed local base."""
    state = canonical_mail_state(action.base_state.get("labels"))
    chain_result = await db.execute(
        select(MailAction)
        .where(
            MailAction.email_id == action.email_id,
            MailAction.sequence >= action.chain_start_sequence,
        )
        .order_by(MailAction.sequence)
    )
    for item in chain_result.scalars().all():
        item_state = transition_state if item.id == action.id else item.state
        if item_state == "applied":
            item_after_state = applied_state if item.id == action.id else item.after_state
            if item_after_state is None:
                raise ValueError("Applied mail actions require canonical Gmail state")
            state = canonical_mail_state(item_after_state.get("labels"))
        elif item_state in ACTIVE_MAIL_ACTION_STATES:
            state = state_after_label_delta(state, item.add_labels, item.remove_labels)
    return state


def classify_mail_action_error(exc: Exception) -> ErrorDisposition:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    error_text = str(exc).lower()
    if status == 403 and any(token in error_text for token in ("quota", "rate", "limit")):
        return ErrorDisposition(True, "gmail_403_rate_limit", "Gmail is temporarily unavailable")
    if status in {400, 401, 403, 404}:
        return ErrorDisposition(False, f"gmail_{status}", "Gmail rejected the mail action")
    if status in {408, 409, 425, 429} or (isinstance(status, int) and status >= 500):
        return ErrorDisposition(True, f"gmail_{status}", "Gmail is temporarily unavailable")
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return ErrorDisposition(True, "gmail_transport", "Gmail is temporarily unavailable")
    return ErrorDisposition(True, "gmail_unknown", "Gmail is temporarily unavailable")


def retry_delay(attempt_count: int) -> timedelta:
    seconds = min(15 * (2 ** max(attempt_count - 1, 0)), 15 * 60)
    return timedelta(seconds=seconds)


async def _reclaim_expired_leases(
    db: AsyncSession,
    *,
    account_id: int,
    now: datetime,
) -> set[tuple[int, UUID]]:
    """Recover expired claims without allowing unbounded Gmail replays.

    The first read is intentionally unlocked: it only discovers the Email rows
    that must be locked first.  The second MailAction read revalidates the
    lease while holding those Email locks, matching sync, undo, retry, and
    worker completion lock ordering.
    """
    preliminary_result = await db.execute(
        select(MailAction)
        .where(
            MailAction.account_id == account_id,
            MailAction.state == "processing",
            MailAction.lease_expires_at <= now,
        )
        .order_by(MailAction.email_id, MailAction.sequence)
    )
    preliminary = list(preliminary_result.scalars().all())
    if not preliminary:
        return set()

    email_ids = sorted(
        {
            action.email_id
            for action in preliminary
            if action.email_id is not None
        }
    )
    emails: dict[int, Email] = {}
    if email_ids:
        email_result = await db.execute(
            select(Email)
            .where(Email.id.in_(email_ids))
            .order_by(Email.id)
            .with_for_update()
        )
        emails = {email.id: email for email in email_result.scalars().all()}

    action_ids = [action.id for action in preliminary]
    action_result = await db.execute(
        select(MailAction)
        .where(
            MailAction.id.in_(action_ids),
            MailAction.account_id == account_id,
            MailAction.state == "processing",
            MailAction.lease_expires_at <= now,
        )
        .order_by(MailAction.email_id, MailAction.sequence)
        .with_for_update(skip_locked=True)
    )
    expired = list(action_result.scalars().all())
    notifications: set[tuple[int, UUID]] = set()
    for action in expired:
        action.lease_token = None
        action.lease_expires_at = None
        action.updated_at = now
        notifications.add((action.user_id, action.request_id))
        email = emails.get(action.email_id) if action.email_id is not None else None

        if action.email_id is None or email is None:
            action.state = "failed"
            action.next_attempt_at = None
            action.error_code = "email_missing"
            action.error_message = "The email no longer exists in the mailbox"
            action.failed_at = now
        elif action.attempt_count >= action.max_attempts:
            action.state = "failed"
            action.next_attempt_at = None
            action.error_code = "lease_attempts_exhausted"
            action.error_message = "Mail action retry limit was reached"
            action.failed_at = now
            effective_state = await _effective_state_after_transition(
                db,
                action=action,
                transition_state="failed",
            )
            apply_mail_state(email, effective_state)
        else:
            action.state = "retry_wait"
            action.next_attempt_at = now
            action.error_code = "lease_expired"
            action.error_message = "Mail action worker lease expired; retrying"

    return notifications


async def _terminalize_orphaned_actions(
    db: AsyncSession,
    *,
    account_id: int,
    now: datetime,
) -> set[tuple[int, UUID]]:
    """Fail active work whose local email was deleted by authoritative sync."""
    result = await db.execute(
        update(MailAction)
        .where(
            MailAction.account_id == account_id,
            MailAction.email_id.is_(None),
            MailAction.state.in_(ACTIVE_MAIL_ACTION_STATES),
        )
        .values(
            state="failed",
            next_attempt_at=None,
            lease_token=None,
            lease_expires_at=None,
            error_code="email_missing",
            error_message="The email no longer exists in the mailbox",
            failed_at=now,
            updated_at=now,
        )
        .returning(MailAction.user_id, MailAction.request_id)
    )
    return {(row.user_id, row.request_id) for row in result.all()}


async def _claim_due_actions(
    db: AsyncSession,
    *,
    account_id: int,
    now: datetime,
    limit: int,
) -> list[MailAction]:
    notifications = await _terminalize_orphaned_actions(
        db,
        account_id=account_id,
        now=now,
    )
    notifications.update(await _reclaim_expired_leases(
        db,
        account_id=account_id,
        now=now,
    ))
    earlier = aliased(MailAction)
    due = or_(
        and_(MailAction.state == "staged", MailAction.execute_after <= now),
        and_(MailAction.state == "retry_wait", MailAction.next_attempt_at <= now),
    )
    no_earlier_active = ~exists(
        select(earlier.id).where(
            earlier.email_id == MailAction.email_id,
            earlier.sequence < MailAction.sequence,
            earlier.state.in_(ACTIVE_MAIL_ACTION_STATES),
        )
    )
    result = await db.execute(
        select(MailAction)
        .where(
            MailAction.account_id == account_id,
            MailAction.email_id.isnot(None),
            due,
            no_earlier_active,
        )
        .order_by(MailAction.email_id, MailAction.sequence)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    actions = list(result.scalars().all())
    lease_expires_at = now + timedelta(seconds=MAIL_ACTION_LEASE_SECONDS)
    for action in actions:
        action.state = "processing"
        action.attempt_count += 1
        action.lease_token = uuid4()
        action.lease_expires_at = lease_expires_at
        action.processing_started_at = now
        action.next_attempt_at = None
        action.updated_at = now
    await db.commit()
    for user_id, request_id in notifications:
        await _publish_action_event(user_id, request_id)
    return actions


async def _record_action_success(
    *,
    action_id: int,
    lease_token: UUID,
    gmail_result: dict,
    now: datetime,
) -> bool:
    labels = gmail_result.get("labelIds") if isinstance(gmail_result, dict) else None
    if not isinstance(labels, list):
        raise RuntimeError("Gmail label response did not include canonical labels")
    remote_state = canonical_mail_state(labels)

    async with async_session() as db:
        action, email = await _lock_processing_action_and_email(
            db,
            action_id=action_id,
            lease_token=lease_token,
        )
        if action is None:
            return False

        if email is not None:
            effective_state = await _effective_state_after_transition(
                db,
                action=action,
                transition_state="applied",
                applied_state=remote_state,
            )
            apply_mail_state(email, effective_state)

        action.after_state = remote_state
        action.gmail_history_id = (
            str(gmail_result.get("historyId"))
            if gmail_result.get("historyId") is not None
            else None
        )
        action.state = "applied"
        action.applied_at = now
        action.updated_at = now
        action.lease_token = None
        action.lease_expires_at = None
        action.error_code = None
        action.error_message = None
        await db.commit()
        user_id = action.user_id
        request_id = action.request_id

    await _publish_action_event(user_id, request_id)
    return True


async def _record_action_failure(
    *,
    action_id: int,
    lease_token: UUID,
    disposition: ErrorDisposition,
    now: datetime,
) -> bool:
    async with async_session() as db:
        action, email = await _lock_processing_action_and_email(
            db,
            action_id=action_id,
            lease_token=lease_token,
        )
        if action is None:
            return False

        should_retry = disposition.retryable and action.attempt_count < action.max_attempts
        action.lease_token = None
        action.lease_expires_at = None
        action.error_code = disposition.code
        action.error_message = disposition.message
        action.updated_at = now
        if should_retry:
            action.state = "retry_wait"
            action.next_attempt_at = now + retry_delay(action.attempt_count)
        else:
            action.state = "failed"
            action.failed_at = now
            action.next_attempt_at = None
            if email is not None:
                effective_state = await _effective_state_after_transition(
                    db,
                    action=action,
                    transition_state="failed",
                )
                apply_mail_state(email, effective_state)

        await db.commit()
        user_id = action.user_id
        request_id = action.request_id

    await _publish_action_event(user_id, request_id)
    return True


async def _lock_processing_action_and_email(
    db: AsyncSession,
    *,
    action_id: int,
    lease_token: UUID,
) -> tuple[MailAction | None, Email | None]:
    """Lock Email before MailAction to match sync and recovery endpoints."""
    preliminary_result = await db.execute(
        select(MailAction).where(MailAction.id == action_id)
    )
    preliminary = preliminary_result.scalar_one_or_none()
    if preliminary is None:
        return None, None

    email = None
    if preliminary.email_id is not None:
        email_result = await db.execute(
            select(Email).where(Email.id == preliminary.email_id).with_for_update()
        )
        email = email_result.scalar_one_or_none()

    action_result = await db.execute(
        select(MailAction)
        .where(
            MailAction.id == action_id,
            MailAction.state == "processing",
            MailAction.lease_token == lease_token,
        )
        .with_for_update()
    )
    return action_result.scalar_one_or_none(), email


async def _publish_action_event(user_id: int, request_id: UUID) -> None:
    try:
        from backend.services.notifications import publish_event

        await _await_bounded(
            publish_event(
                user_id,
                "mail_action_updated",
                {"request_id": str(request_id)},
            ),
            timeout=MAIL_ACTION_REDIS_IO_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Could not publish mail action update", exc_info=True)


async def _due_account_ids(now: datetime, limit: int = 50) -> list[int]:
    due = or_(
        and_(MailAction.state == "staged", MailAction.execute_after <= now),
        and_(MailAction.state == "retry_wait", MailAction.next_attempt_at <= now),
        and_(MailAction.state == "processing", MailAction.lease_expires_at <= now),
    )
    async with async_session() as db:
        result = await db.execute(
            select(MailAction.account_id)
            .where(due)
            .distinct()
            .order_by(MailAction.account_id)
            .limit(limit)
        )
        return list(result.scalars().all())


async def drain_due_mail_actions() -> int:
    """Drain due database work, serializing Gmail changes against sync."""
    processed = 0
    for account_id in await _due_account_ids(utcnow()):
        remaining = MAIL_ACTION_DRAIN_MAX_ACTIONS - processed
        if remaining <= 0:
            break
        try:
            processed += await _drain_account_mail_actions(
                account_id,
                max_actions=remaining,
            )
        except Exception:
            logger.exception("Mail action drain failed for account %s", account_id)
    return processed


async def _drain_account_mail_actions(
    account_id: int,
    *,
    max_actions: int = MAIL_ACTION_DRAIN_MAX_ACTIONS,
) -> int:
    processed = 0
    async with account_advisory_lock(account_id) as acquired:
        if not acquired:
            return 0

        gmail: GmailService | None = None
        while processed < max_actions:
            claim_time = utcnow()
            async with async_session() as db:
                actions = await _claim_due_actions(
                    db,
                    account_id=account_id,
                    now=claim_time,
                    limit=min(
                        MAIL_ACTION_DRAIN_BATCH,
                        max_actions - processed,
                    ),
                )
            if not actions:
                break

            if gmail is None:
                try:
                    async with async_session() as db:
                        account_result = await db.execute(
                            select(GoogleAccount).where(GoogleAccount.id == account_id)
                        )
                        account = account_result.scalar_one_or_none()
                        if account is None:
                            disposition = ErrorDisposition(
                                False,
                                "account_missing",
                                "The mail account is no longer available",
                            )
                        else:
                            client_id, client_secret = await get_google_credentials(db)
                            gmail = GmailService(
                                account,
                                client_id=client_id,
                                client_secret=client_secret,
                                transport_timeout=MAIL_ACTION_GMAIL_TRANSPORT_TIMEOUT_SECONDS,
                            )
                            disposition = None
                except Exception as exc:
                    disposition = classify_mail_action_error(exc)

                if gmail is None:
                    for action in actions:
                        if action.lease_token is not None:
                            await _record_action_failure(
                                action_id=action.id,
                                lease_token=action.lease_token,
                                disposition=disposition,
                                now=utcnow(),
                            )
                            processed += 1
                    break

            for action in actions:
                lease_token = action.lease_token
                if lease_token is None:
                    continue
                try:
                    gmail_result = await gmail.modify_labels(
                        action.gmail_message_id,
                        add_labels=list(action.add_labels or []),
                        remove_labels=list(action.remove_labels or []),
                        max_retries=1,
                    )
                    await _persist_refreshed_token(account_id, gmail)
                    await _record_action_success(
                        action_id=action.id,
                        lease_token=lease_token,
                        gmail_result=gmail_result,
                        now=utcnow(),
                    )
                except Exception as exc:
                    await _persist_refreshed_token(account_id, gmail)
                    disposition = classify_mail_action_error(exc)
                    await _record_action_failure(
                        action_id=action.id,
                        lease_token=lease_token,
                        disposition=disposition,
                        now=utcnow(),
                    )
                processed += 1
    return processed


async def _persist_refreshed_token(account_id: int, gmail: GmailService) -> None:
    token = gmail.get_refreshed_token()
    if not token:
        return
    try:
        async with async_session() as db:
            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.id == account_id)
                .values(encrypted_access_token=encrypt_value(token))
            )
            await db.commit()
    except Exception:
        logger.warning(
            "Could not persist refreshed Gmail token for account %s",
            account_id,
            exc_info=True,
        )


async def try_enqueue_mail_action_drain() -> None:
    """Best-effort wakeup; durable cron draining is the recovery path."""
    try:
        await _await_bounded(
            _enqueue_mail_action_drain(),
            timeout=MAIL_ACTION_REDIS_IO_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Could not enqueue mail action drain; cron will recover it", exc_info=True)


async def _enqueue_mail_action_drain() -> None:
    settings = get_settings()
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await redis.enqueue_job(
            "drain_mail_actions_task",
            _queue_name=MAIL_ACTION_QUEUE_NAME,
            _defer_by=timedelta(seconds=MAIL_ACTION_UNDO_SECONDS),
        )
    finally:
        await redis.close()
