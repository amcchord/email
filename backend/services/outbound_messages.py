"""Durable, at-most-once outbound email delivery.

PostgreSQL is the source of truth. Redis only wakes the drainer sooner. Every
provider attempt is durably marked before Gmail is called; after that point an
ambiguous outcome may only be reconciled by the stable RFC Message-ID and is
never replayed automatically.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import async_session
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.outbound_message import OutboundMessage
from backend.schemas.email import ComposeRequest
from backend.services.account_lock import account_advisory_lock
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService
from backend.utils.security import encrypt_value


logger = logging.getLogger(__name__)

OUTBOUND_QUEUE_NAME = "arq:cron"
OUTBOUND_UNDO_SECONDS = 10
OUTBOUND_SCHEDULE_MIN_SECONDS = 60
OUTBOUND_SCHEDULE_MAX_DAYS = 365
OUTBOUND_LINKED_DRAFT_HOLD_DAYS = 7
OUTBOUND_LEASE_SECONDS = 120
OUTBOUND_MAX_ATTEMPTS = 8
OUTBOUND_RECONCILE_MAX_CHECKS = 8
OUTBOUND_DRAIN_MAX_MESSAGES = 8
OUTBOUND_GMAIL_TRANSPORT_TIMEOUT_SECONDS = 30.0
OUTBOUND_REDIS_IO_TIMEOUT_SECONDS = 1.0
OUTBOUND_RFC_MESSAGE_ID_DOMAIN = "email.mcchord.net"
OUTBOUND_CAPACITY_STATES = ("staged", "processing", "retry_wait", "reconciling")
OUTBOUND_USER_ACTIVE_LIMIT = 60
OUTBOUND_ACCOUNT_ACTIVE_LIMIT = 30
OUTBOUND_ACCEPTANCE_WINDOW_SECONDS = 60
OUTBOUND_USER_RECENT_LIMIT = 40
OUTBOUND_ACCOUNT_RECENT_LIMIT = 20
OUTBOUND_ACTIVE_RETRY_AFTER_SECONDS = 30
OUTBOUND_RETRY_PAYLOAD_RETENTION_SECONDS = 60 * 60


class OutboundMessageError(RuntimeError):
    """Base class for safe API-facing outbound errors."""


class OutboundMessageNotFound(OutboundMessageError):
    pass


class OutboundMessageConflict(OutboundMessageError):
    pass


class OutboundMessageValidationError(OutboundMessageError):
    pass


class OutboundMessageQuotaExceeded(OutboundMessageError):
    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = max(1, retry_after_seconds)


class OutboundMessagePersistenceError(OutboundMessageError):
    pass


@dataclass(frozen=True)
class OutboundErrorDisposition:
    retryable: bool
    code: str
    message: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_payload(request: ComposeRequest) -> dict:
    return request.model_dump(mode="json", exclude={"idempotency_key", "is_draft"})


def outbound_payload_hash(request: ComposeRequest) -> str:
    serialized = json.dumps(
        _canonical_payload(request),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def outbound_scheduled_for(outbound: OutboundMessage) -> datetime | None:
    payload = outbound.payload if isinstance(outbound.payload, dict) else {}
    value = payload.get("scheduled_for")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    if outbound.execute_after > outbound.undo_until:
        return outbound.execute_after
    return None


def outbound_schedule_timezone(outbound: OutboundMessage) -> str | None:
    payload = outbound.payload if isinstance(outbound.payload, dict) else {}
    value = payload.get("schedule_timezone")
    return value if isinstance(value, str) and value else None


def outbound_is_scheduled(outbound: OutboundMessage) -> bool:
    return outbound_scheduled_for(outbound) is not None


def outbound_archives_source_after_send(outbound: OutboundMessage) -> bool:
    """Expose only the safe, active archive intent—not the retained payload."""
    payload = outbound.payload if isinstance(outbound.payload, dict) else {}
    return (
        payload.get("archive_source_after_send") is True
        and isinstance(outbound.source_email_id, int)
        and outbound.source_email_id > 0
    )


async def _ensure_post_send_archive(outbound: OutboundMessage) -> bool:
    """Durably stage post-send archive intent before terminal send truth.

    The deterministic mail-action key makes a crash between staging the action
    and marking the outbound sent harmless: provider reconciliation repeats
    this lookup without creating a second mailbox mutation.
    """
    payload = outbound.payload if isinstance(outbound.payload, dict) else {}
    if payload.get("archive_source_after_send") is not True:
        return True
    source_email_id = outbound.source_email_id
    if not isinstance(source_email_id, int) or source_email_id <= 0:
        # Gmail history may remove the validated source before a scheduled
        # delivery. The FK then becomes NULL, while the immutable retained
        # intent still carries the admission-validated source identifier.
        source_email_id = payload.get("source_email_id")
    if not isinstance(source_email_id, int) or source_email_id <= 0:
        logger.error("Outbound post-send archive is missing a validated source email")
        return False

    from backend.services.mail_actions import (
        MailActionNotFound,
        stage_mail_actions,
        try_enqueue_mail_action_drain,
    )

    action_key = uuid5(NAMESPACE_URL, f"mail-outbound:{outbound.send_id}:archive-source")
    try:
        async with async_session() as db:
            _actions, created = await stage_mail_actions(
                db,
                user_id=outbound.user_id,
                email_ids=[source_email_id],
                action="archive",
                idempotency_key=action_key,
                scope="conversations",
            )
    except MailActionNotFound:
        # The exact source was validated at send admission. If it has since
        # been removed, there is no remaining local inbox row to archive.
        return True
    except Exception:
        logger.warning(
            "Could not durably stage post-send archive; outbound reconciliation will retry",
            exc_info=True,
        )
        return False
    if created:
        await try_enqueue_mail_action_drain()
    return True


def _idempotency_advisory_key(user_id: int, idempotency_key: UUID) -> int:
    digest = hashlib.sha256(f"outbound:{user_id}:{idempotency_key}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _acceptance_advisory_key(user_id: int) -> int:
    digest = hashlib.sha256(f"outbound-acceptance:{user_id}".encode("ascii")).digest()
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


async def _lock_user_acceptance(
    db: AsyncSession,
    *,
    user_id: int,
) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _acceptance_advisory_key(user_id)},
    )


async def _owned_outbound_by_idempotency(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: UUID,
    for_update: bool = False,
) -> OutboundMessage | None:
    statement = select(OutboundMessage).where(
        OutboundMessage.user_id == user_id,
        OutboundMessage.idempotency_key == idempotency_key,
    )
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


def _outbound_consumes_capacity(*, now: datetime):
    return or_(
        OutboundMessage.state.in_(OUTBOUND_CAPACITY_STATES),
        and_(
            OutboundMessage.retry_authorized.is_(True),
            OutboundMessage.retry_expires_at > now,
        ),
    )


async def _active_outbound_count(
    db: AsyncSession,
    *,
    now: datetime,
    user_id: int | None = None,
    account_id: int | None = None,
) -> int:
    statement = select(func.count(OutboundMessage.id)).where(
        _outbound_consumes_capacity(now=now)
    )
    if user_id is not None:
        statement = statement.where(OutboundMessage.user_id == user_id)
    if account_id is not None:
        statement = statement.where(OutboundMessage.account_id == account_id)
    return int((await db.execute(statement)).scalar_one())


async def _scrub_expired_retry_payloads(
    db: AsyncSession,
    *,
    now: datetime,
    user_id: int | None = None,
) -> list[tuple[int, UUID]]:
    statement = (
        update(OutboundMessage)
        .where(
            OutboundMessage.state == "failed",
            OutboundMessage.retry_authorized.is_(True),
            OutboundMessage.retry_expires_at <= now,
        )
        .values(
            payload=None,
            retry_authorized=False,
            retry_expires_at=None,
            updated_at=now,
        )
        .returning(OutboundMessage.user_id, OutboundMessage.send_id)
    )
    if user_id is not None:
        statement = statement.where(OutboundMessage.user_id == user_id)
    result = await db.execute(statement)
    return [(row.user_id, row.send_id) for row in result]


async def scrub_expired_retry_payloads(*, now: datetime | None = None) -> int:
    current = now or utcnow()
    async with async_session() as db:
        notifications = await _scrub_expired_retry_payloads(db, now=current)
        await db.commit()
    for user_id, send_id in notifications:
        await _publish_outbound_event(user_id, send_id)
    return len(notifications)


async def _recent_acceptance_retry_after(
    db: AsyncSession,
    *,
    accepted_at: datetime,
    limit: int,
    user_id: int | None = None,
    account_id: int | None = None,
) -> int | None:
    cutoff = accepted_at - timedelta(seconds=OUTBOUND_ACCEPTANCE_WINDOW_SECONDS)
    statement = select(OutboundMessage.created_at).where(OutboundMessage.created_at >= cutoff)
    if user_id is not None:
        statement = statement.where(OutboundMessage.user_id == user_id)
    if account_id is not None:
        statement = statement.where(OutboundMessage.account_id == account_id)
    threshold_time = (
        await db.execute(
            statement
            .order_by(OutboundMessage.created_at.desc(), OutboundMessage.id.desc())
            .offset(limit - 1)
            .limit(1)
        )
    ).scalar_one_or_none()
    if threshold_time is None:
        return None
    retry_at = threshold_time + timedelta(seconds=OUTBOUND_ACCEPTANCE_WINDOW_SECONDS)
    return max(1, math.ceil((retry_at - accepted_at).total_seconds()))


async def _enforce_acceptance_quotas(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    accepted_at: datetime,
) -> None:
    account_active = await _active_outbound_count(
        db,
        now=accepted_at,
        account_id=account_id,
    )
    if account_active >= OUTBOUND_ACCOUNT_ACTIVE_LIMIT:
        raise OutboundMessageQuotaExceeded(
            "Too many sends are awaiting delivery. Try again shortly.",
            retry_after_seconds=OUTBOUND_ACTIVE_RETRY_AFTER_SECONDS,
        )

    user_active = await _active_outbound_count(
        db,
        now=accepted_at,
        user_id=user_id,
    )
    if user_active >= OUTBOUND_USER_ACTIVE_LIMIT:
        raise OutboundMessageQuotaExceeded(
            "Too many sends are awaiting delivery. Try again shortly.",
            retry_after_seconds=OUTBOUND_ACTIVE_RETRY_AFTER_SECONDS,
        )

    account_retry_after = await _recent_acceptance_retry_after(
        db,
        accepted_at=accepted_at,
        limit=OUTBOUND_ACCOUNT_RECENT_LIMIT,
        account_id=account_id,
    )
    if account_retry_after is not None:
        raise OutboundMessageQuotaExceeded(
            "Too many sends were accepted recently. Try again shortly.",
            retry_after_seconds=account_retry_after,
        )

    user_retry_after = await _recent_acceptance_retry_after(
        db,
        accepted_at=accepted_at,
        limit=OUTBOUND_USER_RECENT_LIMIT,
        user_id=user_id,
    )
    if user_retry_after is not None:
        raise OutboundMessageQuotaExceeded(
            "Too many sends were accepted recently. Try again shortly.",
            retry_after_seconds=user_retry_after,
        )


def _expected_reply_references(source: Email) -> str:
    existing = (source.references_header or "").strip()
    parts = existing.split() if existing else []
    message_id = (source.message_id_header or "").strip()
    if message_id and message_id not in parts:
        parts.append(message_id)
    return " ".join(parts)


async def _validate_reply_provenance(
    db: AsyncSession,
    *,
    account_id: int,
    request: ComposeRequest,
) -> None:
    has_reply_metadata = any((request.thread_id, request.in_reply_to, request.references))
    if has_reply_metadata and request.source_email_id is None:
        raise OutboundMessageValidationError("Reply source is required")
    if request.source_email_id is None:
        return

    source = (
        await db.execute(
            select(Email).where(
                Email.id == request.source_email_id,
                Email.account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        # Keep foreign and nonexistent source IDs indistinguishable.
        raise OutboundMessageNotFound("Reply source not found")

    expected_message_id = (source.message_id_header or "").strip() or None
    expected_references = _expected_reply_references(source) or None
    if (
        not has_reply_metadata
        or request.thread_id != source.gmail_thread_id
        or request.in_reply_to != expected_message_id
        or request.references != expected_references
    ):
        raise OutboundMessageNotFound("Reply source not found")


async def stage_outbound_message(
    db: AsyncSession,
    *,
    user_id: int,
    request: ComposeRequest,
    now: datetime | None = None,
) -> tuple[OutboundMessage, bool]:
    """Accept one fully validated send intent without exposing persistence errors."""
    try:
        return await _stage_outbound_message(
            db,
            user_id=user_id,
            request=request,
            now=now,
        )
    except OutboundMessageError:
        await _safe_staging_rollback(db)
        raise
    except Exception as error:
        await _safe_staging_rollback(db)
        logger.error(
            "Outbound staging failed safely; exception_type=%s",
            type(error).__name__,
        )
        raise OutboundMessagePersistenceError(
            "Send could not be accepted right now"
        ) from None


async def _safe_staging_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception as error:
        logger.error(
            "Outbound staging rollback failed; exception_type=%s",
            type(error).__name__,
        )


async def _stage_outbound_message(
    db: AsyncSession,
    *,
    user_id: int,
    request: ComposeRequest,
    now: datetime | None = None,
) -> tuple[OutboundMessage, bool]:
    """Accept one fully validated send intent atomically."""
    payload_hash = outbound_payload_hash(request)
    await _lock_idempotency_key(
        db,
        user_id=user_id,
        idempotency_key=request.idempotency_key,
    )

    existing = await _owned_outbound_by_idempotency(
        db,
        user_id=user_id,
        idempotency_key=request.idempotency_key,
        for_update=True,
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise OutboundMessageConflict("Idempotency key was already used for another payload")
        await db.commit()
        return existing, False

    await _lock_user_acceptance(db, user_id=user_id)

    account = (
        await db.execute(
            select(GoogleAccount)
            .where(
                GoogleAccount.id == request.account_id,
                GoogleAccount.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if account is None:
        raise OutboundMessageNotFound("Account not found")
    if not account.is_active:
        raise OutboundMessageValidationError("Account is inactive")

    await _validate_reply_provenance(
        db,
        account_id=account.id,
        request=request,
    )

    accepted_at = now or utcnow()
    undo_until = accepted_at + timedelta(seconds=OUTBOUND_UNDO_SECONDS)
    execute_after = undo_until
    if request.scheduled_for is not None:
        earliest = accepted_at + timedelta(seconds=OUTBOUND_SCHEDULE_MIN_SECONDS)
        latest = accepted_at + timedelta(days=OUTBOUND_SCHEDULE_MAX_DAYS)
        if request.scheduled_for < earliest:
            raise OutboundMessageValidationError(
                "Scheduled delivery must be at least one minute in the future"
            )
        if request.scheduled_for > latest:
            raise OutboundMessageValidationError(
                "Scheduled delivery cannot be more than one year in the future"
            )
        execute_after = request.scheduled_for
    expired_notifications = await _scrub_expired_retry_payloads(
        db,
        now=accepted_at,
        user_id=user_id,
    )
    await _enforce_acceptance_quotas(
        db,
        user_id=user_id,
        account_id=account.id,
        accepted_at=accepted_at,
    )
    send_id = uuid4()
    linked_draft = None
    if request.client_draft_id is not None:
        from backend.services.drafts import (
            DraftConflict,
            DraftNotFound,
            DraftValidationError,
            link_draft_for_outbound_send,
        )

        try:
            linked_draft = await link_draft_for_outbound_send(
                db,
                user_id=user_id,
                request=request,
                send_id=send_id,
                discard_at=(
                    execute_after + timedelta(days=OUTBOUND_LINKED_DRAFT_HOLD_DAYS)
                    if request.scheduled_for is not None
                    else undo_until
                ),
            )
        except DraftNotFound as error:
            raise OutboundMessageNotFound(str(error)) from error
        except DraftConflict as error:
            raise OutboundMessageConflict(str(error)) from error
        except DraftValidationError as error:
            raise OutboundMessageValidationError(str(error)) from error
    outbound = OutboundMessage(
        send_id=send_id,
        idempotency_key=request.idempotency_key,
        payload_hash=payload_hash,
        user_id=user_id,
        account_id=account.id,
        source_email_id=request.source_email_id,
        draft_session_id=linked_draft.id if linked_draft is not None else None,
        client_draft_id=request.client_draft_id,
        payload=_canonical_payload(request),
        retry_authorized=False,
        retry_expires_at=None,
        rfc_message_id=(
            linked_draft.rfc_message_id
            if linked_draft is not None
            else f"<mail-{send_id}@{OUTBOUND_RFC_MESSAGE_ID_DOMAIN}>"
        ),
        state="staged",
        execute_after=execute_after,
        undo_until=undo_until,
        next_attempt_at=execute_after,
        attempt_count=0,
        max_attempts=OUTBOUND_MAX_ATTEMPTS,
        reconcile_count=0,
        created_at=accepted_at,
        updated_at=accepted_at,
    )
    db.add(outbound)
    await db.flush()
    await db.commit()
    for expired_user_id, expired_send_id in expired_notifications:
        await _publish_outbound_event(expired_user_id, expired_send_id)
    await _publish_outbound_event(outbound.user_id, outbound.send_id)
    return outbound, True


async def get_outbound_message(
    db: AsyncSession,
    *,
    user_id: int,
    send_id: UUID,
    for_update: bool = False,
) -> OutboundMessage:
    statement = select(OutboundMessage).where(
        OutboundMessage.user_id == user_id,
        OutboundMessage.send_id == send_id,
    )
    if for_update:
        statement = statement.with_for_update()
    outbound = (await db.execute(statement)).scalar_one_or_none()
    if outbound is None:
        raise OutboundMessageNotFound("Send not found")
    return outbound


async def get_outbound_message_by_idempotency(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: UUID,
) -> OutboundMessage:
    outbound = await _owned_outbound_by_idempotency(
        db,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    if outbound is None:
        raise OutboundMessageNotFound("Send not found")
    return outbound


async def recent_outbound_messages(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 20,
) -> list[OutboundMessage]:
    result = await db.execute(
        select(OutboundMessage)
        .where(OutboundMessage.user_id == user_id)
        .order_by(OutboundMessage.created_at.desc(), OutboundMessage.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def scheduled_outbound_messages(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 60,
) -> list[OutboundMessage]:
    result = await db.execute(
        select(OutboundMessage)
        .where(
            OutboundMessage.user_id == user_id,
            OutboundMessage.state == "staged",
            OutboundMessage.execute_after > OutboundMessage.undo_until,
        )
        .order_by(OutboundMessage.execute_after, OutboundMessage.id)
        .limit(limit)
    )
    return list(result.scalars().all())


def outbound_can_undo(outbound: OutboundMessage, *, now: datetime | None = None) -> bool:
    current = now or utcnow()
    return outbound.state == "staged" and current <= outbound.undo_until


def outbound_can_cancel(outbound: OutboundMessage, *, now: datetime | None = None) -> bool:
    current = now or utcnow()
    return bool(
        outbound.state == "staged"
        and outbound_is_scheduled(outbound)
        and current < outbound.execute_after
    )


def outbound_can_retry(
    outbound: OutboundMessage,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or utcnow()
    return (
        outbound.state == "failed"
        and outbound.retry_authorized
        and outbound.retry_expires_at is not None
        and current < outbound.retry_expires_at
        and outbound.provider_attempted_at is None
        and outbound.payload is not None
    )


async def undo_outbound_message(
    db: AsyncSession,
    *,
    user_id: int,
    send_id: UUID,
    now: datetime | None = None,
) -> OutboundMessage:
    current = now or utcnow()
    outbound = await get_outbound_message(
        db,
        user_id=user_id,
        send_id=send_id,
        for_update=True,
    )
    if not outbound_can_undo(outbound, now=current):
        raise OutboundMessageConflict("Send can no longer be undone")
    outbound.state = "cancelled"
    outbound.payload = None
    outbound.retry_authorized = False
    outbound.retry_expires_at = None
    outbound.next_attempt_at = None
    outbound.cancelled_at = current
    outbound.updated_at = current
    outbound.error_code = None
    outbound.error_message = None
    linked_draft = None
    draft_session_id = getattr(outbound, "draft_session_id", None)
    if draft_session_id is not None:
        from backend.services.drafts import restore_linked_draft_after_outbound_cancel

        linked_draft = await restore_linked_draft_after_outbound_cancel(
            db,
            user_id=user_id,
            draft_session_id=draft_session_id,
            send_id=outbound.send_id,
            now=current,
        )
        if linked_draft is not None:
            # Release the unique draft-session reservation so the restored
            # writing session can own a later logical send.
            outbound.draft_session_id = None
    await db.commit()
    await _publish_outbound_event(outbound.user_id, outbound.send_id)
    if linked_draft is not None:
        from backend.services.drafts import publish_draft_session_event

        await publish_draft_session_event(linked_draft)
    return outbound


async def cancel_scheduled_outbound_message(
    db: AsyncSession,
    *,
    user_id: int,
    send_id: UUID,
    now: datetime | None = None,
) -> OutboundMessage:
    current = now or utcnow()
    outbound = await get_outbound_message(
        db,
        user_id=user_id,
        send_id=send_id,
        for_update=True,
    )
    if outbound.state == "cancelled" and outbound_is_scheduled(outbound):
        await db.commit()
        return outbound
    if not outbound_can_cancel(outbound, now=current):
        raise OutboundMessageConflict("Scheduled send can no longer be cancelled")
    outbound.state = "cancelled"
    outbound.payload = None
    outbound.retry_authorized = False
    outbound.retry_expires_at = None
    outbound.next_attempt_at = None
    outbound.cancelled_at = current
    outbound.updated_at = current
    outbound.error_code = None
    outbound.error_message = None
    linked_draft = None
    draft_session_id = getattr(outbound, "draft_session_id", None)
    if draft_session_id is not None:
        from backend.services.drafts import restore_linked_draft_after_outbound_cancel

        linked_draft = await restore_linked_draft_after_outbound_cancel(
            db,
            user_id=user_id,
            draft_session_id=draft_session_id,
            send_id=outbound.send_id,
            now=current,
        )
        if linked_draft is not None:
            outbound.draft_session_id = None
    await db.commit()
    await _publish_outbound_event(outbound.user_id, outbound.send_id)
    if linked_draft is not None:
        from backend.services.drafts import publish_draft_session_event

        await publish_draft_session_event(linked_draft)
    return outbound


async def send_scheduled_outbound_now(
    db: AsyncSession,
    *,
    user_id: int,
    send_id: UUID,
    now: datetime | None = None,
) -> OutboundMessage:
    current = now or utcnow()
    outbound = await get_outbound_message(
        db,
        user_id=user_id,
        send_id=send_id,
        for_update=True,
    )
    if not outbound_can_cancel(outbound, now=current):
        raise OutboundMessageConflict("Scheduled send can no longer be sent now")
    outbound.execute_after = current
    # Closing the Undo deadline at the same instant removes this operation
    # from the future-scheduled query without changing its staged/due state.
    outbound.undo_until = current
    outbound.next_attempt_at = current
    outbound.updated_at = current
    await db.commit()
    await _publish_outbound_event(outbound.user_id, outbound.send_id)
    return outbound


async def retry_outbound_message(
    db: AsyncSession,
    *,
    user_id: int,
    send_id: UUID,
    now: datetime | None = None,
) -> OutboundMessage:
    current = now or utcnow()
    outbound = await get_outbound_message(
        db,
        user_id=user_id,
        send_id=send_id,
        for_update=True,
    )
    if not outbound_can_retry(outbound, now=current):
        raise OutboundMessageConflict("Send cannot be retried safely")
    outbound.state = "retry_wait"
    outbound.retry_authorized = False
    outbound.retry_expires_at = None
    outbound.next_attempt_at = current
    outbound.attempt_count = 0
    outbound.failed_at = None
    outbound.error_code = None
    outbound.error_message = None
    outbound.updated_at = current
    await db.commit()
    await _publish_outbound_event(outbound.user_id, outbound.send_id)
    return outbound


def classify_outbound_preflight_error(exc: Exception) -> OutboundErrorDisposition:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    error_text = str(exc).lower()
    if status == 403 and any(token in error_text for token in ("quota", "rate", "limit")):
        return OutboundErrorDisposition(True, "gmail_rate_limit", "Gmail is temporarily unavailable")
    if status in {400, 401, 403, 404}:
        return OutboundErrorDisposition(False, "gmail_authorization", "The sending account needs attention")
    if status in {408, 409, 425, 429} or (isinstance(status, int) and status >= 500):
        return OutboundErrorDisposition(True, "gmail_unavailable", "Gmail is temporarily unavailable")
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return OutboundErrorDisposition(True, "gmail_transport", "Gmail is temporarily unavailable")
    return OutboundErrorDisposition(True, "gmail_unavailable", "Gmail is temporarily unavailable")


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(15 * (2 ** max(attempt_count - 1, 0)), 15 * 60))


def _reconcile_delay(reconcile_count: int) -> timedelta:
    return timedelta(seconds=min(30 * (2 ** max(reconcile_count - 1, 0)), 5 * 60))


def _fail_outbound(
    outbound: OutboundMessage,
    *,
    now: datetime,
    retry_authorized: bool,
) -> None:
    safe_retry = bool(
        retry_authorized
        and outbound.provider_attempted_at is None
        and outbound.payload is not None
    )
    outbound.state = "failed"
    outbound.next_attempt_at = None
    outbound.failed_at = now
    outbound.retry_authorized = safe_retry
    if safe_retry:
        outbound.retry_expires_at = now + timedelta(
            seconds=OUTBOUND_RETRY_PAYLOAD_RETENTION_SECONDS
        )
    else:
        outbound.payload = None
        outbound.retry_expires_at = None


async def _reclaim_expired_leases(
    db: AsyncSession,
    *,
    account_id: int,
    now: datetime,
) -> set[tuple[int, UUID]]:
    notifications: set[tuple[int, UUID]] = set()
    result = await db.execute(
        select(OutboundMessage)
        .where(
            OutboundMessage.account_id == account_id,
            OutboundMessage.state == "processing",
            OutboundMessage.lease_expires_at <= now,
        )
        .with_for_update(skip_locked=True)
    )
    for outbound in result.scalars().all():
        notifications.add((outbound.user_id, outbound.send_id))
        outbound.lease_token = None
        outbound.lease_expires_at = None
        outbound.updated_at = now
        outbound.next_attempt_at = now
        if outbound.provider_attempted_at is None:
            if outbound.attempt_count >= outbound.max_attempts:
                _fail_outbound(outbound, now=now, retry_authorized=True)
                outbound.error_code = "worker_unavailable"
                outbound.error_message = "Delivery could not be started"
            else:
                outbound.state = "retry_wait"
                outbound.retry_authorized = False
                outbound.retry_expires_at = None
                outbound.error_code = "worker_interrupted"
                outbound.error_message = "Delivery was delayed and will be retried"
        else:
            outbound.state = "reconciling"
            outbound.retry_authorized = False
            outbound.retry_expires_at = None
            outbound.error_code = "send_outcome_unknown"
            outbound.error_message = "Delivery is being confirmed with Gmail"
    return notifications


async def _claim_due_outbound(
    db: AsyncSession,
    *,
    account_id: int,
    now: datetime,
    limit: int,
) -> list[OutboundMessage]:
    notifications = await _reclaim_expired_leases(db, account_id=account_id, now=now)
    due = or_(
        and_(OutboundMessage.state == "staged", OutboundMessage.execute_after <= now),
        and_(
            OutboundMessage.state.in_(("retry_wait", "reconciling")),
            OutboundMessage.next_attempt_at <= now,
        ),
    )
    result = await db.execute(
        select(OutboundMessage)
        .where(OutboundMessage.account_id == account_id, due)
        .order_by(OutboundMessage.execute_after, OutboundMessage.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = list(result.scalars().all())
    lease_expires_at = now + timedelta(seconds=OUTBOUND_LEASE_SECONDS)
    for outbound in claimed:
        outbound.state = "processing"
        outbound.attempt_count += 1
        outbound.lease_token = uuid4()
        outbound.lease_expires_at = lease_expires_at
        outbound.processing_started_at = now
        outbound.next_attempt_at = None
        outbound.updated_at = now
    await db.commit()
    for user_id, send_id in notifications:
        await _publish_outbound_event(user_id, send_id)
    return claimed


async def _mark_provider_attempt_started(
    *,
    outbound_id: int,
    lease_token: UUID,
    now: datetime,
) -> bool:
    async with async_session() as db:
        result = await db.execute(
            update(OutboundMessage)
            .where(
                OutboundMessage.id == outbound_id,
                OutboundMessage.state == "processing",
                OutboundMessage.lease_token == lease_token,
                OutboundMessage.provider_attempted_at.is_(None),
            )
            .values(provider_attempted_at=now, updated_at=now)
            .returning(OutboundMessage.id)
        )
        marked = result.scalar_one_or_none() is not None
        await db.commit()
        return marked


async def _record_outbound_sent(
    *,
    outbound_id: int,
    lease_token: UUID,
    provider_message_id: str,
    now: datetime,
) -> bool:
    async with async_session() as db:
        outbound = (
            await db.execute(
                select(OutboundMessage)
                .where(
                    OutboundMessage.id == outbound_id,
                    OutboundMessage.state == "processing",
                    OutboundMessage.lease_token == lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if outbound is None:
            return False
        outbound.state = "sent"
        outbound.provider_message_id = provider_message_id
        outbound.payload = None
        outbound.retry_authorized = False
        outbound.retry_expires_at = None
        outbound.lease_token = None
        outbound.lease_expires_at = None
        outbound.next_attempt_at = None
        outbound.error_code = None
        outbound.error_message = None
        outbound.sent_at = now
        outbound.updated_at = now
        linked_draft = None
        draft_session_id = getattr(outbound, "draft_session_id", None)
        if draft_session_id is not None:
            from backend.services.drafts import prepare_linked_draft_for_outbound_discard

            linked_draft = await prepare_linked_draft_for_outbound_discard(
                db,
                user_id=outbound.user_id,
                draft_session_id=draft_session_id,
                send_id=outbound.send_id,
                now=now,
            )
        await db.commit()
        user_id, send_id = outbound.user_id, outbound.send_id
    await _publish_outbound_event(user_id, send_id)
    if linked_draft is not None:
        from backend.services.drafts import publish_draft_session_event, try_enqueue_draft_drain

        await publish_draft_session_event(linked_draft)
        await try_enqueue_draft_drain()
    return True


async def _record_preflight_failure(
    *,
    outbound_id: int,
    lease_token: UUID,
    disposition: OutboundErrorDisposition,
    now: datetime,
) -> bool:
    async with async_session() as db:
        outbound = (
            await db.execute(
                select(OutboundMessage)
                .where(
                    OutboundMessage.id == outbound_id,
                    OutboundMessage.state == "processing",
                    OutboundMessage.lease_token == lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if outbound is None:
            return False
        if outbound.provider_attempted_at is not None:
            return await _record_reconciling_locked(db, outbound=outbound, now=now)
        outbound.lease_token = None
        outbound.lease_expires_at = None
        outbound.error_code = disposition.code
        outbound.error_message = disposition.message
        outbound.updated_at = now
        linked_draft = None
        was_scheduled = outbound_is_scheduled(outbound)
        if disposition.retryable and outbound.attempt_count < outbound.max_attempts:
            outbound.state = "retry_wait"
            outbound.retry_authorized = False
            outbound.retry_expires_at = None
            outbound.next_attempt_at = now + _retry_delay(outbound.attempt_count)
        else:
            _fail_outbound(
                outbound,
                now=now,
                retry_authorized=(disposition.retryable and not was_scheduled),
            )
            draft_session_id = getattr(outbound, "draft_session_id", None)
            if draft_session_id is not None and was_scheduled:
                from backend.services.drafts import restore_linked_draft_after_outbound_cancel

                linked_draft = await restore_linked_draft_after_outbound_cancel(
                    db,
                    user_id=outbound.user_id,
                    draft_session_id=draft_session_id,
                    send_id=outbound.send_id,
                    now=now,
                )
                if linked_draft is not None:
                    outbound.draft_session_id = None
        await db.commit()
        user_id, send_id = outbound.user_id, outbound.send_id
    await _publish_outbound_event(user_id, send_id)
    if linked_draft is not None:
        from backend.services.drafts import publish_draft_session_event, try_enqueue_draft_drain

        await publish_draft_session_event(linked_draft)
        await try_enqueue_draft_drain()
    return True


async def _record_reconciling_locked(
    db: AsyncSession,
    *,
    outbound: OutboundMessage,
    now: datetime,
    provider_confirmed_absent: bool = False,
) -> bool:
    outbound.lease_token = None
    outbound.lease_expires_at = None
    outbound.reconcile_count += 1
    outbound.updated_at = now
    outbound.error_code = "send_outcome_unknown"
    outbound.error_message = "Delivery could not be confirmed automatically"
    linked_draft = None
    if provider_confirmed_absent and outbound.reconcile_count >= OUTBOUND_RECONCILE_MAX_CHECKS:
        _fail_outbound(outbound, now=now, retry_authorized=False)
        draft_session_id = getattr(outbound, "draft_session_id", None)
        if draft_session_id is not None:
            from backend.services.drafts import prepare_linked_draft_for_outbound_discard

            linked_draft = await prepare_linked_draft_for_outbound_discard(
                db,
                user_id=outbound.user_id,
                draft_session_id=draft_session_id,
                send_id=outbound.send_id,
                now=now,
            )
    else:
        outbound.state = "reconciling"
        outbound.retry_authorized = False
        outbound.retry_expires_at = None
        outbound.next_attempt_at = now + _reconcile_delay(outbound.reconcile_count)
    await db.commit()
    user_id, send_id = outbound.user_id, outbound.send_id
    await _publish_outbound_event(user_id, send_id)
    if linked_draft is not None:
        from backend.services.drafts import publish_draft_session_event, try_enqueue_draft_drain

        await publish_draft_session_event(linked_draft)
        await try_enqueue_draft_drain()
    return True


async def _record_reconciling(
    *,
    outbound_id: int,
    lease_token: UUID,
    now: datetime,
    provider_confirmed_absent: bool = False,
) -> bool:
    async with async_session() as db:
        outbound = (
            await db.execute(
                select(OutboundMessage)
                .where(
                    OutboundMessage.id == outbound_id,
                    OutboundMessage.state == "processing",
                    OutboundMessage.lease_token == lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if outbound is None:
            return False
        return await _record_reconciling_locked(
            db,
            outbound=outbound,
            now=now,
            provider_confirmed_absent=provider_confirmed_absent,
        )


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
        logger.warning("Could not persist refreshed Gmail token for outbound account %s", account_id)


async def _process_claimed_outbound(
    outbound: OutboundMessage,
    *,
    gmail: GmailService,
) -> None:
    lease_token = outbound.lease_token
    if lease_token is None:
        return
    try:
        provider_message_id = await gmail.find_sent_message_by_rfc_message_id(
            outbound.rfc_message_id,
            max_retries=1,
        )
        await _persist_refreshed_token(outbound.account_id, gmail)
    except Exception as exc:
        await _persist_refreshed_token(outbound.account_id, gmail)
        if outbound.provider_attempted_at is not None:
            await _record_reconciling(
                outbound_id=outbound.id,
                lease_token=lease_token,
                now=utcnow(),
            )
        else:
            await _record_preflight_failure(
                outbound_id=outbound.id,
                lease_token=lease_token,
                disposition=classify_outbound_preflight_error(exc),
                now=utcnow(),
            )
        return

    if provider_message_id:
        if not await _ensure_post_send_archive(outbound):
            await _record_reconciling(
                outbound_id=outbound.id,
                lease_token=lease_token,
                now=utcnow(),
            )
            return
        await _record_outbound_sent(
            outbound_id=outbound.id,
            lease_token=lease_token,
            provider_message_id=provider_message_id,
            now=utcnow(),
        )
        return

    if outbound.provider_attempted_at is not None:
        await _record_reconciling(
            outbound_id=outbound.id,
            lease_token=lease_token,
            now=utcnow(),
            provider_confirmed_absent=True,
        )
        return

    payload = outbound.payload
    if not isinstance(payload, dict):
        await _record_preflight_failure(
            outbound_id=outbound.id,
            lease_token=lease_token,
            disposition=OutboundErrorDisposition(False, "payload_missing", "Send content is unavailable"),
            now=utcnow(),
        )
        return

    attempted_at = utcnow()
    if not await _mark_provider_attempt_started(
        outbound_id=outbound.id,
        lease_token=lease_token,
        now=attempted_at,
    ):
        return
    outbound.provider_attempted_at = attempted_at

    try:
        provider_message_id = await gmail.send_email(
            to=list(payload.get("to") or []),
            cc=list(payload.get("cc") or []),
            bcc=list(payload.get("bcc") or []),
            subject=str(payload.get("subject") or ""),
            body_html=str(payload.get("body_html") or ""),
            body_text=str(payload.get("body_text") or ""),
            in_reply_to=payload.get("in_reply_to"),
            references=payload.get("references"),
            thread_id=payload.get("thread_id"),
            attachments=list(payload.get("attachments") or []),
            message_id_header=outbound.rfc_message_id,
            max_retries=1,
        )
        await _persist_refreshed_token(outbound.account_id, gmail)
    except Exception:
        await _persist_refreshed_token(outbound.account_id, gmail)
        await _record_reconciling(
            outbound_id=outbound.id,
            lease_token=lease_token,
            now=utcnow(),
        )
        return

    if not provider_message_id:
        await _record_reconciling(
            outbound_id=outbound.id,
            lease_token=lease_token,
            now=utcnow(),
        )
        return

    if not await _ensure_post_send_archive(outbound):
        await _record_reconciling(
            outbound_id=outbound.id,
            lease_token=lease_token,
            now=utcnow(),
        )
        return
    await _record_outbound_sent(
        outbound_id=outbound.id,
        lease_token=lease_token,
        provider_message_id=provider_message_id,
        now=utcnow(),
    )


async def _due_account_ids(now: datetime, limit: int = 50) -> list[int]:
    due = or_(
        and_(OutboundMessage.state == "staged", OutboundMessage.execute_after <= now),
        and_(
            OutboundMessage.state.in_(("retry_wait", "reconciling")),
            OutboundMessage.next_attempt_at <= now,
        ),
        and_(OutboundMessage.state == "processing", OutboundMessage.lease_expires_at <= now),
    )
    async with async_session() as db:
        result = await db.execute(
            select(OutboundMessage.account_id)
            .where(due)
            .distinct()
            .order_by(OutboundMessage.account_id)
            .limit(limit)
        )
        return list(result.scalars().all())


async def drain_due_outbound_messages() -> int:
    try:
        await scrub_expired_retry_payloads()
    except Exception:
        logger.exception("Expired outbound retry payload scrub failed")
    processed = 0
    for account_id in await _due_account_ids(utcnow()):
        remaining = OUTBOUND_DRAIN_MAX_MESSAGES - processed
        if remaining <= 0:
            break
        try:
            processed += await _drain_account_outbound(account_id, max_messages=remaining)
        except Exception:
            logger.exception("Outbound drain failed for account %s", account_id)
    return processed


async def _drain_account_outbound(account_id: int, *, max_messages: int) -> int:
    processed = 0
    async with account_advisory_lock(account_id) as acquired:
        if not acquired:
            return 0

        gmail: GmailService | None = None
        while processed < max_messages:
            async with async_session() as db:
                claimed = await _claim_due_outbound(
                    db,
                    account_id=account_id,
                    now=utcnow(),
                    limit=max_messages - processed,
                )
            if not claimed:
                break

            if gmail is None:
                disposition: OutboundErrorDisposition | None = None
                try:
                    async with async_session() as db:
                        account = (
                            await db.execute(
                                select(GoogleAccount).where(
                                    GoogleAccount.id == account_id,
                                    GoogleAccount.is_active.is_(True),
                                )
                            )
                        ).scalar_one_or_none()
                        if account is None:
                            disposition = OutboundErrorDisposition(
                                False,
                                "account_unavailable",
                                "The sending account is no longer available",
                            )
                        else:
                            client_id, client_secret = await get_google_credentials(db)
                            gmail = GmailService(
                                account,
                                client_id=client_id,
                                client_secret=client_secret,
                                transport_timeout=OUTBOUND_GMAIL_TRANSPORT_TIMEOUT_SECONDS,
                            )
                except Exception as exc:
                    disposition = classify_outbound_preflight_error(exc)
                if gmail is None:
                    assert disposition is not None
                    for outbound in claimed:
                        if outbound.lease_token is not None:
                            await _record_preflight_failure(
                                outbound_id=outbound.id,
                                lease_token=outbound.lease_token,
                                disposition=disposition,
                                now=utcnow(),
                            )
                            processed += 1
                    break

            for outbound in claimed:
                await _process_claimed_outbound(outbound, gmail=gmail)
                processed += 1
    return processed


async def _publish_outbound_event(user_id: int, send_id: UUID) -> None:
    try:
        from backend.services.notifications import publish_event

        await asyncio.wait_for(
            publish_event(
                user_id,
                "outbound_send_updated",
                {"send_id": str(send_id)},
            ),
            timeout=OUTBOUND_REDIS_IO_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Could not publish outbound send update", exc_info=True)


async def try_enqueue_outbound_drain(execute_after: datetime | None = None) -> None:
    try:
        await asyncio.wait_for(
            _enqueue_outbound_drain(execute_after=execute_after),
            timeout=OUTBOUND_REDIS_IO_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Could not enqueue outbound drain; cron will recover it", exc_info=True)


async def _enqueue_outbound_drain(*, execute_after: datetime | None = None) -> None:
    settings = get_settings()
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        defer_until = execute_after or (utcnow() + timedelta(seconds=OUTBOUND_UNDO_SECONDS))
        await redis.enqueue_job(
            "drain_outbound_messages_task",
            _queue_name=OUTBOUND_QUEUE_NAME,
            _defer_until=defer_until,
        )
    finally:
        await redis.close()
