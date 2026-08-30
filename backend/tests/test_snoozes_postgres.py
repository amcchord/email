"""Opt-in disposable-PostgreSQL lifecycle checks for universal snooze.

Set SNOOZE_POSTGRES_TEST_URL to a freshly migrated disposable database. Never
point this at development or production data.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.services.mail_actions as action_module
import backend.services.snoozes as snooze_module
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.mail_action import MailAction
from backend.models.snooze import EmailSnooze
from backend.models.user import User
from backend.schemas.snooze import SnoozeCreateRequest
from backend.services.mail_actions import stage_mail_actions
from backend.services.mail_actions import MailActionValidationError
from backend.services.snoozes import (
    SnoozeConflict,
    SnoozeNotFound,
    _claim_due,
    _process_claim,
    cancel_snooze,
    create_snooze,
    get_snooze,
    reschedule_snooze,
    return_snooze_now,
)


DATABASE_URL = os.getenv("SNOOZE_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires SNOOZE_POSTGRES_TEST_URL for disposable PostgreSQL",
    ),
]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _session_factory():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset_database(engine):
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def _seed_email(
    sessions,
    *,
    suffix="one",
    user_id=None,
    labels=None,
    is_sent=False,
    is_trash=False,
    is_spam=False,
    date=NOW,
    thread_id=None,
):
    async with sessions() as db:
        if user_id is None:
            user = User(username=f"generated-snooze-{suffix}", is_admin=False, is_active=True)
            db.add(user)
            await db.flush()
            user_id = user.id
        account = GoogleAccount(
            user_id=user_id,
            email=f"generated-snooze-{suffix}@example.test",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        email = Email(
            account_id=account.id,
            gmail_message_id=f"generated-snooze-message-{suffix}",
            gmail_thread_id=thread_id or f"generated-snooze-thread-{suffix}",
            subject=f"Generated snooze {suffix}",
            from_address=f"sender-{suffix}@example.test",
            to_addresses=[account.email],
            date=date,
            snippet="Generated lifecycle test; no real mailbox data.",
            labels=list(labels if labels is not None else ["INBOX", "UNREAD"]),
            is_read="UNREAD" not in (labels if labels is not None else ["INBOX", "UNREAD"]),
            is_starred=False,
            is_trash=is_trash,
            is_spam=is_spam,
            is_draft=False,
            is_sent=is_sent,
            mail_action_version=0,
            has_attachments=False,
        )
        db.add(email)
        await db.commit()
        return user_id, account.id, email.id


def _request(email_id, *, key=None, wake_at=None, condition="always"):
    return SnoozeCreateRequest(
        email_id=email_id,
        wake_at=wake_at or NOW + timedelta(days=1),
        time_zone="America/New_York",
        condition=condition,
        idempotency_key=key or uuid4(),
    )


@pytest.fixture(autouse=True)
def _use_disposable_sessions(monkeypatch):
    if not DATABASE_URL:
        return
    engine, sessions = _session_factory()
    monkeypatch.setattr(snooze_module, "async_session", sessions)

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(snooze_module, "_publish_snooze_event", no_publish)
    monkeypatch.setattr(snooze_module, "try_enqueue_mail_action_drain", no_publish)
    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)
    return engine, sessions


async def _mark_action_applied(sessions, action_id, at):
    async with sessions() as db:
        action = await db.get(MailAction, action_id, with_for_update=True)
        action.state = "applied"
        action.applied_at = at
        action.next_attempt_at = None
        action.lease_token = None
        action.lease_expires_at = None
        action.updated_at = at
        await db.commit()


async def _make_row_due(sessions, row_id, at):
    async with sessions() as db:
        row = await db.get(EmailSnooze, row_id, with_for_update=True)
        row.next_attempt_at = at
        row.lease_token = None
        row.lease_expires_at = None
        await db.commit()


async def _process_only_claim(at):
    claimed = await _claim_due(at, 20)
    assert len(claimed) == 1
    await _process_claim(claimed[0][0], claimed[0][1], at)


async def test_archive_activation_exact_due_and_return_lifecycle(_use_disposable_sessions):
    engine, sessions = _use_disposable_sessions
    try:
        await _reset_database(engine)
        user_id, _account_id, email_id = await _seed_email(sessions)
        key = uuid4()
        request = _request(email_id, key=key)

        async with sessions() as db:
            first, created = await create_snooze(db, user_id=user_id, request=request, now=NOW)
        async with sessions() as db:
            duplicate, duplicate_created = await create_snooze(
                db, user_id=user_id, request=request, now=NOW
            )

        assert created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert first.state == "pending_archive"
        assert first.archive_action_request_id is not None
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(EmailSnooze)) == 1
            assert await db.scalar(select(func.count()).select_from(MailAction)) == 1
            email = await db.get(Email, email_id)
            row = await db.scalar(select(EmailSnooze))
            archive_action_id = row.archive_action_id
            wake_at = row.wake_at
            assert "INBOX" not in email.labels

        await _mark_action_applied(sessions, archive_action_id, NOW + timedelta(seconds=11))
        await _make_row_due(sessions, row.id, NOW + timedelta(seconds=11))
        await _process_only_claim(NOW + timedelta(seconds=11))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row.id)
            assert row.state == "scheduled"

        assert await _claim_due(wake_at - timedelta(microseconds=1), 20) == []
        await _process_only_claim(wake_at)
        async with sessions() as db:
            row = await db.get(EmailSnooze, row.id)
            email = await db.get(Email, email_id)
            assert row.state == "pending_return"
            assert row.return_action_id is not None
            assert "INBOX" in email.labels
            return_action_id = row.return_action_id

        await _mark_action_applied(sessions, return_action_id, wake_at + timedelta(seconds=11))
        await _make_row_due(sessions, row.id, wake_at + timedelta(seconds=11))
        await _process_only_claim(wake_at + timedelta(seconds=11))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row.id)
            assert row.state == "returned"
            assert row.returned_at == wake_at + timedelta(seconds=11)
    finally:
        await engine.dispose()


async def test_cancel_after_archive_restores_inbox_before_terminal_state(
    _use_disposable_sessions,
):
    engine, sessions = _use_disposable_sessions
    try:
        await _reset_database(engine)
        user_id, _account_id, email_id = await _seed_email(sessions, suffix="cancel")
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(email_id), now=NOW
            )
            row_id = (await db.scalar(select(EmailSnooze.id)))
        async with sessions() as db:
            response = await cancel_snooze(
                db, user_id=user_id, public_id=response.id, now=NOW + timedelta(seconds=1)
            )
        assert response.state == "pending_return"
        assert response.status_detail == "cancelling"
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            email = await db.get(Email, email_id)
            assert "INBOX" in email.labels
            archive_action_id = row.archive_action_id
            return_action_id = row.return_action_id

        await _mark_action_applied(sessions, archive_action_id, NOW + timedelta(seconds=11))
        await _mark_action_applied(sessions, return_action_id, NOW + timedelta(seconds=12))
        await _make_row_due(sessions, row_id, NOW + timedelta(seconds=12))
        await _process_only_claim(NOW + timedelta(seconds=12))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            assert row.state == "cancelled"
            assert row.cancelled_at == NOW + timedelta(seconds=12)
    finally:
        await engine.dispose()


async def test_cancel_before_archive_staging_never_orphans_inbox(
    _use_disposable_sessions, monkeypatch
):
    engine, sessions = _use_disposable_sessions
    try:
        await _reset_database(engine)
        user_id, _account_id, email_id = await _seed_email(sessions, suffix="early-cancel")

        async def generated_outage(*_args, **_kwargs):
            raise ConnectionError("generated queue boundary")

        original_ensure = snooze_module._ensure_action
        monkeypatch.setattr(snooze_module, "_ensure_action", generated_outage)
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(email_id), now=NOW
            )
            cancelled = await cancel_snooze(
                db, user_id=user_id, public_id=response.id, now=NOW + timedelta(seconds=1)
            )
        assert cancelled.state == "cancelled"
        async with sessions() as db:
            email = await db.get(Email, email_id)
            assert "INBOX" in email.labels
            assert await db.scalar(select(func.count()).select_from(MailAction)) == 0

        # Model the narrow race where the original create request resumes only
        # after cancellation committed. The late archive must automatically
        # create its ordered inverse and put lifecycle monitoring back in place.
        monkeypatch.setattr(snooze_module, "_ensure_action", original_ensure)
        async with sessions() as db:
            row_id = await db.scalar(select(EmailSnooze.id))
        await original_ensure(row_id, purpose="archive", now=NOW + timedelta(seconds=2))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            email = await db.get(Email, email_id)
            actions = list((await db.execute(
                select(MailAction).order_by(MailAction.sequence)
            )).scalars().all())
            assert row.state == "pending_return"
            assert row.status_detail == "cancelling"
            assert [action.action for action in actions] == ["archive", "unarchive"]
            assert "INBOX" in email.labels
    finally:
        await engine.dispose()


async def test_if_no_reply_dismisses_and_never_stages_return(_use_disposable_sessions):
    engine, sessions = _use_disposable_sessions
    try:
        await _reset_database(engine)
        user_id, account_id, email_id = await _seed_email(
            sessions,
            suffix="sent",
            labels=["SENT"],
            is_sent=True,
            thread_id="generated-shared-thread",
        )
        wake_at = NOW + timedelta(hours=1)
        async with sessions() as db:
            response, _ = await create_snooze(
                db,
                user_id=user_id,
                request=_request(
                    email_id, wake_at=wake_at, condition="if_no_reply"
                ),
                now=NOW,
            )
            reply = Email(
                account_id=account_id,
                gmail_message_id="generated-reply-message",
                gmail_thread_id="generated-shared-thread",
                from_address="reply@example.test",
                to_addresses=["generated-snooze-sent@example.test"],
                date=NOW + timedelta(minutes=10),
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                has_attachments=False,
            )
            db.add(reply)
            await db.commit()

        await _process_only_claim(wake_at)
        async with sessions() as db:
            row = await db.scalar(select(EmailSnooze))
            assert row.state == "dismissed"
            assert row.status_detail == "reply_received"
            assert row.return_action_id is None
            assert await db.scalar(select(func.count()).select_from(MailAction)) == 0
    finally:
        await engine.dispose()


async def test_trash_and_newer_manual_placement_are_never_overridden(
    _use_disposable_sessions,
):
    engine, sessions = _use_disposable_sessions
    try:
        await _reset_database(engine)
        user_id, _account_id, email_id = await _seed_email(
            sessions, suffix="manual", labels=["SENT"], is_sent=True
        )
        wake_at = NOW + timedelta(hours=1)
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(email_id, wake_at=wake_at), now=NOW
            )
            await stage_mail_actions(
                db,
                user_id=user_id,
                email_ids=[email_id],
                action="archive",
                idempotency_key=uuid4(),
                now=NOW + timedelta(minutes=1),
            )
        await _process_only_claim(wake_at)
        async with sessions() as db:
            row = await db.scalar(select(EmailSnooze))
            assert row.state == "dismissed"
            assert row.status_detail == "newer_manual_action"
            assert row.return_action_id is None

        # A new snooze may be created after terminalization, but trash remains
        # an unconditional fail-closed boundary for both create and wake.
        async with sessions() as db:
            email = await db.get(Email, email_id, with_for_update=True)
            email.is_trash = True
            email.labels = ["TRASH"]
            await db.commit()
            with pytest.raises(SnoozeConflict, match="Trash and spam"):
                await create_snooze(
                    db,
                    user_id=user_id,
                    request=_request(email_id, key=uuid4()),
                    now=NOW,
                )
            with pytest.raises(MailActionValidationError, match="dedicated actions"):
                await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=[email_id],
                    action="unarchive",
                    idempotency_key=uuid4(),
                    now=NOW + timedelta(minutes=2),
                )
    finally:
        await engine.dispose()


async def test_exact_owner_scope_and_concurrent_claim_are_fail_closed(
    _use_disposable_sessions,
):
    engine, sessions = _use_disposable_sessions
    try:
        await _reset_database(engine)
        first_user, _account_id, email_id = await _seed_email(
            sessions, suffix="owner", labels=["SENT"], is_sent=True
        )
        second_user, _second_account, _second_email = await _seed_email(
            sessions, suffix="other", labels=["SENT"], is_sent=True
        )
        wake_at = NOW + timedelta(hours=1)
        async with sessions() as db:
            response, _ = await create_snooze(
                db,
                user_id=first_user,
                request=_request(email_id, wake_at=wake_at),
                now=NOW,
            )
        async with sessions() as db:
            with pytest.raises(SnoozeNotFound):
                await get_snooze(db, user_id=second_user, public_id=response.id)

        first, second = await asyncio.gather(
            _claim_due(wake_at, 20), _claim_due(wake_at, 20)
        )
        assert sorted([len(first), len(second)]) == [0, 1]
    finally:
        await engine.dispose()


async def test_reschedule_and_return_now_are_idempotent(_use_disposable_sessions):
    engine, sessions = _use_disposable_sessions
    try:
        await _reset_database(engine)
        user_id, _account_id, email_id = await _seed_email(
            sessions, suffix="return", labels=["SENT"], is_sent=True
        )
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(email_id), now=NOW
            )
            moved = await reschedule_snooze(
                db,
                user_id=user_id,
                public_id=response.id,
                wake_at=NOW + timedelta(days=2),
                time_zone="UTC",
                now=NOW + timedelta(seconds=1),
            )
            first_return = await return_snooze_now(
                db,
                user_id=user_id,
                public_id=response.id,
                now=NOW + timedelta(seconds=2),
            )
            second_return = await return_snooze_now(
                db,
                user_id=user_id,
                public_id=response.id,
                now=NOW + timedelta(seconds=3),
            )
        assert moved.time_zone == "UTC"
        assert first_return.state == "pending_return"
        assert second_return.id == first_return.id
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(MailAction)) == 1
            action = await db.scalar(select(MailAction))
            assert action.action == "unarchive"
    finally:
        await engine.dispose()
