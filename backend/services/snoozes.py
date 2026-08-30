"""PostgreSQL-authoritative universal email snoozes.

Redis only wakes the drainer. Gmail placement changes are always represented by
the existing ordered, undo-capable mail-action outbox, so sync and manual user
intent share one serialization boundary.
"""

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
from backend.models.account import GoogleAccount
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
    get_mail_action_operation_by_idempotency,
    retry_mail_action_operation,
    stage_mail_actions,
    try_enqueue_mail_action_drain,
)


logger = logging.getLogger(__name__)

SNOOZE_QUEUE_NAME = "arq:cron"
SNOOZE_LEASE_SECONDS = 120
SNOOZE_DRAIN_LIMIT = 50
SNOOZE_REDIS_TIMEOUT_SECONDS = 1.0
SNOOZE_ACTION_NAMESPACE = UUID("a30fa772-271d-54fa-8918-a171a39c5192")
PLACEMENT_ACTIONS = {"archive", "unarchive", "trash", "untrash", "spam", "unspam"}


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
        # PostgreSQL cannot lock the nullable joined rows from eager outer joins.
        statement = select(EmailSnooze).where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.public_id == public_id,
        ).with_for_update()
    result = await db.execute(statement)
    row = result.scalar_one_or_none()
    if row is None:
        raise SnoozeNotFound("Snooze not found")
    return row


async def _reload(db: AsyncSession, row_id: int) -> EmailSnooze:
    result = await db.execute(_loaded_query().where(EmailSnooze.id == row_id))
    return result.scalar_one()


async def create_snooze(
    db: AsyncSession,
    *,
    user_id: int,
    request: SnoozeCreateRequest,
    now: datetime | None = None,
) -> tuple[SnoozeResponse, bool]:
    accepted_at = now or utcnow()
    wake_at = request.wake_at.astimezone(timezone.utc)
    if wake_at <= accepted_at:
        raise SnoozeValidationError("wake_at must be in the future")

    payload_hash = _payload_hash(request)
    await _lock_idempotency(db, user_id=user_id, key=request.idempotency_key)
    existing_result = await db.execute(
        select(EmailSnooze).where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.idempotency_key == request.idempotency_key,
        ).with_for_update()
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise SnoozeConflict("Idempotency key was already used for another snooze")
        return _response(await _reload(db, existing.id)), False

    email_result = await db.execute(
        select(Email, GoogleAccount)
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .where(Email.id == request.email_id, GoogleAccount.user_id == user_id)
        .with_for_update(of=Email)
    )
    owned = email_result.one_or_none()
    if owned is None:
        raise SnoozeNotFound("Email not found")
    email, account = owned
    if email.is_trash or email.is_spam:
        raise SnoozeConflict("Trash and spam cannot be snoozed")
    if email.is_draft:
        raise SnoozeConflict("Drafts cannot be snoozed")

    active = await db.scalar(
        select(EmailSnooze.id).where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.email_id == email.id,
            EmailSnooze.state.in_(SNOOZE_ACTIVE_STATES),
        ).limit(1)
    )
    if active is not None:
        raise SnoozeConflict("This email is already snoozed")

    public_id = uuid4()
    archive_required = "INBOX" in set(email.labels or [])
    row = EmailSnooze(
        public_id=public_id,
        idempotency_key=request.idempotency_key,
        payload_hash=payload_hash,
        user_id=user_id,
        account_id=account.id,
        email_id=email.id,
        gmail_message_id=email.gmail_message_id,
        gmail_thread_id=email.gmail_thread_id,
        wake_at=wake_at,
        time_zone=request.time_zone,
        condition=request.condition,
        state="pending_archive" if archive_required else "scheduled",
        status_detail="archiving" if archive_required else "scheduled",
        archive_required=archive_required,
        anchor_date=email.date or accepted_at,
        mail_action_version_at_schedule=int(email.mail_action_version or 0),
        archive_idempotency_key=_action_key(public_id, "archive"),
        return_idempotency_key=_action_key(public_id, "return"),
        next_attempt_at=accepted_at if archive_required else wake_at,
        created_at=accepted_at,
        updated_at=accepted_at,
        scheduled_at=accepted_at if not archive_required else None,
    )
    db.add(row)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise SnoozeConflict("This email is already snoozed") from exc

    # Make inbox removal immediate. If this best-effort staging is interrupted,
    # the durable pending_archive row lets the cron drainer reconcile the same
    # deterministic mail-action idempotency key.
    if archive_required:
        try:
            await _ensure_action(row.id, purpose="archive", now=accepted_at)
        except Exception:
            logger.warning("Immediate snooze archive staging failed; cron will recover", exc_info=True)

    await _publish_snooze_event(user_id, public_id)
    refreshed = await _reload(db, row.id)
    return _response(refreshed), True


