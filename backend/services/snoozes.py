"""PostgreSQL-authoritative, conversation-scoped universal snooze."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.config import get_settings
from backend.database import async_session
from backend.models.account import GoogleAccount, SyncStatus
from backend.models.email import Email
from backend.models.mail_action import ACTIVE_MAIL_ACTION_STATES, MailAction
from backend.models.snooze import EmailSnooze, SNOOZE_ACTIVE_STATES
from backend.schemas.snooze import (
    SnoozeCreateRequest,
    SnoozedEmailSummary,
    SnoozeListResponse,
    SnoozeResponse,
)
from backend.services.mail_actions import (
    MailActionConflict,
    MailActionNotFound,
    MailActionValidationError,
    get_mail_action_operation_by_idempotency,
    retry_mail_action_operation,
    stage_mail_actions,
    try_enqueue_mail_action_drain,
    undo_mail_action_operation,
)


logger = logging.getLogger(__name__)

SNOOZE_QUEUE_NAME = "arq:cron"
SNOOZE_LEASE_SECONDS = 120
SNOOZE_DRAIN_LIMIT = 50
SNOOZE_REDIS_TIMEOUT_SECONDS = 1.0
SNOOZE_ACTION_NAMESPACE = UUID("a30fa772-271d-54fa-8918-a171a39c5192")
PLACEMENT_ACTIONS = {"archive", "unarchive", "trash", "untrash", "spam", "unspam"}
TERMINAL_STATES = {"returned", "cancelled", "dismissed", "failed"}


class SnoozeError(RuntimeError):
    pass


class SnoozeNotFound(SnoozeError):
    pass


class SnoozeConflict(SnoozeError):
    pass


class SnoozeValidationError(SnoozeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(request: SnoozeCreateRequest) -> str:
    encoded = json.dumps(
        {
            "condition": request.condition,
            "email_id": request.email_id,
            "time_zone": request.time_zone,
            "wake_at": request.wake_at.astimezone(timezone.utc).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _advisory_key(user_id: int, value: UUID) -> int:
    digest = hashlib.sha256(f"snooze:{user_id}:{value}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def _lock_idempotency(db: AsyncSession, *, user_id: int, key: UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _advisory_key(user_id, key)},
    )


def _action_key(public_id: UUID, purpose: str) -> UUID:
    return uuid5(SNOOZE_ACTION_NAMESPACE, f"{public_id}:{purpose}")


def _ids(values) -> list[int]:
    return sorted({int(value) for value in (values or []) if int(value) > 0})


def _response(row: EmailSnooze) -> SnoozeResponse:
    account_email = row.account.email
    email = row.email
    summary = None
    if email is not None:
        summary = SnoozedEmailSummary(
            id=email.id,
            gmail_message_id=email.gmail_message_id,
            gmail_thread_id=email.gmail_thread_id,
            subject=email.subject,
            from_address=email.from_address,
            from_name=email.from_name,
            to_addresses=email.to_addresses or [],
            date=email.date,
            snippet=email.snippet,
            is_read=email.is_read,
            is_starred=email.is_starred,
            is_sent=email.is_sent,
            is_trash=email.is_trash,
            is_spam=email.is_spam,
            has_attachments=email.has_attachments,
            labels=email.labels or [],
            account_email=account_email,
        )
    archive_action = row.archive_action
    return SnoozeResponse(
        id=row.public_id,
        email_id=row.email_id,
        account_id=row.account_id,
        account_email=account_email,
        gmail_thread_id=row.gmail_thread_id,
        wake_at=row.wake_at,
        time_zone=row.time_zone,
        condition=row.condition,
        state=row.state,
        status_detail=row.status_detail,
        archive_required=row.archive_required,
        originally_in_inbox=bool(_ids(row.original_inbox_email_ids)),
        conversation_message_count=len(_ids(row.conversation_email_ids)),
        archive_action_request_id=archive_action.request_id if archive_action else None,
        archive_undo_until=archive_action.undo_until if archive_action else None,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        scheduled_at=row.scheduled_at,
        returned_at=row.returned_at,
        cancelled_at=row.cancelled_at,
        dismissed_at=row.dismissed_at,
        failed_at=row.failed_at,
        email=summary,
    )


def _loaded_query():
    return select(EmailSnooze).execution_options(populate_existing=True).options(
        joinedload(EmailSnooze.account),
        joinedload(EmailSnooze.email),
        joinedload(EmailSnooze.archive_action),
        joinedload(EmailSnooze.return_action),
    )


async def _reload(db: AsyncSession, row_id: int) -> EmailSnooze:
    result = await db.execute(_loaded_query().where(EmailSnooze.id == row_id))
    return result.scalar_one()


async def _owned_snooze(
    db: AsyncSession,
    *,
    user_id: int,
    public_id: UUID,
    for_update: bool = False,
) -> EmailSnooze:
    statement = _loaded_query().where(
        EmailSnooze.user_id == user_id,
        EmailSnooze.public_id == public_id,
    )
    if for_update:
        statement = (
            select(EmailSnooze)
            .where(
                EmailSnooze.user_id == user_id,
                EmailSnooze.public_id == public_id,
            )
            .with_for_update()
        )
    result = await db.execute(statement)
    row = result.scalar_one_or_none()
    if row is None:
        raise SnoozeNotFound("Snooze not found")
    return row


async def _locked_conversation(db: AsyncSession, row: EmailSnooze) -> list[Email]:
    result = await db.execute(
        select(Email)
        .where(
            Email.account_id == row.account_id,
            Email.gmail_thread_id == row.gmail_thread_id,
        )
        .order_by(Email.id)
        .with_for_update()
    )
    return list(result.scalars().all())


def _eligible(email: Email) -> bool:
    return not email.is_draft and not email.is_trash and not email.is_spam


async def _actions_for_key(
    db: AsyncSession, *, user_id: int, key: UUID
) -> list[MailAction]:
    try:
        return await get_mail_action_operation_by_idempotency(
            db, user_id=user_id, idempotency_key=key
        )
    except MailActionNotFound:
        return []


async def _actions_for_purpose(
    db: AsyncSession, row: EmailSnooze, purpose: str
) -> list[MailAction]:
    key = row.archive_idempotency_key if purpose == "archive" else row.return_idempotency_key
    return await _actions_for_key(db, user_id=row.user_id, key=key)


def _terminal(row: EmailSnooze, state: str, now: datetime, detail: str) -> None:
    row.state = state
    row.status_detail = detail
    row.next_attempt_at = None
    row.lease_token = None
    row.lease_expires_at = None
    row.pending_action_purpose = None
    row.completion_state = None
    row.updated_at = now
    if state == "returned":
        row.returned_at = now
    elif state == "cancelled":
        row.cancelled_at = now
    elif state == "dismissed":
        row.dismissed_at = now
    elif state == "failed":
        row.failed_at = now


def _operation_error(row: EmailSnooze, purpose: str, actions: list[MailAction], now: datetime) -> None:
    failed = next((action for action in actions if action.state == "failed"), None)
    _terminal(row, "failed", now, f"{purpose}_failed")
    row.error_code = f"{purpose}_failed"
    row.error_message = failed.error_message if failed else f"Gmail {purpose} failed"


async def _stage_locked_operation(
    db: AsyncSession,
    *,
    row: EmailSnooze,
    email_ids: list[int],
    action_name: str,
    purpose: str,
    completion_state: str | None,
    status_detail: str,
    now: datetime,
    retry_failed: bool = False,
) -> list[MailAction]:
    """Assign mail-action sequence numbers while conversation Email locks are held."""
    key = row.archive_idempotency_key if purpose == "archive" else row.return_idempotency_key
    existing = await _actions_for_key(db, user_id=row.user_id, key=key)
    if existing and any(action.state == "failed" for action in existing) and retry_failed:
        await retry_mail_action_operation(
            db,
            user_id=row.user_id,
            request_id=existing[0].request_id,
            now=now,
        )
        existing = await _actions_for_key(db, user_id=row.user_id, key=key)

    row.state = "pending_archive" if purpose == "archive" and completion_state is None else "pending_return"
    row.status_detail = status_detail
    row.pending_action_purpose = purpose
    row.completion_state = completion_state
    row.return_target_email_ids = email_ids if completion_state is not None else []
    row.next_attempt_at = now
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = now

    if existing:
        expected = sorted(action.email_id for action in existing if action.email_id is not None)
        if expected != sorted(email_ids) or any(action.action != action_name for action in existing):
            raise SnoozeConflict("Snooze action recovery payload changed")
        actions = existing
    else:
        try:
            actions, _created = await stage_mail_actions(
                db,
                user_id=row.user_id,
                email_ids=email_ids,
                action=action_name,
                idempotency_key=key,
                now=now,
            )
        except (MailActionConflict, MailActionNotFound, MailActionValidationError) as exc:
            raise SnoozeConflict(str(exc)) from exc

    # stage_mail_actions commits this same transaction, so manual placement
    # cannot receive a lower sequence after our decision but before staging.
    if purpose == "archive":
        row.archive_action_id = actions[0].id
    else:
        row.return_action_id = actions[0].id
    row.next_attempt_at = max(action.execute_after for action in actions)
    await db.commit()
    await try_enqueue_mail_action_drain()
    return actions


async def _newer_placement_email_ids_since_schedule(
    db: AsyncSession, row: EmailSnooze, conversation_ids: list[int]
) -> set[int]:
    if not conversation_ids:
        return set()
    own_actions = (
        await _actions_for_purpose(db, row, "archive")
        + await _actions_for_purpose(db, row, "unarchive")
    )
    own_ids = {action.id for action in own_actions}
    versions = {
        int(email_id): int(version)
        for email_id, version in (row.mail_action_versions_at_schedule or {}).items()
    }
    result = await db.execute(
        select(MailAction).where(
            MailAction.email_id.in_(conversation_ids),
            MailAction.action.in_(PLACEMENT_ACTIONS),
            MailAction.state.in_((*ACTIVE_MAIL_ACTION_STATES, "applied")),
        )
    )
    return {
        int(action.email_id)
        for action in result.scalars().all()
        if action.email_id is not None
        and action.id not in own_ids
        and action.sequence > versions.get(int(action.email_id), 0)
    }


async def _newer_placement_after_operation(
    db: AsyncSession, actions: list[MailAction]
) -> bool:
    own_ids = {action.id for action in actions}
    for action in actions:
        if action.email_id is None:
            continue
        found = await db.scalar(
            select(exists().where(
                MailAction.email_id == action.email_id,
                MailAction.sequence > action.sequence,
                MailAction.id.notin_(own_ids),
                MailAction.action.in_(PLACEMENT_ACTIONS),
                MailAction.state.in_((*ACTIVE_MAIL_ACTION_STATES, "applied")),
            ))
        )
        if found:
            return True
    return False


async def _has_reply(db: AsyncSession, row: EmailSnooze) -> bool:
    if row.anchor_date is None:
        return False
    return bool(await db.scalar(
        select(exists().where(
            Email.account_id == row.account_id,
            Email.gmail_thread_id == row.gmail_thread_id,
            Email.id != row.email_id,
            or_(
                Email.date > row.anchor_date,
                (Email.date == row.anchor_date) & (Email.id > (row.email_id or 0)),
            ),
            Email.is_sent.is_(False),
            Email.is_draft.is_(False),
            Email.is_trash.is_(False),
            Email.is_spam.is_(False),
        ))
    ))


async def _reply_check_is_fresh(db: AsyncSession, row: EmailSnooze) -> bool:
    status = await db.scalar(
        select(SyncStatus).where(SyncStatus.account_id == row.account_id)
    )
    if status is None:
        return False
    checkpoints = [
        value for value in (status.last_incremental_sync, status.last_full_sync)
        if value is not None
    ]
    return bool(checkpoints and max(checkpoints) >= row.wake_at)


async def create_snooze(
    db: AsyncSession,
    *,
    user_id: int,
    request: SnoozeCreateRequest,
    now: datetime | None = None,
) -> tuple[SnoozeResponse, bool]:
    accepted_at = now or utcnow()
    payload_hash = _payload_hash(request)
    await _lock_idempotency(db, user_id=user_id, key=request.idempotency_key)
    existing = await db.scalar(
        select(EmailSnooze).where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.idempotency_key == request.idempotency_key,
        ).with_for_update()
    )
    # Time-dependent validation must not break exact replay after wake_at.
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise SnoozeConflict("Idempotency key was already used for another snooze")
        return _response(await _reload(db, existing.id)), False

    wake_at = request.wake_at.astimezone(timezone.utc)
    if wake_at <= accepted_at:
        raise SnoozeValidationError("wake_at must be in the future")

    owned = (await db.execute(
        select(Email, GoogleAccount)
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .where(Email.id == request.email_id, GoogleAccount.user_id == user_id)
    )).one_or_none()
    if owned is None:
        raise SnoozeNotFound("Email not found")
    anchor, account = owned
    if anchor.is_trash or anchor.is_spam:
        raise SnoozeConflict("Trash and spam cannot be snoozed")
    if anchor.is_draft:
        raise SnoozeConflict("Drafts cannot be snoozed")

    active = await db.scalar(
        select(EmailSnooze).where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.account_id == account.id,
            EmailSnooze.gmail_thread_id == anchor.gmail_thread_id,
            EmailSnooze.state.in_(SNOOZE_ACTIVE_STATES),
        ).with_for_update()
    )
    if active is not None:
        raise SnoozeConflict("This conversation is already snoozed")

    conversation_result = await db.execute(
        select(Email)
        .where(
            Email.account_id == account.id,
            Email.gmail_thread_id == anchor.gmail_thread_id,
        )
        .order_by(Email.id)
        .with_for_update()
    )
    conversation = list(conversation_result.scalars().all())
    eligible = [email for email in conversation if _eligible(email)]
    original_inbox_ids = [
        email.id for email in eligible if "INBOX" in set(email.labels or [])
    ]
    public_id = uuid4()
    row = EmailSnooze(
        public_id=public_id,
        idempotency_key=request.idempotency_key,
        payload_hash=payload_hash,
        user_id=user_id,
        account_id=account.id,
        email_id=anchor.id,
        gmail_message_id=anchor.gmail_message_id,
        gmail_thread_id=anchor.gmail_thread_id,
        wake_at=wake_at,
        time_zone=request.time_zone,
        condition=request.condition,
        state="pending_archive" if original_inbox_ids else "scheduled",
        status_detail="archiving" if original_inbox_ids else "scheduled",
        archive_required=bool(original_inbox_ids),
        anchor_date=anchor.date or accepted_at,
        mail_action_version_at_schedule=int(anchor.mail_action_version or 0),
        conversation_email_ids=[email.id for email in conversation],
        original_inbox_email_ids=original_inbox_ids,
        mail_action_versions_at_schedule={
            str(email.id): int(email.mail_action_version or 0) for email in conversation
        },
        return_target_email_ids=[],
        completion_state=None,
        pending_action_purpose="archive" if original_inbox_ids else None,
        archive_idempotency_key=_action_key(public_id, "archive"),
        return_idempotency_key=_action_key(public_id, "return"),
        next_attempt_at=accepted_at if original_inbox_ids else wake_at,
        created_at=accepted_at,
        updated_at=accepted_at,
        scheduled_at=accepted_at if not original_inbox_ids else None,
    )
    db.add(row)
    try:
        await db.flush()
        if original_inbox_ids:
            await _stage_locked_operation(
                db,
                row=row,
                email_ids=original_inbox_ids,
                action_name="archive",
                purpose="archive",
                completion_state=None,
                status_detail="archiving",
                now=accepted_at,
            )
        else:
            await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise SnoozeConflict("This conversation is already snoozed") from exc

    await _publish_snooze_event(user_id, public_id)
    return _response(await _reload(db, row.id)), True


async def get_snooze(db: AsyncSession, *, user_id: int, public_id: UUID) -> SnoozeResponse:
    return _response(await _owned_snooze(db, user_id=user_id, public_id=public_id))


async def get_snooze_by_idempotency(
    db: AsyncSession, *, user_id: int, idempotency_key: UUID
) -> SnoozeResponse:
    row = await db.scalar(
        _loaded_query().where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.idempotency_key == idempotency_key,
        )
    )
    if row is None:
        raise SnoozeNotFound("Snooze not found")
    return _response(row)


async def list_snoozes(
    db: AsyncSession,
    *,
    user_id: int,
    state: str,
    limit: int,
    offset: int,
) -> SnoozeListResponse:
    filters = [EmailSnooze.user_id == user_id]
    if state == "active":
        filters.append(EmailSnooze.state.in_(SNOOZE_ACTIVE_STATES))
    elif state == "cancelled":
        filters.append(EmailSnooze.state.in_(("cancelled", "dismissed")))
    elif state != "all":
        filters.append(EmailSnooze.state == state)
    total = int(await db.scalar(
        select(func.count()).select_from(EmailSnooze).where(*filters)
    ) or 0)
    rows = list((await db.execute(
        _loaded_query()
        .where(*filters)
        .order_by(EmailSnooze.wake_at, EmailSnooze.id)
        .limit(limit)
        .offset(offset)
    )).scalars().unique().all())
    return SnoozeListResponse(
        items=[_response(row) for row in rows], total=total, limit=limit, offset=offset
    )


async def reschedule_snooze(
    db: AsyncSession,
    *,
    user_id: int,
    public_id: UUID,
    wake_at: datetime,
    time_zone: str,
    now: datetime | None = None,
) -> SnoozeResponse:
    changed_at = now or utcnow()
    wake_at = wake_at.astimezone(timezone.utc)
    if wake_at <= changed_at:
        raise SnoozeValidationError("wake_at must be in the future")
    row = await _owned_snooze(
        db, user_id=user_id, public_id=public_id, for_update=True
    )
    if row.state not in ("pending_archive", "scheduled"):
        raise SnoozeConflict("Only an active snooze can be rescheduled")
    if row.lease_token and row.lease_expires_at and row.lease_expires_at > changed_at:
        raise SnoozeConflict("Snooze is currently being processed")
    row.wake_at = wake_at
    row.time_zone = time_zone
    if row.state == "scheduled":
        row.next_attempt_at = wake_at
    row.updated_at = changed_at
    await db.commit()
    await _publish_snooze_event(user_id, public_id)
    return _response(await _reload(db, row.id))


async def _undo_operation_if_possible(
    db: AsyncSession, row: EmailSnooze, actions: list[MailAction], now: datetime
) -> bool:
    if not actions or any(action.state != "staged" for action in actions):
        return False
    if any(action.undo_until < now for action in actions):
        return False
    try:
        await undo_mail_action_operation(
            db, user_id=row.user_id, request_id=actions[0].request_id, now=now
        )
    except MailActionConflict:
        return False
    return True


async def _restore_original(
    db: AsyncSession,
    *,
    row: EmailSnooze,
    conversation: list[Email],
    completion_state: str,
    now: datetime,
) -> None:
    original_ids = set(_ids(row.original_inbox_email_ids))
    return_actions = await _actions_for_purpose(db, row, "unarchive")

    # A Sent/All Mail reminder has no Inbox placement to restore. If an
    # automated due-return already started, reverse that exact operation.
    if not original_ids:
        if not return_actions:
            _terminal(row, completion_state, now, f"{completion_state}_original_placement")
            await db.commit()
            return
        if await _undo_operation_if_possible(db, row, return_actions, now):
            _terminal(row, completion_state, now, f"{completion_state}_original_placement")
            await db.commit()
            return
        targets = [
            email.id for email in conversation
            if email.id in set(_ids(row.return_target_email_ids)) and _eligible(email)
        ]
        if not targets:
            _terminal(row, completion_state, now, f"{completion_state}_original_placement")
            await db.commit()
            return
        await _stage_locked_operation(
            db,
            row=row,
            email_ids=targets,
            action_name="archive",
            purpose="archive",
            completion_state=completion_state,
            status_detail="restoring_original_archive",
            now=now,
            retry_failed=True,
        )
        return

    archive_actions = await _actions_for_purpose(db, row, "archive")
    if await _undo_operation_if_possible(db, row, archive_actions, now):
        _terminal(row, completion_state, now, f"{completion_state}_original_placement")
        await db.commit()
        return
    targets = [
        email.id for email in conversation
        if email.id in original_ids and _eligible(email) and "INBOX" not in set(email.labels or [])
    ]
    if not targets:
        _terminal(row, completion_state, now, f"{completion_state}_original_placement")
        await db.commit()
        return
    await _stage_locked_operation(
        db,
        row=row,
        email_ids=targets,
        action_name="unarchive",
        purpose="unarchive",
        completion_state=completion_state,
        status_detail=f"{completion_state}_restoring_inbox",
        now=now,
        retry_failed=True,
    )


async def cancel_snooze(
    db: AsyncSession, *, user_id: int, public_id: UUID, now: datetime | None = None
) -> SnoozeResponse:
    changed_at = now or utcnow()
    row = await _owned_snooze(
        db, user_id=user_id, public_id=public_id, for_update=True
    )
    if row.state in TERMINAL_STATES:
        return _response(await _reload(db, row.id))
    conversation = await _locked_conversation(db, row)
    await _restore_original(
        db, row=row, conversation=conversation, completion_state="cancelled", now=changed_at
    )
    await _publish_snooze_event(user_id, public_id)
    return _response(await _reload(db, row.id))


async def return_snooze_now(
    db: AsyncSession, *, user_id: int, public_id: UUID, now: datetime | None = None
) -> SnoozeResponse:
    changed_at = now or utcnow()
    row = await _owned_snooze(
        db, user_id=user_id, public_id=public_id, for_update=True
    )
    if row.state in TERMINAL_STATES:
        return _response(await _reload(db, row.id))
    conversation = await _locked_conversation(db, row)
    if row.state == "pending_return" and row.pending_action_purpose == "archive":
        raise SnoozeConflict("The conversation is currently restoring its original placement")
    existing_return = await _actions_for_purpose(db, row, "unarchive")
    if existing_return:
        row.completion_state = "returned"
        row.status_detail = "returning"
        await db.commit()
    else:
        eligible = [email for email in conversation if _eligible(email)]
        conversation_ids = [email.id for email in conversation]
        manually_placed = await _newer_placement_email_ids_since_schedule(
            db, row, conversation_ids
        )
        original_ids = set(_ids(row.original_inbox_email_ids))
        targets = [
            email.id for email in eligible
            if email.id in original_ids and email.id not in manually_placed
        ]
        candidates = [email for email in eligible if email.id not in manually_placed]
        if not targets and not original_ids and candidates:
            targets = [max(
                candidates,
                key=lambda email: (
                    email.date or datetime.min.replace(tzinfo=timezone.utc), email.id
                ),
            ).id]
        if not targets:
            _terminal(
                row,
                "dismissed" if manually_placed else "failed",
                changed_at,
                "newer_manual_action" if manually_placed else "conversation_missing",
            )
            await db.commit()
        else:
            archive_actions = await _actions_for_purpose(db, row, "archive")
            if original_ids and await _undo_operation_if_possible(
                db, row, archive_actions, changed_at
            ):
                _terminal(row, "returned", changed_at, "returned_now")
                await db.commit()
            else:
                await _stage_locked_operation(
                    db,
                    row=row,
                    email_ids=targets,
                    action_name="unarchive",
                    purpose="unarchive",
                    completion_state="returned",
                    status_detail="returning_now",
                    now=changed_at,
                    retry_failed=True,
                )
    await _publish_snooze_event(user_id, public_id)
    return _response(await _reload(db, row.id))


async def _claim_due(now: datetime, limit: int) -> list[tuple[int, UUID]]:
    async with async_session() as db:
        due = or_(
            (EmailSnooze.state == "scheduled") & (EmailSnooze.wake_at <= now),
            (EmailSnooze.state.in_(("pending_archive", "pending_return")))
            & (EmailSnooze.next_attempt_at <= now),
        )
        rows = list((await db.execute(
            select(EmailSnooze)
            .where(
                EmailSnooze.state.in_(SNOOZE_ACTIVE_STATES),
                due,
                or_(EmailSnooze.lease_token.is_(None), EmailSnooze.lease_expires_at <= now),
            )
            .order_by(EmailSnooze.next_attempt_at, EmailSnooze.wake_at, EmailSnooze.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )).scalars().all())
        claimed = []
        for row in rows:
            token = uuid4()
            row.lease_token = token
            row.lease_expires_at = now + timedelta(seconds=SNOOZE_LEASE_SECONDS)
            row.attempt_count += 1
            row.updated_at = now
            claimed.append((row.id, token))
        await db.commit()
        return claimed


async def _process_claim(row_id: int, token: UUID, now: datetime) -> None:
    async with async_session() as db:
        row = await db.scalar(
            select(EmailSnooze)
            .where(EmailSnooze.id == row_id, EmailSnooze.lease_token == token)
            .with_for_update()
        )
        if row is None:
            return
        conversation = await _locked_conversation(db, row)
        eligible = [email for email in conversation if _eligible(email)]
        conversation_ids = [email.id for email in conversation]

        if row.state == "pending_archive":
            actions = await _actions_for_purpose(db, row, "archive")
            if not actions:
                targets = [
                    email.id for email in eligible
                    if email.id in set(_ids(row.original_inbox_email_ids))
                ]
                if not targets:
                    _terminal(row, "failed", now, "conversation_missing")
                    row.error_code = "conversation_missing"
                    row.error_message = "The conversation no longer exists"
                else:
                    await _stage_locked_operation(
                        db,
                        row=row,
                        email_ids=targets,
                        action_name="archive",
                        purpose="archive",
                        completion_state=None,
                        status_detail="archiving",
                        now=now,
                    )
                    actions = await _actions_for_purpose(db, row, "archive")
            if actions:
                row.archive_action_id = actions[0].id
                states = {action.state for action in actions}
                if states.intersection(ACTIVE_MAIL_ACTION_STATES):
                    row.next_attempt_at = now + timedelta(seconds=15)
                elif states == {"applied"}:
                    row.state = "scheduled"
                    row.status_detail = "scheduled"
                    row.pending_action_purpose = None
                    row.scheduled_at = now
                    row.next_attempt_at = row.wake_at
                    row.error_code = None
                    row.error_message = None
                elif "failed" in states:
                    _operation_error(row, "archive", actions, now)
                elif states == {"cancelled"}:
                    _terminal(row, "cancelled", now, "archive_undone")
                else:
                    _operation_error(row, "archive", actions, now)

        elif row.state == "scheduled":
            if row.condition == "if_no_reply" and not await _reply_check_is_fresh(db, row):
                row.status_detail = "waiting_for_reply_sync"
                row.next_attempt_at = now + timedelta(seconds=30)
            elif row.condition == "if_no_reply" and await _has_reply(db, row):
                _terminal(row, "dismissed", now, "reply_received")
            elif any("INBOX" in set(email.labels or []) for email in eligible):
                _terminal(row, "returned", now, "already_in_inbox")
            else:
                manually_placed = await _newer_placement_email_ids_since_schedule(
                    db, row, conversation_ids
                )
                original_ids = set(_ids(row.original_inbox_email_ids))
                targets = [
                    email.id for email in eligible
                    if email.id in original_ids and email.id not in manually_placed
                ]
                candidates = [
                    email for email in eligible if email.id not in manually_placed
                ]
                if not targets and not original_ids and candidates:
                    representative = max(
                        candidates,
                        key=lambda email: (email.date or datetime.min.replace(tzinfo=timezone.utc), email.id),
                    )
                    targets = [representative.id]
                if not targets:
                    if manually_placed:
                        _terminal(row, "dismissed", now, "newer_manual_action")
                    else:
                        _terminal(row, "failed", now, "conversation_missing")
                        row.error_code = "conversation_missing"
                        row.error_message = "The conversation no longer exists"
                else:
                    await _stage_locked_operation(
                        db,
                        row=row,
                        email_ids=targets,
                        action_name="unarchive",
                        purpose="unarchive",
                        completion_state="returned",
                        status_detail="returning",
                        now=now,
                    )

        elif row.state == "pending_return":
            purpose = row.pending_action_purpose or "unarchive"
            actions = await _actions_for_purpose(db, row, purpose)
            if not actions:
                targets = [
                    email.id for email in eligible
                    if email.id in set(_ids(row.return_target_email_ids))
                ]
                if not targets:
                    completion = row.completion_state or "returned"
                    _terminal(row, completion, now, f"{completion}_original_placement")
                else:
                    if purpose == "unarchive":
                        manually_placed = await _newer_placement_email_ids_since_schedule(
                            db, row, conversation_ids
                        )
                        targets = [email_id for email_id in targets if email_id not in manually_placed]
                    if not targets:
                        _terminal(row, "dismissed", now, "newer_manual_action")
                        actions = []
                        await db.commit()
                    else:
                        row.return_target_email_ids = targets
                if targets:
                    await _stage_locked_operation(
                        db,
                        row=row,
                        email_ids=targets,
                        action_name=purpose,
                        purpose=purpose,
                        completion_state=row.completion_state or "returned",
                        status_detail=row.status_detail or "returning",
                        now=now,
                    )
                    actions = await _actions_for_purpose(db, row, purpose)
            if actions:
                if purpose == "archive":
                    row.archive_action_id = actions[0].id
                else:
                    row.return_action_id = actions[0].id
                states = {action.state for action in actions}
                if states.intersection(ACTIVE_MAIL_ACTION_STATES):
                    row.next_attempt_at = now + timedelta(seconds=15)
                elif states == {"applied"}:
                    if await _newer_placement_after_operation(db, actions):
                        _terminal(row, "dismissed", now, "newer_manual_action")
                    else:
                        completion = row.completion_state or "returned"
                        _terminal(row, completion, now, f"{completion}_original_placement")
                elif "failed" in states:
                    _operation_error(row, purpose, actions, now)
                elif states == {"cancelled"}:
                    _terminal(row, "dismissed", now, f"{purpose}_undone")
                else:
                    _terminal(row, "failed", now, f"{purpose}_partial_failure")

        if row.state in SNOOZE_ACTIVE_STATES:
            row.lease_token = None
            row.lease_expires_at = None
            row.updated_at = now
        await db.commit()
        user_id = row.user_id
        public_id = row.public_id
    await _publish_snooze_event(user_id, public_id)


async def drain_due_snoozes() -> int:
    claimed = await _claim_due(utcnow(), SNOOZE_DRAIN_LIMIT)
    for row_id, token in claimed:
        try:
            await _process_claim(row_id, token, utcnow())
        except Exception:
            logger.exception("Snooze drain failed for row %s", row_id)
    return len(claimed)


async def _publish_snooze_event(user_id: int, public_id: UUID) -> None:
    try:
        from backend.services.notifications import publish_event

        await asyncio.wait_for(
            publish_event(user_id, "snooze_updated", {"id": str(public_id)}),
            timeout=SNOOZE_REDIS_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Could not publish snooze update", exc_info=False)


async def try_enqueue_snooze_drain() -> None:
    try:
        await asyncio.wait_for(_enqueue_snooze_drain(), timeout=SNOOZE_REDIS_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Could not enqueue snooze drain; cron will recover it", exc_info=False)


async def _enqueue_snooze_drain() -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job("drain_snoozes_task", _queue_name=SNOOZE_QUEUE_NAME)
    finally:
        await redis.close()
