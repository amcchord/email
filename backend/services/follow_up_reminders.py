"""Delivery-confirmed automatic follow-up reminders.

The outbound row remains the delivery source of truth.  A follow-up intent is
accepted with the send, but cannot schedule a Snooze until Gmail delivery is
terminally confirmed and the exact sent message has arrived through normal
account sync.  Redis is only a low-latency wake-up; the cron drainer owns
recovery after process restarts or lost queue messages.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import getaddresses
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import async_session
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.follow_up import AccountFollowUpPolicy, OutboundFollowUpIntent
from backend.models.mail_action import ACTIVE_MAIL_ACTION_STATES, MailAction
from backend.models.outbound_message import OutboundMessage
from backend.models.snooze import EmailSnooze, SNOOZE_ACTIVE_STATES
from backend.schemas.email import ComposeRequest
from backend.services.snoozes import SNOOZE_ACTION_NAMESPACE, _lock_conversation_scope


logger = logging.getLogger(__name__)

FOLLOW_UP_QUEUE_NAME = "arq:cron"
FOLLOW_UP_LEASE_SECONDS = 120
FOLLOW_UP_DRAIN_LIMIT = 50
FOLLOW_UP_REDIS_TIMEOUT_SECONDS = 1.0
FOLLOW_UP_SYNC_RETRY_SECONDS = 60
FOLLOW_UP_MAX_SYNC_AGE_DAYS = 14
FOLLOW_UP_SNOOZE_NAMESPACE = UUID("f0ac6a16-96f5-50b1-b26e-c2aeae7f6f34")
FOLLOW_UP_ACTIVE_INTENT_STATES = ("awaiting_delivery", "pending_sync")


@dataclass(frozen=True, slots=True)
class EffectiveFollowUp:
    requested_via: str
    delay_days: int
    wake_local_time: str
    time_zone: str
    weekdays_only: bool


class FollowUpReconciliationError(RuntimeError):
    """Provider and RFC delivery identities do not name one sent message."""


class FollowUpEligibilityError(ValueError):
    """An explicit reminder cannot safely apply to these recipients."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mailbox_address(value: str) -> str | None:
    parsed = getaddresses([value])
    if len(parsed) != 1:
        return None
    address = parsed[0][1].strip().casefold()
    return address or None


async def resolve_effective_follow_up(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    request: ComposeRequest,
) -> EffectiveFollowUp | None:
    """Resolve one content-free reminder snapshot at send admission."""
    if request.follow_up_reminder == "disabled":
        return None

    policy = await db.scalar(
        select(AccountFollowUpPolicy).where(
            AccountFollowUpPolicy.user_id == user_id,
            AccountFollowUpPolicy.account_id == account_id,
        )
    )
    if request.follow_up_reminder == "default" and not (policy and policy.enabled):
        return None

    # Bcc never turns an automatic policy into a bulk-mail reminder.  A direct
    # To/Cc recipient must differ from every address the owner has connected.
    owned_result = await db.execute(
        select(GoogleAccount.email).where(GoogleAccount.user_id == user_id)
    )
    owned_addresses = {
        str(value).strip().casefold()
        for value in owned_result.scalars().all()
        if str(value).strip()
    }
    direct_addresses = {
        address
        for address in (_mailbox_address(value) for value in (*request.to, *request.cc))
        if address
    }
    if not direct_addresses.difference(owned_addresses):
        if request.follow_up_reminder == "enabled":
            raise FollowUpEligibilityError(
                "Automatic follow-up requires an external To or Cc recipient"
            )
        return None

    return EffectiveFollowUp(
        requested_via=(
            "explicit" if request.follow_up_reminder == "enabled" else "policy"
        ),
        delay_days=int(policy.delay_days if policy else 3),
        wake_local_time=str(policy.wake_local_time if policy else "09:00"),
        time_zone=str(
            policy.time_zone
            if policy
            else request.follow_up_time_zone or "UTC"
        ),
        weekdays_only=bool(policy.weekdays_only if policy else True),
    )


def _valid_local_candidate(candidate: datetime, zone: ZoneInfo) -> bool:
    return candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == candidate.replace(tzinfo=None)