async def get_snooze(
    db: AsyncSession, *, user_id: int, public_id: UUID
) -> SnoozeResponse:
    return _response(await _owned_snooze(db, user_id=user_id, public_id=public_id))


async def get_snooze_by_idempotency(
    db: AsyncSession, *, user_id: int, idempotency_key: UUID
) -> SnoozeResponse:
    result = await db.execute(
        _loaded_query().where(
            EmailSnooze.user_id == user_id,
            EmailSnooze.idempotency_key == idempotency_key,
        )
    )
    row = result.scalar_one_or_none()
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
    elif state == "scheduled":
        filters.append(EmailSnooze.state == "scheduled")
    elif state == "cancelled":
        filters.append(EmailSnooze.state.in_(("cancelled", "dismissed")))
    elif state != "all":
        filters.append(EmailSnooze.state == state)

    total = int(await db.scalar(select(func.count()).select_from(EmailSnooze).where(*filters)) or 0)
    result = await db.execute(
        _loaded_query()
        .where(*filters)
        .order_by(EmailSnooze.wake_at, EmailSnooze.id)
        .limit(limit)
        .offset(offset)
    )
    rows = list(result.scalars().unique().all())
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
    if row.lease_token is not None and row.lease_expires_at and row.lease_expires_at > changed_at:
        raise SnoozeConflict("Snooze is currently being processed")
    row.wake_at = wake_at
    row.time_zone = time_zone
    if row.state == "scheduled":
        row.next_attempt_at = wake_at
    row.updated_at = changed_at
    await db.commit()
    await _publish_snooze_event(user_id, public_id)
    return _response(await _reload(db, row.id))


async def cancel_snooze(
    db: AsyncSession,
    *,
    user_id: int,
    public_id: UUID,
    now: datetime | None = None,
) -> SnoozeResponse:
    changed_at = now or utcnow()
    row = await _owned_snooze(
        db, user_id=user_id, public_id=public_id, for_update=True
    )
    if row.state in ("cancelled", "dismissed", "failed", "returned"):
        return _response(await _reload(db, row.id))
    email = await db.get(Email, row.email_id, with_for_update=True) if row.email_id else None
    active_return = None
    if row.return_action_id is not None:
        candidate = await db.get(MailAction, row.return_action_id)
        if candidate is not None and candidate.state in ACTIVE_MAIL_ACTION_STATES:
            active_return = candidate
    should_stage_return = False
    if email is None:
        _fail(row, changed_at, "email_missing", "The email no longer exists")
    elif email.is_trash or email.is_spam:
        _dismiss(row, changed_at, "protected_mailbox")
    elif "INBOX" in set(email.labels or []) and active_return is None:
        row.state = "cancelled"
        row.status_detail = "cancelled"
        row.cancelled_at = changed_at
        row.next_attempt_at = None
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = changed_at
    else:
        # A cancellation must not strand a message that the snooze archived.
        # Keep lifecycle authority until the deterministic return action applies.
        row.state = "pending_return"
        row.status_detail = "cancelling"
        row.next_attempt_at = changed_at
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = changed_at
        should_stage_return = active_return is None
    await db.commit()
    if should_stage_return:
        try:
            await _ensure_action(
                row.id, purpose="return", now=changed_at, retry_failed=True
            )
        except Exception:
            logger.warning("Immediate snooze cancellation return failed; cron will recover", exc_info=True)
    await _publish_snooze_event(user_id, public_id)
    return _response(await _reload(db, row.id))


