"""Disposable-PostgreSQL integration checks for the durable mail-action outbox.

These tests are deliberately opt-in so the normal unit suite never reaches a
developer or production database. Set MAIL_ACTION_POSTGRES_TEST_URL to a
freshly migrated disposable database to run them.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.services.mail_actions as action_module
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.mail_action import MailAction
from backend.models.user import User
from backend.services.mail_actions import (
    MailActionConflict,
    MailActionNotFound,
    _claim_due_actions,
    get_mail_action_operation_by_idempotency,
    stage_mail_actions,
    undo_mail_action_operation,
)


DATABASE_URL = os.getenv("MAIL_ACTION_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires MAIL_ACTION_POSTGRES_TEST_URL for a disposable PostgreSQL database",
    ),
]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _session_factory():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset_database(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def _seed_email(session_factory, *, suffix: str = "one") -> tuple[int, int, int]:
    async with session_factory() as db:
        user = User(username=f"generated-{suffix}", is_admin=False, is_active=True)
        db.add(user)
        await db.flush()
        account = GoogleAccount(
            user_id=user.id,
            email=f"generated-{suffix}@example.test",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        email = Email(
            account_id=account.id,
            gmail_message_id=f"generated-message-{suffix}",
            gmail_thread_id=f"generated-thread-{suffix}",
            labels=["INBOX", "UNREAD"],
            is_read=False,
            is_starred=False,
            is_trash=False,
            is_spam=False,
            is_draft=False,
            is_sent=False,
            mail_action_version=0,
            has_attachments=False,
        )
        db.add(email)
        await db.commit()
        return user.id, account.id, email.id


@pytest.fixture(autouse=True)
def _disable_action_notifications(monkeypatch):
    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)


async def test_concurrent_idempotent_stage_creates_one_operation():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, _account_id, email_id = await _seed_email(sessions)
        key = uuid4()

        async def submit():
            async with sessions() as db:
                return await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=[email_id],
                    action="archive",
                    idempotency_key=key,
                    now=NOW,
                )

        first, second = await asyncio.gather(submit(), submit())

        assert sorted((first[1], second[1])) == [False, True]
        assert first[0][0].request_id == second[0][0].request_id
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(MailAction)) == 1
            email = await db.get(Email, email_id)
            assert email.mail_action_version == 1
            assert "INBOX" not in email.labels
    finally:
        await engine.dispose()


async def test_concurrent_actions_receive_strict_sequences_and_fold_intent():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, _account_id, email_id = await _seed_email(sessions)

        async def submit(action):
            async with sessions() as db:
                return await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=[email_id],
                    action=action,
                    idempotency_key=uuid4(),
                    now=NOW,
                )

        await asyncio.gather(submit("star"), submit("mark_read"))

        async with sessions() as db:
            actions = list((await db.execute(
                select(MailAction).where(MailAction.email_id == email_id).order_by(MailAction.sequence)
            )).scalars().all())
            email = await db.get(Email, email_id)
            assert [action.sequence for action in actions] == [1, 2]
            assert email.mail_action_version == 2
            assert email.is_starred is True
            assert email.is_read is True
            assert set(email.labels) == {"INBOX", "STARRED"}
    finally:
        await engine.dispose()


async def test_mixed_ownership_is_atomic_and_idempotency_lookup_is_user_scoped():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        first_user, _first_account, first_email = await _seed_email(sessions, suffix="first")
        second_user, _second_account, second_email = await _seed_email(sessions, suffix="second")

        async with sessions() as db:
            with pytest.raises(MailActionNotFound):
                await stage_mail_actions(
                    db,
                    user_id=first_user,
                    email_ids=[first_email, second_email],
                    action="archive",
                    idempotency_key=uuid4(),
                    now=NOW,
                )
            await db.rollback()

        key = uuid4()
        async with sessions() as db:
            await stage_mail_actions(
                db,
                user_id=first_user,
                email_ids=[first_email],
                action="archive",
                idempotency_key=key,
                now=NOW,
            )
        async with sessions() as db:
            with pytest.raises(MailActionNotFound):
                await get_mail_action_operation_by_idempotency(
                    db,
                    user_id=second_user,
                    idempotency_key=key,
                )
            actions = await get_mail_action_operation_by_idempotency(
                db,
                user_id=first_user,
                idempotency_key=key,
            )
            assert len(actions) == 1
            assert await db.scalar(select(func.count()).select_from(MailAction)) == 1
            second = await db.get(Email, second_email)
            assert second.mail_action_version == 0
            assert "INBOX" in second.labels
    finally:
        await engine.dispose()


async def test_claim_and_undo_race_has_one_winner():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, account_id, email_id = await _seed_email(sessions)
        key = uuid4()
        async with sessions() as db:
            actions, _created = await stage_mail_actions(
                db,
                user_id=user_id,
                email_ids=[email_id],
                action="archive",
                idempotency_key=key,
                now=NOW,
            )
            request_id = actions[0].request_id

        async def claim():
            async with sessions() as db:
                return len(await _claim_due_actions(
                    db,
                    account_id=account_id,
                    now=NOW + timedelta(seconds=11),
                    limit=10,
                ))

        async def undo():
            async with sessions() as db:
                try:
                    result = await undo_mail_action_operation(
                        db,
                        user_id=user_id,
                        request_id=request_id,
                        now=NOW + timedelta(seconds=5),
                    )
                    return result[0].state
                except MailActionConflict:
                    return "conflict"

        claimed, undo_state = await asyncio.gather(claim(), undo())
        assert (claimed, undo_state) in {(1, "conflict"), (0, "cancelled")}
    finally:
        await engine.dispose()
