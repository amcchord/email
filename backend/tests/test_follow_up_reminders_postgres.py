"""Disposable-PostgreSQL lifecycle checks for automatic follow-up reminders.

Set FOLLOW_UP_POSTGRES_TEST_URL only to a freshly migrated disposable database.
Never point this test at development or production data.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.services.follow_up_reminders as follow_up_module
import backend.services.outbound_messages as outbound_module
import backend.services.snoozes as snooze_module
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.follow_up import AccountFollowUpPolicy, OutboundFollowUpIntent
from backend.models.outbound_message import OutboundMessage
from backend.models.snooze import EmailSnooze
from backend.models.user import User
from backend.schemas.email import ComposeRequest
from backend.schemas.snooze import SnoozeCreateRequest
from backend.services.follow_up_reminders import _claim_due, _process_claim
from backend.services.outbound_messages import stage_outbound_message
from backend.services.outbound_messages import (
    OutboundMessageValidationError,
    cancel_scheduled_outbound_message,
    send_scheduled_outbound_now,
    undo_outbound_message,
)
from backend.services.snoozes import (
    SnoozeConflict,
    _lock_conversation_scope,
    cancel_snooze,
    create_snooze,
)


DATABASE_URL = os.getenv("FOLLOW_UP_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires FOLLOW_UP_POSTGRES_TEST_URL for disposable PostgreSQL",
    ),
]
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _session_factory():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _disposable_sessions(monkeypatch):
    if not DATABASE_URL:
        return
    engine, sessions = _session_factory()
    monkeypatch.setattr(follow_up_module, "async_session", sessions)
    monkeypatch.setattr(outbound_module, "async_session", sessions)

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(follow_up_module, "_publish_snooze_event", noop)
    monkeypatch.setattr(outbound_module, "_publish_outbound_event", noop)
    return engine, sessions


async def _reset(engine):
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def _seed_account(sessions, suffix="one"):
    async with sessions() as db:
        user = User(username=f"generated-follow-up-{suffix}", is_active=True, is_admin=False)
        db.add(user)
        await db.flush()
        account = GoogleAccount(
            user_id=user.id,
            email=f"owner-{suffix}@example.test",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        await db.commit()
        return user.id, account.id


def _request(account_id, *, mode="default", key=None, to=None, cc=None, bcc=None):
    return ComposeRequest(
        account_id=account_id,
        to=to if to is not None else ["recipient@example.test"],
        cc=cc or [],
        bcc=bcc or [],
        subject="Generated follow-up lifecycle",
        body_text="Generated fixture content only.",
        follow_up_reminder=mode,
        follow_up_time_zone="America/New_York",
        idempotency_key=key or uuid4(),
    )


async def _stage(sessions, *, user_id, account_id, mode="enabled"):
    async with sessions() as db:
        outbound, created = await stage_outbound_message(
            db,
            user_id=user_id,
            request=_request(account_id, mode=mode),
            now=NOW,
        )
        assert created is True
        return outbound.id


async def _mark_sent_and_sync(
    sessions,
    *,
    outbound_id,
    delivered_at,
    provider_message_id="generated-provider-sent",
    rfc_message_id=None,
    thread_id="generated-follow-up-thread",
):
    async with sessions() as db:
        outbound = await db.get(OutboundMessage, outbound_id, with_for_update=True)
        outbound.state = "sent"
        outbound.sent_at = delivered_at - timedelta(seconds=10)
        outbound.provider_message_id = provider_message_id
        outbound.next_attempt_at = None
        outbound.payload = None
        outbound.retry_authorized = False
        outbound.retry_expires_at = None
        email = Email(
            account_id=outbound.account_id,
            gmail_message_id=provider_message_id,
            gmail_thread_id=thread_id,
            message_id_header=rfc_message_id or outbound.rfc_message_id,
            subject="Generated delivered message",
            from_address="owner-one@example.test",
            to_addresses=["recipient@example.test"],
            date=delivered_at,
            snippet="Generated fixture content only.",
            labels=["SENT"],
            is_read=True,
            is_starred=False,
            is_trash=False,
            is_spam=False,
            is_draft=False,
            is_sent=True,
            has_attachments=False,
            mail_action_version=0,
        )
        db.add(email)
        await db.flush()
        email_id = email.id
        await db.commit()
        return email_id


async def _process_one(at):
    claimed = await _claim_due(at, 10)
    assert len(claimed) == 1
    await _process_claim(claimed[0][0], claimed[0][1], at)


async def test_default_off_policy_opt_in_and_explicit_disable(_disposable_sessions):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)

        await _stage(sessions, user_id=user_id, account_id=account_id, mode="default")
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(OutboundFollowUpIntent)) == 0
            first = await db.scalar(select(OutboundMessage).order_by(OutboundMessage.id))
            assert first.follow_up_requested is False
            db.add(AccountFollowUpPolicy(
                account_id=account_id,
                user_id=user_id,
                enabled=True,
                delay_days=4,
                wake_local_time="08:30",
                time_zone="America/New_York",
                weekdays_only=False,
                revision=1,
            ))
            await db.commit()

        await _stage(sessions, user_id=user_id, account_id=account_id, mode="default")
        await _stage(sessions, user_id=user_id, account_id=account_id, mode="disabled")
        async with sessions() as db:
            intents = list((await db.execute(select(OutboundFollowUpIntent))).scalars())
            assert len(intents) == 1
            assert intents[0].requested_via == "policy"
            assert intents[0].delay_days == 4
            assert intents[0].wake_local_time == "08:30"
            assert intents[0].time_zone == "America/New_York"
            assert intents[0].weekdays_only is False
            assert intents[0].provider_message_id is None
            assert intents[0].rfc_message_id is None
    finally:
        await engine.dispose()


async def test_explicit_enable_rejects_self_or_bcc_only_but_accepts_mixed_direct(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)
        self_only = _request(
            account_id,
            mode="enabled",
            to=["owner-one@example.test"],
        )
        bcc_only = _request(
            account_id,
            mode="enabled",
            to=["owner-one@example.test"],
            bcc=["hidden@example.test"],
        )
        async with sessions() as db:
            with pytest.raises(OutboundMessageValidationError, match="external To or Cc"):
                await stage_outbound_message(db, user_id=user_id, request=self_only, now=NOW)
            await db.rollback()
            with pytest.raises(OutboundMessageValidationError, match="external To or Cc"):
                await stage_outbound_message(db, user_id=user_id, request=bcc_only, now=NOW)
            await db.rollback()
            accepted, created = await stage_outbound_message(
                db,
                user_id=user_id,
                request=_request(
                    account_id,
                    mode="enabled",
                    to=["owner-one@example.test"],
                    cc=["direct@example.test"],
                ),
                now=NOW,
            )
            assert created is True
            assert accepted.follow_up_requested is True
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(OutboundFollowUpIntent)) == 1
    finally:
        await engine.dispose()


async def test_actual_provider_delivery_anchors_automatic_no_reply_snooze(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)
        outbound_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        delivered_at = datetime(2026, 8, 31, 20, 45, tzinfo=timezone.utc)
        email_id = await _mark_sent_and_sync(
            sessions,
            outbound_id=outbound_id,
            delivered_at=delivered_at,
        )

        await _process_one(NOW + timedelta(minutes=1))
        async with sessions() as db:
            intent = await db.scalar(select(OutboundFollowUpIntent))
            snooze = await db.scalar(select(EmailSnooze))
            assert intent.state == "scheduled"
            assert intent.delivered_at == delivered_at
            assert snooze.origin == "automatic_follow_up"
            assert snooze.origin_outbound_id == outbound_id
            assert snooze.email_id == email_id
            assert snooze.condition == "if_no_reply"
            assert snooze.original_inbox_email_ids == []
            assert snooze.archive_required is False
            assert snooze.anchor_date == delivered_at
            assert snooze.wake_at == datetime(2026, 9, 3, 13, 0, tzinfo=timezone.utc)
    finally:
        await engine.dispose()


async def test_conflicting_provider_and_rfc_identities_fail_closed(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)
        outbound_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        delivered_at = NOW + timedelta(seconds=30)
        await _mark_sent_and_sync(
            sessions,
            outbound_id=outbound_id,
            delivered_at=delivered_at,
            rfc_message_id="<generated-provider-row@example.test>",
        )
        async with sessions() as db:
            outbound = await db.get(OutboundMessage, outbound_id)
            db.add(Email(
                account_id=account_id,
                gmail_message_id="generated-rfc-only-row",
                gmail_thread_id="generated-conflict-thread",
                message_id_header=outbound.rfc_message_id,
                subject="Generated conflicting identity",
                from_address="owner-one@example.test",
                to_addresses=["recipient@example.test"],
                date=delivered_at,
                snippet="Generated fixture content only.",
                labels=["SENT"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=True,
                has_attachments=False,
                mail_action_version=0,
            ))
            await db.commit()

        await _process_one(NOW + timedelta(minutes=1))
        async with sessions() as db:
            intent = await db.scalar(select(OutboundFollowUpIntent))
            assert intent.state == "failed"
            assert intent.error_code == "sent_message_identity_conflict"
            assert await db.scalar(select(func.count()).select_from(EmailSnooze)) == 0
    finally:
        await engine.dispose()


async def test_manual_reminder_atomically_replaces_idle_automatic(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)
        outbound_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        email_id = await _mark_sent_and_sync(
            sessions,
            outbound_id=outbound_id,
            delivered_at=NOW + timedelta(seconds=30),
        )
        await _process_one(NOW + timedelta(minutes=1))

        async with sessions() as db:
            manual, created = await create_snooze(
                db,
                user_id=user_id,
                request=SnoozeCreateRequest(
                    email_id=email_id,
                    wake_at=NOW + timedelta(days=7),
                    time_zone="America/New_York",
                    condition="always",
                    idempotency_key=uuid4(),
                ),
                now=NOW + timedelta(minutes=2),
            )
            assert created is True
            assert manual.origin == "manual"

        async with sessions() as db:
            snoozes = list((await db.execute(select(EmailSnooze).order_by(EmailSnooze.id))).scalars())
            assert [row.state for row in snoozes] == ["cancelled", "scheduled"]
            assert [row.origin for row in snoozes] == ["automatic_follow_up", "manual"]
            intent = await db.scalar(select(OutboundFollowUpIntent))
            assert intent.state == "superseded"
            assert intent.status_detail == "manual_reminder_created"
    finally:
        await engine.dispose()


async def test_conversation_advisory_serializes_cancel_before_manual_replace(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)
        outbound_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        email_id = await _mark_sent_and_sync(
            sessions,
            outbound_id=outbound_id,
            delivered_at=NOW + timedelta(seconds=30),
        )
        await _process_one(NOW + timedelta(minutes=1))
        async with sessions() as lookup:
            automatic = await lookup.scalar(select(EmailSnooze))
            automatic_public_id = automatic.public_id
            thread_id = automatic.gmail_thread_id

        async def create_manual():
            async with sessions() as db:
                return await create_snooze(
                    db,
                    user_id=user_id,
                    request=SnoozeCreateRequest(
                        email_id=email_id,
                        wake_at=NOW + timedelta(days=8),
                        time_zone="America/New_York",
                        condition="always",
                        idempotency_key=uuid4(),
                    ),
                    now=NOW + timedelta(minutes=3),
                )

        async with sessions() as first:
            await _lock_conversation_scope(
                first,
                user_id=user_id,
                account_id=account_id,
                gmail_thread_id=thread_id,
            )
            pending_manual = asyncio.create_task(create_manual())
            await asyncio.sleep(0.02)
            assert pending_manual.done() is False
            cancelled = await cancel_snooze(
                first,
                user_id=user_id,
                public_id=automatic_public_id,
                now=NOW + timedelta(minutes=2),
            )
            assert cancelled.state == "cancelled"
        manual, created = await asyncio.wait_for(pending_manual, timeout=2)
        assert created is True
        assert manual.origin == "manual"
    finally:
        await engine.dispose()


async def test_snooze_transaction_holds_conversation_lock_through_action_stage(
    _disposable_sessions,
    monkeypatch,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "atomic-stage")
        async with sessions() as db:
            email = Email(
                account_id=account_id,
                gmail_message_id="generated-atomic-stage",
                gmail_thread_id="generated-atomic-stage-thread",
                message_id_header="<generated-atomic-stage@example.test>",
                subject="Generated atomic Snooze staging",
                from_address="recipient@example.test",
                to_addresses=["owner-atomic-stage@example.test"],
                date=NOW,
                snippet="Generated fixture content only.",
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                has_attachments=False,
                mail_action_version=0,
            )
            db.add(email)
            await db.flush()
            email_id = email.id
            await db.commit()

        action_staged = asyncio.Event()
        release_stage = asyncio.Event()
        original_stage = snooze_module.stage_mail_actions

        async def paused_stage(*args, **kwargs):
            assert kwargs.get("commit") is False
            result = await original_stage(*args, **kwargs)
            action_staged.set()
            await release_stage.wait()
            return result

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(snooze_module, "stage_mail_actions", paused_stage)
        monkeypatch.setattr(snooze_module, "publish_mail_action_event", noop)
        monkeypatch.setattr(snooze_module, "try_enqueue_mail_action_drain", noop)
        monkeypatch.setattr(snooze_module, "_publish_snooze_event", noop)

        async def create_manual(key, days):
            async with sessions() as db:
                return await create_snooze(
                    db,
                    user_id=user_id,
                    request=SnoozeCreateRequest(
                        email_id=email_id,
                        wake_at=NOW + timedelta(days=days),
                        time_zone="America/New_York",
                        condition="always",
                        idempotency_key=key,
                    ),
                    now=NOW + timedelta(minutes=1),
                )

        first = asyncio.create_task(create_manual(uuid4(), 3))
        await asyncio.wait_for(action_staged.wait(), timeout=2)
        competing = asyncio.create_task(create_manual(uuid4(), 4))
        await asyncio.sleep(0.05)
        assert competing.done() is False

        release_stage.set()
        created, was_created = await asyncio.wait_for(first, timeout=2)
        assert was_created is True
        assert created.state == "pending_archive"
        with pytest.raises(SnoozeConflict) as conflict:
            await asyncio.wait_for(competing, timeout=2)
        assert "already snoozed" in str(conflict.value).lower()

        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(EmailSnooze)) == 1
    finally:
        await engine.dispose()


async def test_scheduled_send_now_cancel_and_undo_settle_companion_intent(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)

        send_now_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        cancel_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        undo_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        scheduled_for = NOW + timedelta(days=30)
        async with sessions() as db:
            for outbound_id in (send_now_id, cancel_id):
                outbound = await db.get(OutboundMessage, outbound_id, with_for_update=True)
                outbound.execute_after = scheduled_for
                outbound.next_attempt_at = scheduled_for
                intent = await db.scalar(
                    select(OutboundFollowUpIntent).where(
                        OutboundFollowUpIntent.outbound_message_id == outbound_id
                    )
                )
                intent.next_attempt_at = scheduled_for
            await db.commit()

        changed_at = NOW + timedelta(seconds=5)
        async with sessions() as db:
            send_now = await db.get(OutboundMessage, send_now_id)
            await send_scheduled_outbound_now(
                db,
                user_id=user_id,
                send_id=send_now.send_id,
                now=changed_at,
            )
        async with sessions() as db:
            intent = await db.scalar(select(OutboundFollowUpIntent).where(
                OutboundFollowUpIntent.outbound_message_id == send_now_id
            ))
            assert intent.state == "awaiting_delivery"
            assert intent.next_attempt_at == changed_at

        async with sessions() as db:
            scheduled = await db.get(OutboundMessage, cancel_id)
            await cancel_scheduled_outbound_message(
                db,
                user_id=user_id,
                send_id=scheduled.send_id,
                now=changed_at,
            )
        async with sessions() as db:
            intent = await db.scalar(select(OutboundFollowUpIntent).where(
                OutboundFollowUpIntent.outbound_message_id == cancel_id
            ))
            assert intent.state == "cancelled"
            assert intent.cancelled_at == changed_at

        async with sessions() as db:
            ordinary = await db.get(OutboundMessage, undo_id)
            await undo_outbound_message(
                db,
                user_id=user_id,
                send_id=ordinary.send_id,
                now=changed_at,
            )
        async with sessions() as db:
            intent = await db.scalar(select(OutboundFollowUpIntent).where(
                OutboundFollowUpIntent.outbound_message_id == undo_id
            ))
            assert intent.state == "cancelled"
            assert intent.status_detail == "outbound_cancelled"
    finally:
        await engine.dispose()


async def test_retry_authorized_failure_keeps_intent_recoverable(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)
        outbound_id = await _stage(sessions, user_id=user_id, account_id=account_id)
        async with sessions() as db:
            outbound = await db.get(OutboundMessage, outbound_id, with_for_update=True)
            outbound.state = "failed"
            outbound.failed_at = NOW + timedelta(seconds=20)
            outbound.retry_authorized = True
            outbound.retry_expires_at = NOW + timedelta(hours=1)
            outbound.next_attempt_at = None
            outbound.lease_token = None
            outbound.lease_expires_at = None
            await db.commit()

        await _process_one(NOW + timedelta(minutes=1))
        async with sessions() as db:
            intent = await db.scalar(select(OutboundFollowUpIntent))
            assert intent.state == "awaiting_delivery"
            assert intent.status_detail == "waiting_for_safe_retry"
            assert intent.next_attempt_at == NOW + timedelta(minutes=2)
            assert intent.lease_token is None
        assert await outbound_module.scrub_expired_retry_payloads(
            now=NOW + timedelta(hours=1, seconds=1)
        ) == 1
        async with sessions() as db:
            intent = await db.scalar(select(OutboundFollowUpIntent))
            assert intent.state == "cancelled"
            assert intent.status_detail == "outbound_failed"
    finally:
        await engine.dispose()