async def return_snooze_now(
    db: AsyncSession,
    *,
    user_id: int,
    public_id: UUID,
    now: datetime | None = None,
) -> SnoozeResponse:
    changed_at = now or utcnow()
    row = await _owned_snooze(
        db, user_id=user_id, public_id=public_id, for_update=True
    )
    if row.state == "returned":
        return _response(await _reload(db, row.id))
    if row.state in ("dismissed", "failed"):
        raise SnoozeConflict("This snooze can no longer return the email")
    if row.state == "pending_return" and row.return_action_id is not None:
        return_action = await db.get(MailAction, row.return_action_id)
        if return_action is None or return_action.state != "failed":
            return _response(await _reload(db, row.id))
    email = await db.get(Email, row.email_id, with_for_update=True) if row.email_id else None
    if email is None:
        _fail(row, changed_at, "email_missing", "The email no longer exists")
    elif email.is_trash or email.is_spam:
        _dismiss(row, changed_at, "protected_mailbox")
    elif "INBOX" in set(email.labels or []):
        _returned(row, changed_at, "returned_now")
    else:
        row.state = "pending_return"
        row.status_detail = "returning_now"
        row.next_attempt_at = changed_at
        row.lease_token = None
        row.lease_expires_at = None
        row.updated_at = changed_at
    await db.commit()
    if row.state == "pending_return":
        try:
            await _ensure_action(
                row.id, purpose="return", now=changed_at, retry_failed=True
            )
        except Exception:
            logger.warning("Immediate snooze return staging failed; cron will recover", exc_info=True)
    await _publish_snooze_event(user_id, public_id)
    return _response(await _reload(db, row.id))


def _returned(row: EmailSnooze, now: datetime, detail: str) -> None:
    row.state = "returned"
    row.status_detail = detail
    row.returned_at = now
    row.next_attempt_at = None
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = now


def _dismiss(row: EmailSnooze, now: datetime, detail: str) -> None:
    row.state = "dismissed"
    row.status_detail = detail
    row.dismissed_at = now
    row.next_attempt_at = None
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = now


def _fail(row: EmailSnooze, now: datetime, code: str, message: str) -> None:
    row.state = "failed"
    row.status_detail = "failed"
    row.error_code = code
    row.error_message = message
    row.failed_at = now
    row.next_attempt_at = None
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = now


async def _lookup_action(
    db: AsyncSession, *, user_id: int, key: UUID
) -> MailAction | None:
    try:
        actions = await get_mail_action_operation_by_idempotency(
            db, user_id=user_id, idempotency_key=key
        )
    except MailActionNotFound:
        return None
    return actions[0]