def _resolve_local_datetime(local_date: date, local_time: time, zone: ZoneInfo) -> datetime:
    """Resolve DST gaps forward and repeated clocks to the later occurrence."""
    naive = datetime.combine(local_date, local_time)
    candidates = [naive.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [candidate for candidate in candidates if _valid_local_candidate(candidate, zone)]
    if valid:
        return max(valid, key=lambda value: value.astimezone(timezone.utc))

    # A configured time can fall inside a spring-forward gap.  A reminder is
    # deferred to the first real local minute instead of firing early.
    for minute in range(1, 181):
        shifted = naive + timedelta(minutes=minute)
        candidate = shifted.replace(tzinfo=zone, fold=0)
        if _valid_local_candidate(candidate, zone):
            return candidate
    raise ValueError("Could not resolve follow-up reminder local time")


def calculate_follow_up_wake_at(
    delivered_at: datetime,
    *,
    delay_days: int,
    wake_local_time: str,
    time_zone: str,
    weekdays_only: bool,
) -> datetime:
    if delivered_at.tzinfo is None or delivered_at.utcoffset() is None:
        raise ValueError("Delivery time must include a timezone")
    if not 1 <= int(delay_days) <= 30:
        raise ValueError("Follow-up delay must be between 1 and 30 days")
    hour_text, minute_text = wake_local_time.split(":", 1)
    target_time = time(hour=int(hour_text), minute=int(minute_text))
    zone = ZoneInfo(time_zone)
    target_date = delivered_at.astimezone(zone).date()
    remaining = int(delay_days)
    while remaining:
        target_date += timedelta(days=1)
        if not weekdays_only or target_date.weekday() < 5:
            remaining -= 1
    return _resolve_local_datetime(target_date, target_time, zone).astimezone(timezone.utc)


async def stage_follow_up_intent(
    db: AsyncSession,
    *,
    outbound: OutboundMessage,
    request: ComposeRequest,
    configuration: EffectiveFollowUp | None,
    accepted_at: datetime,
) -> OutboundFollowUpIntent | None:
    if configuration is None:
        outbound.follow_up_requested = False
        return None
    outbound.follow_up_requested = True
    intent = OutboundFollowUpIntent(
        public_id=uuid4(),
        outbound_message_id=outbound.id,
        user_id=outbound.user_id,
        account_id=outbound.account_id,
        state="awaiting_delivery",
        requested_via=configuration.requested_via,
        delay_days=configuration.delay_days,
        wake_local_time=configuration.wake_local_time,
        time_zone=configuration.time_zone,
        weekdays_only=configuration.weekdays_only,
        post_send_archive=bool(request.archive_source_after_send),
        next_attempt_at=outbound.execute_after,
        attempt_count=0,
        status_detail="awaiting_delivery",
        created_at=accepted_at,
        updated_at=accepted_at,
    )
    db.add(intent)
    await db.flush()
    return intent


def _intent_terminal(
    intent: OutboundFollowUpIntent,
    *,
    state: str,
    now: datetime,
    detail: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    intent.state = state
    intent.status_detail = detail
    intent.next_attempt_at = None
    intent.lease_token = None
    intent.lease_expires_at = None
    intent.error_code = error_code
    intent.error_message = error_message
    intent.updated_at = now
    if state == "cancelled":
        intent.cancelled_at = now
    elif state == "failed":
        intent.failed_at = now


async def sync_follow_up_intent_with_outbound(
    db: AsyncSession,
    *,
    outbound: OutboundMessage,
    now: datetime,
) -> None:
    """Advance or settle the companion intent in the outbound transaction."""
    intent = await db.scalar(
        select(OutboundFollowUpIntent)
        .where(OutboundFollowUpIntent.outbound_message_id == outbound.id)
        .with_for_update()
    )
    if intent is None or intent.state not in FOLLOW_UP_ACTIVE_INTENT_STATES:
        return
    if outbound.state == "sent" and outbound.sent_at is not None:
        intent.state = "pending_sync"
        intent.status_detail = "waiting_for_sent_sync"
        intent.provider_message_id = outbound.provider_message_id
        intent.rfc_message_id = outbound.rfc_message_id
        intent.next_attempt_at = now
    elif outbound.state == "failed" and (
        outbound.retry_authorized
        and outbound.retry_expires_at is not None
        and outbound.retry_expires_at > now
    ):
        intent.status_detail = "waiting_for_safe_retry"
        intent.next_attempt_at = min(
            outbound.retry_expires_at,
            now + timedelta(seconds=FOLLOW_UP_SYNC_RETRY_SECONDS),
        )
    elif outbound.state in {"failed", "cancelled"}:
        _intent_terminal(
            intent,
            state="cancelled",
            now=now,
            detail=f"outbound_{outbound.state}",
        )
    else:
        intent.status_detail = "awaiting_delivery"
        intent.next_attempt_at = (
            outbound.next_attempt_at
            or outbound.execute_after
            or now + timedelta(seconds=FOLLOW_UP_SYNC_RETRY_SECONDS)
        )
    intent.lease_token = None
    intent.lease_expires_at = None
    intent.updated_at = now


def _snooze_action_key(public_id: UUID, purpose: str) -> UUID:
    return uuid5(SNOOZE_ACTION_NAMESPACE, f"{public_id}:{purpose}")


def _snooze_payload_hash(
    *, email_id: int, wake_at: datetime, time_zone: str
) -> str:
    payload = json.dumps(
        {
            "condition": "if_no_reply",
            "email_id": email_id,
            "time_zone": time_zone,
            "wake_at": wake_at.astimezone(timezone.utc).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _post_send_archive_is_settled(
    db: AsyncSession,
    *,
    intent: OutboundFollowUpIntent,
    outbound: OutboundMessage,
) -> bool:
    if not intent.post_send_archive:
        return True
    action_key = uuid5(
        NAMESPACE_URL,
        f"mail-outbound:{outbound.send_id}:archive-source",
    )
    rows = list((await db.execute(
        select(MailAction).where(
            MailAction.user_id == intent.user_id,
            MailAction.idempotency_key == action_key,
        )
    )).scalars().all())
    if not rows:
        # Delivery can be confirmed after the admitted source was removed by
        # sync.  In that safe no-op case the archive hook intentionally creates
        # no MailAction rows.
        return True
    return not any(row.state in ACTIVE_MAIL_ACTION_STATES for row in rows)


async def _synced_sent_email(
    db: AsyncSession,
    *,
    intent: OutboundFollowUpIntent,
) -> Email | None:
    base = (
        Email.account_id == intent.account_id,
        Email.is_sent.is_(True),
        Email.date.is_not(None),
    )
    provider_match = None
    if intent.provider_message_id:
        provider_match = await db.scalar(
            select(Email).where(
                *base,
                Email.gmail_message_id == intent.provider_message_id,
            )
        )

    rfc_matches: list[Email] = []
    if intent.rfc_message_id:
        rfc_matches = list((await db.execute(
            select(Email)
            .where(*base, Email.message_id_header == intent.rfc_message_id)
            .order_by(Email.id)
            .limit(2)
        )).scalars().all())
        if len(rfc_matches) > 1:
            raise FollowUpReconciliationError(
                "The RFC Message-ID matched multiple synchronized sent messages"
            )

    if provider_match is not None:
        if rfc_matches and rfc_matches[0].id != provider_match.id:
            raise FollowUpReconciliationError(
                "Provider and RFC message identities resolved to different sent messages"
            )
        return provider_match
    if rfc_matches:
        return rfc_matches[0]
    return None


async def _schedule_snooze(
    db: AsyncSession,
    *,
    intent: OutboundFollowUpIntent,
    outbound: OutboundMessage,
    target: Email,
    now: datetime,
) -> UUID | None:
    await _lock_conversation_scope(
        db,
        user_id=intent.user_id,
        account_id=intent.account_id,
        gmail_thread_id=target.gmail_thread_id,
    )
    conversation = list((await db.execute(
        select(Email)
        .where(
            Email.account_id == intent.account_id,
            Email.gmail_thread_id == target.gmail_thread_id,
        )
        .order_by(Email.id)
        .with_for_update()
    )).scalars().all())
    active = await db.scalar(
        select(EmailSnooze).where(
            EmailSnooze.user_id == intent.user_id,
            EmailSnooze.account_id == intent.account_id,
            EmailSnooze.gmail_thread_id == target.gmail_thread_id,
            EmailSnooze.state.in_(SNOOZE_ACTIVE_STATES),
        ).with_for_update()
    )
    wake_at = intent.wake_at
    if wake_at is None:
        raise ValueError("Follow-up wake time is unavailable")
    conversation_ids = [email.id for email in conversation]
    versions = {
        str(email.id): int(email.mail_action_version or 0)
        for email in conversation
    }

    if active is not None and active.origin == "manual":
        _intent_terminal(
            intent,
            state="skipped",
            now=now,
            detail="manual_reminder_exists",
        )
        return None

    if active is not None:
        if active.origin_outbound_id == outbound.id:
            intent.snooze_id = active.id
            intent.state = "scheduled"
            intent.status_detail = "scheduled"
            intent.scheduled_at = intent.scheduled_at or now
            intent.next_attempt_at = None
            intent.lease_token = None
            intent.lease_expires_at = None
            return active.public_id
        current_delivery_key = (
            intent.delivered_at or datetime.min.replace(tzinfo=timezone.utc),
            outbound.id,
        )
        existing_delivery_key = (
            active.anchor_date or datetime.min.replace(tzinfo=timezone.utc),
            int(active.origin_outbound_id or 0),
        )
        if current_delivery_key <= existing_delivery_key:
            _intent_terminal(
                intent,
                state="superseded",
                now=now,
                detail="older_outbound",
            )
            return None
        if active.state != "scheduled" or (
            active.lease_token is not None
            and active.lease_expires_at is not None
            and active.lease_expires_at > now
        ):
            _intent_terminal(
                intent,
                state="skipped",
                now=now,
                detail="active_reminder_processing",
            )
            return None
        prior_intents = list((await db.execute(
            select(OutboundFollowUpIntent).where(
                OutboundFollowUpIntent.snooze_id == active.id,
                OutboundFollowUpIntent.id != intent.id,
                OutboundFollowUpIntent.state == "scheduled",
            ).with_for_update()
        )).scalars().all())
        for prior in prior_intents:
            _intent_terminal(
                prior,
                state="superseded",
                now=now,
                detail="newer_outbound",
            )
        active.email_id = target.id
        active.gmail_message_id = target.gmail_message_id
        active.wake_at = wake_at
        active.time_zone = intent.time_zone
        active.condition = "if_no_reply"
        active.origin = "automatic_follow_up"
        active.origin_outbound_id = outbound.id
        active.state = "scheduled"
        active.status_detail = "scheduled"
        active.archive_required = False
        active.anchor_date = target.date
        active.mail_action_version_at_schedule = int(target.mail_action_version or 0)
        active.conversation_email_ids = conversation_ids
        active.original_inbox_email_ids = []
        active.mail_action_versions_at_schedule = versions
        active.return_target_email_ids = []
        active.completion_state = None
        active.pending_action_purpose = None
        active.payload_hash = _snooze_payload_hash(
            email_id=target.id,
            wake_at=wake_at,
            time_zone=intent.time_zone,
        )
        active.next_attempt_at = wake_at
        active.lease_token = None
        active.lease_expires_at = None
        active.error_code = None
        active.error_message = None
        active.updated_at = now
        active.scheduled_at = now
        intent.snooze_id = active.id
        public_id = active.public_id
    else:
        public_id = uuid5(FOLLOW_UP_SNOOZE_NAMESPACE, str(intent.public_id))
        snooze = EmailSnooze(
            public_id=public_id,
            idempotency_key=public_id,
            payload_hash=_snooze_payload_hash(
                email_id=target.id,
                wake_at=wake_at,
                time_zone=intent.time_zone,
            ),
            user_id=intent.user_id,
            account_id=intent.account_id,
            email_id=target.id,
            gmail_message_id=target.gmail_message_id,
            gmail_thread_id=target.gmail_thread_id,
            wake_at=wake_at,
            time_zone=intent.time_zone,
            condition="if_no_reply",
            origin="automatic_follow_up",
            origin_outbound_id=outbound.id,
            state="scheduled",
            status_detail="scheduled",
            archive_required=False,
            anchor_date=target.date,
            mail_action_version_at_schedule=int(target.mail_action_version or 0),
            conversation_email_ids=conversation_ids,
            original_inbox_email_ids=[],
            mail_action_versions_at_schedule=versions,
            return_target_email_ids=[],
            completion_state=None,
            pending_action_purpose=None,
            archive_idempotency_key=_snooze_action_key(public_id, "archive"),
            return_idempotency_key=_snooze_action_key(public_id, "return"),
            next_attempt_at=wake_at,
            attempt_count=0,
            created_at=now,
            updated_at=now,
            scheduled_at=now,
        )
        db.add(snooze)
        await db.flush()
        intent.snooze_id = snooze.id

    intent.state = "scheduled"
    intent.status_detail = "scheduled"
    intent.scheduled_at = now
    intent.next_attempt_at = None
    intent.lease_token = None
    intent.lease_expires_at = None
    intent.error_code = None
    intent.error_message = None
    intent.updated_at = now
    return public_id


async def _claim_due(now: datetime, limit: int) -> list[tuple[int, UUID]]:
    async with async_session() as db:
        rows = list((await db.execute(
            select(OutboundFollowUpIntent)
            .where(
                OutboundFollowUpIntent.state.in_(FOLLOW_UP_ACTIVE_INTENT_STATES),
                OutboundFollowUpIntent.next_attempt_at <= now,
                or_(
                    OutboundFollowUpIntent.lease_token.is_(None),
                    OutboundFollowUpIntent.lease_expires_at <= now,
                ),
            )
            .order_by(OutboundFollowUpIntent.next_attempt_at, OutboundFollowUpIntent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )).scalars().all())
        claimed: list[tuple[int, UUID]] = []
        for intent in rows:
            token = uuid4()
            intent.lease_token = token
            intent.lease_expires_at = now + timedelta(seconds=FOLLOW_UP_LEASE_SECONDS)
            intent.attempt_count += 1
            intent.updated_at = now
            claimed.append((intent.id, token))
        await db.commit()
        return claimed


async def _process_claim(intent_id: int, token: UUID, now: datetime) -> UUID | None:
    async with async_session() as db:
        identity = await db.scalar(
            select(OutboundFollowUpIntent).where(
                OutboundFollowUpIntent.id == intent_id,
                OutboundFollowUpIntent.lease_token == token,
            )
        )
        if identity is None:
            return None
        outbound = await db.scalar(
            select(OutboundMessage)
            .where(
                OutboundMessage.id == identity.outbound_message_id,
                OutboundMessage.user_id == identity.user_id,
                OutboundMessage.account_id == identity.account_id,
            )
            .with_for_update()
        )
        intent = await db.scalar(
            select(OutboundFollowUpIntent).where(
                OutboundFollowUpIntent.id == intent_id,
                OutboundFollowUpIntent.lease_token == token,
            ).with_for_update()
        )
        if intent is None:
            return None
        if outbound is None:
            _intent_terminal(
                intent,
                state="failed",
                now=now,
                detail="outbound_missing",
                error_code="outbound_missing",
                error_message="The accepted send is no longer available",
            )
            await db.commit()
            return None

        if intent.state == "awaiting_delivery":
            if outbound.state == "sent" and outbound.sent_at is not None:
                intent.state = "pending_sync"
                intent.status_detail = "waiting_for_sent_sync"
                intent.provider_message_id = outbound.provider_message_id
                intent.rfc_message_id = outbound.rfc_message_id
                intent.next_attempt_at = now
            elif (
                outbound.state == "failed"
                and outbound.retry_authorized
                and outbound.retry_expires_at is not None
                and outbound.retry_expires_at > now
            ):
                intent.status_detail = "waiting_for_safe_retry"
                intent.next_attempt_at = min(
                    outbound.retry_expires_at,
                    now + timedelta(seconds=FOLLOW_UP_SYNC_RETRY_SECONDS),
                )
            elif outbound.state in ("failed", "cancelled"):
                _intent_terminal(
                    intent,
                    state="cancelled",
                    now=now,
                    detail=f"outbound_{outbound.state}",
                )
            else:
                intent.status_detail = "awaiting_delivery"
                intent.next_attempt_at = now + timedelta(seconds=FOLLOW_UP_SYNC_RETRY_SECONDS)

        public_id = None
        if intent.state == "pending_sync":
            if outbound.state != "sent" or outbound.sent_at is None:
                _intent_terminal(
                    intent,
                    state="failed",
                    now=now,
                    detail="delivery_truth_changed",
                    error_code="delivery_truth_changed",
                    error_message="Delivery confirmation became inconsistent",
                )
            elif not await _post_send_archive_is_settled(
                db,
                intent=intent,
                outbound=outbound,
            ):
                intent.status_detail = "waiting_for_post_send_archive"
                intent.next_attempt_at = now + timedelta(seconds=FOLLOW_UP_SYNC_RETRY_SECONDS)
            else:
                try:
                    target = await _synced_sent_email(db, intent=intent)
                except FollowUpReconciliationError as error:
                    _intent_terminal(
                        intent,
                        state="failed",
                        now=now,
                        detail="sent_message_identity_conflict",
                        error_code="sent_message_identity_conflict",
                        error_message=str(error),
                    )
                    target = None
                if intent.state == "failed":
                    pass
                elif target is None:
                    if now >= outbound.sent_at + timedelta(days=FOLLOW_UP_MAX_SYNC_AGE_DAYS):
                        _intent_terminal(
                            intent,
                            state="failed",
                            now=now,
                            detail="sent_message_not_synchronized",
                            error_code="sent_message_not_synchronized",
                            error_message="The delivered message could not be reconciled after sync",
                        )
                    else:
                        intent.status_detail = "waiting_for_sent_sync"
                        intent.next_attempt_at = now + timedelta(seconds=FOLLOW_UP_SYNC_RETRY_SECONDS)
                else:
                    provider_delivered_at = target.date or outbound.sent_at
                    if provider_delivered_at.tzinfo is None or provider_delivered_at.utcoffset() is None:
                        provider_delivered_at = provider_delivered_at.replace(tzinfo=timezone.utc)
                    intent.delivered_at = provider_delivered_at.astimezone(timezone.utc)
                    intent.wake_at = calculate_follow_up_wake_at(
                        intent.delivered_at,
                        delay_days=intent.delay_days,
                        wake_local_time=intent.wake_local_time,
                        time_zone=intent.time_zone,
                        weekdays_only=intent.weekdays_only,
                    )
                    try:
                        public_id = await _schedule_snooze(
                            db,
                            intent=intent,
                            outbound=outbound,
                            target=target,
                            now=now,
                        )
                    except IntegrityError:
                        await db.rollback()
                        return None

        if intent.state in FOLLOW_UP_ACTIVE_INTENT_STATES:
            intent.lease_token = None
            intent.lease_expires_at = None
            intent.updated_at = now
        await db.commit()
        user_id = intent.user_id
    if public_id is not None:
        await _publish_snooze_event(user_id, public_id)
    return public_id


async def drain_follow_up_intents() -> int:
    claimed = await _claim_due(utcnow(), FOLLOW_UP_DRAIN_LIMIT)
    for intent_id, token in claimed:
        try:
            await _process_claim(intent_id, token, utcnow())
        except Exception:
            logger.exception("Automatic follow-up drain failed for intent %s", intent_id)
    return len(claimed)


async def _publish_snooze_event(user_id: int, public_id: UUID) -> None:
    try:
        from backend.services.notifications import publish_event

        await asyncio.wait_for(
            publish_event(user_id, "snooze_updated", {"id": str(public_id)}),
            timeout=FOLLOW_UP_REDIS_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Could not publish automatic follow-up update", exc_info=False)


async def try_enqueue_follow_up_drain() -> None:
    try:
        await asyncio.wait_for(
            _enqueue_follow_up_drain(),
            timeout=FOLLOW_UP_REDIS_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "Could not enqueue automatic follow-up drain; cron will recover it",
            exc_info=False,
        )


async def _enqueue_follow_up_drain() -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job("drain_follow_up_intents_task", _queue_name=FOLLOW_UP_QUEUE_NAME)
    finally:
        await redis.close()
