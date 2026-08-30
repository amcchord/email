"""Disposable-PostgreSQL invariants for conversation-scoped universal snooze."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.services.mail_actions as action_module
import backend.services.snoozes as snooze_module
from backend.models.account import GoogleAccount, SyncStatus
from backend.models.email import Email
from backend.models.mail_action import MailAction
from backend.models.snooze import EmailSnooze
from backend.models.user import User
from backend.schemas.snooze import SnoozeCreateRequest
from backend.services.mail_actions import stage_mail_actions
from backend.services.snoozes import (
    SnoozeConflict,
    SnoozeNotFound,
    _claim_due,
    _process_claim,
    cancel_snooze,
    create_snooze,
    get_snooze,
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


@pytest.fixture(autouse=True)
def _disposable_sessions(monkeypatch):
    if not DATABASE_URL:
        return
    engine, sessions = _session_factory()
    monkeypatch.setattr(snooze_module, "async_session", sessions)

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(snooze_module, "_publish_snooze_event", noop)
    monkeypatch.setattr(snooze_module, "try_enqueue_mail_action_drain", noop)
    monkeypatch.setattr(action_module, "_publish_action_event", noop)
    return engine, sessions


async def _reset(engine):
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def _seed_account(sessions, suffix="one"):
    async with sessions() as db:
        user = User(username=f"generated-snooze-{suffix}", is_active=True, is_admin=False)
        db.add(user)
        await db.flush()
        account = GoogleAccount(
            user_id=user.id,
            email=f"generated-{suffix}@example.test",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        await db.commit()
        return user.id, account.id


async def _add_email(
    sessions,
    *,
    account_id,
    suffix,
    thread="generated-thread",
    labels=None,
    is_sent=False,
    is_trash=False,
    date=NOW,
):
    labels = list(labels if labels is not None else ["INBOX", "UNREAD"])
    async with sessions() as db:
        email = Email(
            account_id=account_id,
            gmail_message_id=f"generated-message-{suffix}",
            gmail_thread_id=thread,
            subject="Generated conversation",
            from_address=f"sender-{suffix}@example.test",
            to_addresses=["recipient@example.test"],
            date=date,
            snippet="Generated test data only.",
            labels=labels,
            is_read="UNREAD" not in labels,
            is_starred=False,
            is_trash=is_trash,
            is_spam=False,
            is_draft=False,
            is_sent=is_sent,
            mail_action_version=0,
            has_attachments=False,
        )
        db.add(email)
        await db.commit()
        return email.id


def _request(email_id, *, key=None, wake_at=None, condition="always"):
    return SnoozeCreateRequest(
        email_id=email_id,
        wake_at=wake_at or NOW + timedelta(hours=1),
        time_zone="America/New_York",
        condition=condition,
        idempotency_key=key or uuid4(),
    )


async def _actions(sessions, action_name=None):
    async with sessions() as db:
        statement = select(MailAction).order_by(MailAction.email_id, MailAction.sequence)
        if action_name:
            statement = statement.where(MailAction.action == action_name)
        return list((await db.execute(statement)).scalars().all())


async def _mark_applied(sessions, actions, at):
    async with sessions() as db:
        for source in actions:
            action = await db.get(MailAction, source.id, with_for_update=True)
            action.state = "applied"
            action.applied_at = at
            action.next_attempt_at = None
            action.lease_token = None
            action.lease_expires_at = None
            action.updated_at = at
        await db.commit()


async def _due_row(sessions, row_id, at):
    async with sessions() as db:
        row = await db.get(EmailSnooze, row_id, with_for_update=True)
        row.next_attempt_at = at
        row.lease_token = None
        row.lease_expires_at = None
        await db.commit()


async def _process_one(at):
    claimed = await _claim_due(at, 20)
    assert len(claimed) == 1
    await _process_claim(claimed[0][0], claimed[0][1], at)


async def _activate_archive(sessions, row_id, at):
    archive = await _actions(sessions, "archive")
    await _mark_applied(sessions, archive, at)
    await _due_row(sessions, row_id, at)
    await _process_one(at)


async def test_create_is_one_active_conversation_and_archives_all_inbox_messages(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions)
        first = await _add_email(sessions, account_id=account_id, suffix="first")
        second = await _add_email(
            sessions, account_id=account_id, suffix="second", date=NOW + timedelta(minutes=1)
        )
        key = uuid4()
        async with sessions() as db:
            response, created = await create_snooze(
                db, user_id=user_id, request=_request(first, key=key), now=NOW
            )
            replay, replay_created = await create_snooze(
                db, user_id=user_id, request=_request(first, key=key), now=NOW + timedelta(hours=2)
            )
            with pytest.raises(SnoozeConflict, match="conversation"):
                await create_snooze(
                    db, user_id=user_id, request=_request(second), now=NOW
                )
        assert created is True and replay_created is False
        assert replay.id == response.id
        assert response.conversation_message_count == 2
        assert response.originally_in_inbox is True
        archive = await _actions(sessions, "archive")
        assert {action.email_id for action in archive} == {first, second}
        assert len({action.request_id for action in archive}) == 1
        async with sessions() as db:
            rows = list((await db.execute(select(Email).order_by(Email.id))).scalars())
            assert all("INBOX" not in email.labels for email in rows)
    finally:
        await engine.dispose()


async def test_sent_return_now_adds_inbox_but_cancel_preserves_non_inbox_placement(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "sent")
        sent = await _add_email(
            sessions, account_id=account_id, suffix="sent", labels=["SENT"], is_sent=True
        )
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(sent), now=NOW
            )
            returned = await return_snooze_now(
                db, user_id=user_id, public_id=response.id, now=NOW + timedelta(seconds=1)
            )
        assert returned.state == "pending_return"
        assert returned.originally_in_inbox is False
        returns = await _actions(sessions, "unarchive")
        assert [action.email_id for action in returns] == [sent]
        async with sessions() as db:
            email = await db.get(Email, sent)
            assert "INBOX" in email.labels

        # A second conversation proves cancel has the same placement contract.
        other = await _add_email(
            sessions,
            account_id=account_id,
            suffix="sent-other",
            thread="generated-other-thread",
            labels=["SENT"],
            is_sent=True,
        )
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(other), now=NOW
            )
            cancelled = await cancel_snooze(
                db, user_id=user_id, public_id=response.id, now=NOW + timedelta(seconds=1)
            )
        assert cancelled.state == "cancelled"
        async with sessions() as db:
            email = await db.get(Email, other)
            assert "INBOX" not in email.labels
    finally:
        await engine.dispose()


async def test_inbox_undo_uses_exact_bulk_archive_undo_without_inverse_actions(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "undo")
        first = await _add_email(sessions, account_id=account_id, suffix="undo-first")
        second = await _add_email(sessions, account_id=account_id, suffix="undo-second")
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(first), now=NOW
            )
            returned = await return_snooze_now(
                db, user_id=user_id, public_id=response.id, now=NOW + timedelta(seconds=1)
            )
        assert returned.state == "returned"
        actions = await _actions(sessions)
        assert len(actions) == 2
        assert {action.state for action in actions} == {"cancelled"}
        assert {action.action for action in actions} == {"archive"}
        async with sessions() as db:
            emails = list((await db.execute(select(Email))).scalars())
            assert all("INBOX" in email.labels for email in emails)
    finally:
        await engine.dispose()


async def test_due_return_is_ordered_before_later_manual_archive_and_manual_wins(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "race")
        email_id = await _add_email(sessions, account_id=account_id, suffix="race")
        wake = NOW + timedelta(hours=1)
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(email_id, wake_at=wake), now=NOW
            )
            row_id = await db.scalar(select(EmailSnooze.id))
        await _activate_archive(sessions, row_id, NOW + timedelta(seconds=11))

        await _process_one(wake)
        return_actions = await _actions(sessions, "unarchive")
        assert len(return_actions) == 1
        async with sessions() as db:
            _manual, _ = await stage_mail_actions(
                db,
                user_id=user_id,
                email_ids=[email_id],
                action="archive",
                idempotency_key=uuid4(),
                now=wake + timedelta(microseconds=1),
            )
        all_actions = await _actions(sessions)
        assert [action.sequence for action in all_actions] == [1, 2, 3]
        assert all_actions[1].action == "unarchive"
        assert all_actions[2].action == "archive"
        await _mark_applied(sessions, return_actions, wake + timedelta(seconds=11))
        await _due_row(sessions, row_id, wake + timedelta(seconds=11))
        await _process_one(wake + timedelta(seconds=11))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            email = await db.get(Email, email_id)
            assert row.state == "dismissed"
            assert row.status_detail == "newer_manual_action"
            assert "INBOX" not in email.labels
    finally:
        await engine.dispose()


async def test_protected_conversation_member_is_filtered_while_other_returns(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "protected")
        safe = await _add_email(sessions, account_id=account_id, suffix="safe")
        protected = await _add_email(sessions, account_id=account_id, suffix="protected")
        wake = NOW + timedelta(hours=1)
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(safe, wake_at=wake), now=NOW
            )
            row_id = await db.scalar(select(EmailSnooze.id))
        await _activate_archive(sessions, row_id, NOW + timedelta(seconds=11))
        async with sessions() as db:
            email = await db.get(Email, protected, with_for_update=True)
            email.is_trash = True
            email.labels = ["TRASH"]
            await db.commit()
        await _process_one(wake)
        returns = await _actions(sessions, "unarchive")
        assert [action.email_id for action in returns] == [safe]
        await _mark_applied(sessions, returns, wake + timedelta(seconds=11))
        await _due_row(sessions, row_id, wake + timedelta(seconds=11))
        await _process_one(wake + timedelta(seconds=11))
        async with sessions() as db:
            safe_email = await db.get(Email, safe)
            protected_email = await db.get(Email, protected)
            row = await db.get(EmailSnooze, row_id)
            assert row.state == "returned"
            assert "INBOX" in safe_email.labels
            assert protected_email.is_trash is True
            assert "INBOX" not in protected_email.labels
    finally:
        await engine.dispose()


async def test_partial_bulk_failure_waits_for_active_items_then_releases_conversation(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "partial")
        first = await _add_email(sessions, account_id=account_id, suffix="partial-first")
        await _add_email(sessions, account_id=account_id, suffix="partial-second")
        async with sessions() as db:
            await create_snooze(db, user_id=user_id, request=_request(first), now=NOW)
            row_id = await db.scalar(select(EmailSnooze.id))
        archive = await _actions(sessions, "archive")
        async with sessions() as db:
            applied = await db.get(MailAction, archive[0].id, with_for_update=True)
            failed = await db.get(MailAction, archive[1].id, with_for_update=True)
            applied.state = "staged"
            failed.state = "failed"
            failed.failed_at = NOW + timedelta(seconds=11)
            failed.error_message = "Generated provider rejection"
            await db.commit()
        await _due_row(sessions, row_id, NOW + timedelta(seconds=11))
        await _process_one(NOW + timedelta(seconds=11))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            assert row.state == "pending_archive"
        await _mark_applied(sessions, [archive[0]], NOW + timedelta(seconds=12))
        await _due_row(sessions, row_id, NOW + timedelta(seconds=12))
        await _process_one(NOW + timedelta(seconds=12))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            assert row.state == "failed"
            assert row.status_detail == "archive_failed"
            assert row.error_message == "Generated provider rejection"
    finally:
        await engine.dispose()


async def test_if_no_reply_waits_for_post_wake_sync_then_dismisses_reply(
    _disposable_sessions,
):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "reply")
        sent = await _add_email(
            sessions,
            account_id=account_id,
            suffix="reply-sent",
            labels=["SENT"],
            is_sent=True,
        )
        wake = NOW + timedelta(hours=1)
        async with sessions() as db:
            await create_snooze(
                db,
                user_id=user_id,
                request=_request(sent, wake_at=wake, condition="if_no_reply"),
                now=NOW,
            )
            row_id = await db.scalar(select(EmailSnooze.id))
            db.add(SyncStatus(
                account_id=account_id,
                last_incremental_sync=wake - timedelta(seconds=1),
                status="idle",
            ))
            await db.commit()
        await _process_one(wake)
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            assert row.state == "scheduled"
            assert row.status_detail == "waiting_for_reply_sync"
            reply = Email(
                account_id=account_id,
                gmail_message_id="generated-reply",
                gmail_thread_id="generated-thread",
                from_address="reply@example.test",
                date=NOW + timedelta(minutes=30),
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                mail_action_version=0,
                has_attachments=False,
            )
            db.add(reply)
            status = await db.scalar(select(SyncStatus).where(SyncStatus.account_id == account_id))
            status.last_incremental_sync = wake + timedelta(seconds=1)
            row.next_attempt_at = wake + timedelta(seconds=1)
            await db.commit()
        await _process_one(wake + timedelta(seconds=1))
        async with sessions() as db:
            row = await db.get(EmailSnooze, row_id)
            assert row.state == "dismissed"
            assert row.status_detail == "reply_received"
            assert await db.scalar(
                select(func.count()).select_from(MailAction).where(MailAction.action == "unarchive")
            ) == 0
    finally:
        await engine.dispose()


async def test_owner_scope_and_concurrent_claim_are_fail_closed(_disposable_sessions):
    engine, sessions = _disposable_sessions
    try:
        await _reset(engine)
        user_id, account_id = await _seed_account(sessions, "owner")
        other_user, _ = await _seed_account(sessions, "other")
        sent = await _add_email(
            sessions, account_id=account_id, suffix="owner", labels=["SENT"], is_sent=True
        )
        wake = NOW + timedelta(hours=1)
        async with sessions() as db:
            response, _ = await create_snooze(
                db, user_id=user_id, request=_request(sent, wake_at=wake), now=NOW
            )
            with pytest.raises(SnoozeNotFound):
                await get_snooze(db, user_id=other_user, public_id=response.id)
        first, second = await asyncio.gather(_claim_due(wake, 20), _claim_due(wake, 20))
        assert sorted([len(first), len(second)]) == [0, 1]
    finally:
        await engine.dispose()