async def _ensure_action(
    row_id: int,
    *,
    purpose: str,
    now: datetime,
    retry_failed: bool = False,
) -> None:
    """Reconcile or stage one deterministic action, then persist its linkage."""
    compensate_cancelled_archive = False
    async with async_session() as db:
        row = await db.get(EmailSnooze, row_id)
        if row is None or row.email_id is None:
            return
        key = row.archive_idempotency_key if purpose == "archive" else row.return_idempotency_key
        action = await _lookup_action(db, user_id=row.user_id, key=key)
        if action is not None and action.state == "failed" and retry_failed:
            await retry_mail_action_operation(
                db,
                user_id=row.user_id,
                request_id=action.request_id,
                now=now,
            )
            await db.refresh(action)
        if action is None:
            action_name = "archive" if purpose == "archive" else "unarchive"
            try:
                actions, _created = await stage_mail_actions(
                    db,
                    user_id=row.user_id,
                    email_ids=[row.email_id],
                    action=action_name,
                    idempotency_key=key,
                    now=now,
                )
            except MailActionConflict:
                action = await _lookup_action(db, user_id=row.user_id, key=key)
                if action is None:
                    raise
            else:
                action = actions[0]

        row = await db.get(EmailSnooze, row_id, with_for_update=True)
        if row is None:
            return
        if purpose == "archive" and row.archive_action_id is None:
            row.archive_action_id = action.id
            compensate_cancelled_archive = row.state in ("cancelled", "returned")
            if row.state == "cancelled":
                row.state = "pending_return"
                row.status_detail = "cancelling"
                row.cancelled_at = None
            elif row.state == "returned":
                row.state = "pending_return"
                row.status_detail = "returning_now"
                row.returned_at = None
        elif purpose == "return" and row.return_action_id is None:
            row.return_action_id = action.id
            if row.state not in ("returned", "cancelled", "dismissed", "failed"):
                row.state = "pending_return"
                if row.status_detail not in ("cancelling", "returning_now"):
                    row.status_detail = "returning"
        if row.state in SNOOZE_ACTIVE_STATES:
            row.next_attempt_at = max(now + timedelta(seconds=1), action.execute_after)
        row.updated_at = now
        await db.commit()
    await try_enqueue_mail_action_drain()
    if compensate_cancelled_archive:
        # Cancellation/Undo may have won after the durable snooze row was
        # accepted but before this archive operation was linked. Preserve that
        # newer intent with the ordered inverse action rather than orphaning
        # the message outside INBOX.
        await _ensure_action(row_id, purpose="return", now=now, retry_failed=True)


async def _has_reply(db: AsyncSession, row: EmailSnooze) -> bool:
    if row.anchor_date is None:
        return False
    return bool(await db.scalar(
        select(exists().where(
            Email.account_id == row.account_id,
            Email.gmail_thread_id == row.gmail_thread_id,
            Email.id != row.email_id,
            Email.date > row.anchor_date,
            Email.is_sent.is_(False),
            Email.is_draft.is_(False),
            Email.is_trash.is_(False),
            Email.is_spam.is_(False),
        ))
    ))


async def _newer_manual_placement(
    db: AsyncSession, row: EmailSnooze
) -> MailAction | None:
    if row.archive_action_id is None:
        base_sequence = row.mail_action_version_at_schedule
    else:
        archive = await db.get(MailAction, row.archive_action_id)
        base_sequence = archive.sequence if archive is not None else row.mail_action_version_at_schedule
    if row.email_id is None:
        return None
    result = await db.execute(
        select(MailAction)
        .where(
            MailAction.email_id == row.email_id,
            MailAction.sequence > base_sequence,
            MailAction.id != row.return_action_id,
            MailAction.action.in_(PLACEMENT_ACTIONS),
            MailAction.state.in_((*ACTIVE_MAIL_ACTION_STATES, "applied")),
        )
        .order_by(MailAction.sequence.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _claim_due(now: datetime, limit: int) -> list[tuple[int, UUID]]:
    async with async_session() as db:
        due = or_(
            (EmailSnooze.state == "scheduled") & (EmailSnooze.wake_at <= now),
            (EmailSnooze.state.in_(("pending_archive", "pending_return")))
            & (EmailSnooze.next_attempt_at <= now),
        )
        result = await db.execute(
            select(EmailSnooze)
            .where(
                EmailSnooze.state.in_(SNOOZE_ACTIVE_STATES),
                due,
                or_(EmailSnooze.lease_token.is_(None), EmailSnooze.lease_expires_at <= now),
            )
            .order_by(EmailSnooze.next_attempt_at, EmailSnooze.wake_at, EmailSnooze.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claimed = []
        for row in result.scalars().all():
            token = uuid4()
            row.lease_token = token
            row.lease_expires_at = now + timedelta(seconds=SNOOZE_LEASE_SECONDS)
            row.attempt_count += 1
            row.updated_at = now
            claimed.append((row.id, token))
        await db.commit()
        return claimed


async def _process_claim(row_id: int, token: UUID, now: datetime) -> None:
    stage_purpose: str | None = None
    async with async_session() as db:
        result = await db.execute(
            select(EmailSnooze)
            .where(EmailSnooze.id == row_id, EmailSnooze.lease_token == token)
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            return
        email = await db.get(Email, row.email_id, with_for_update=True) if row.email_id else None
        if email is None:
            _fail(row, now, "email_missing", "The email no longer exists")
        elif row.state == "pending_archive":
            action = await db.get(MailAction, row.archive_action_id) if row.archive_action_id else None
            if action is None:
                stage_purpose = "archive"
            elif action.state == "applied":
                row.state = "scheduled"
                row.status_detail = "scheduled"
                row.scheduled_at = now
                row.next_attempt_at = row.wake_at
            elif action.state == "cancelled":
                row.state = "cancelled"
                row.status_detail = "archive_undone"
                row.cancelled_at = now
                row.next_attempt_at = None
            elif action.state == "failed":
                row.status_detail = "archive_failed"
                row.error_code = "archive_failed"
                row.error_message = action.error_message or "Gmail archive failed"
                row.next_attempt_at = now + timedelta(minutes=5)
            else:
                row.next_attempt_at = now + timedelta(seconds=15)
        elif row.state == "scheduled":
            if email.is_trash or email.is_spam:
                _dismiss(row, now, "protected_mailbox")
            elif "INBOX" in set(email.labels or []):
                _returned(row, now, "already_in_inbox")
            elif await _newer_manual_placement(db, row):
                _dismiss(row, now, "newer_manual_action")
            elif row.condition == "if_no_reply" and await _has_reply(db, row):
                _dismiss(row, now, "reply_received")
            else:
                row.state = "pending_return"
                row.status_detail = "returning"
                row.next_attempt_at = now
                stage_purpose = "return"
        elif row.state == "pending_return":
            if email.is_trash or email.is_spam:
                _dismiss(row, now, "protected_mailbox")
            elif row.return_action_id is None:
                stage_purpose = "return"
            else:
                action = await db.get(MailAction, row.return_action_id)
                if action is None:
                    stage_purpose = "return"
                elif action.state == "applied":
                    if await _newer_manual_placement(db, row):
                        _dismiss(row, now, "newer_manual_action")
                    elif row.status_detail == "cancelling":
                        row.state = "cancelled"
                        row.status_detail = "cancelled"
                        row.cancelled_at = now
                        row.next_attempt_at = None
                        row.lease_token = None
                        row.lease_expires_at = None
                        row.updated_at = now
                    else:
                        _returned(row, now, "returned_to_inbox")
                elif action.state == "failed":
                    row.status_detail = "return_failed"
                    row.error_code = "return_failed"
                    row.error_message = action.error_message or "Gmail return failed"
                    row.next_attempt_at = now + timedelta(minutes=5)
                elif action.state == "cancelled":
                    _dismiss(row, now, "return_undone")
                else:
                    row.next_attempt_at = now + timedelta(seconds=15)

        if row.state in SNOOZE_ACTIVE_STATES:
            row.lease_token = None
            row.lease_expires_at = None
            row.updated_at = now
        await db.commit()
        user_id = row.user_id
        public_id = row.public_id

    if stage_purpose:
        await _ensure_action(row_id, purpose=stage_purpose, now=now)
    await _publish_snooze_event(user_id, public_id)


async def drain_due_snoozes() -> int:
    now = utcnow()
    claimed = await _claim_due(now, SNOOZE_DRAIN_LIMIT)
    processed = 0
    for row_id, token in claimed:
        try:
            await _process_claim(row_id, token, utcnow())
        except Exception:
            logger.exception("Snooze drain failed for row %s", row_id)
        processed += 1
    return processed


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
