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
from backend.models.email import Email, EmailLabel
from backend.models.mail_action import MailAction
from backend.models.user import User
from backend.services.mail_actions import (
    MailActionConflict,
    MailActionNotFound,
    MailActionValidationError,
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


async def test_label_move_expands_conversation_and_replays_exact_operation():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        async with sessions() as db:
            user = User(username="generated-labels", is_admin=False, is_active=True)
            db.add(user)
            await db.flush()
            account = GoogleAccount(
                user_id=user.id,
                email="generated-labels@example.test",
                is_active=True,
            )
            db.add(account)
            await db.flush()
            label = EmailLabel(
                account_id=account.id,
                gmail_label_id="Label_work",
                name="Work",
                label_type="user",
            )
            db.add(label)
            messages = []
            for suffix in ("first", "second"):
                is_inbox = suffix == "first"
                email = Email(
                    account_id=account.id,
                    gmail_message_id=f"generated-label-{suffix}",
                    gmail_thread_id="generated-label-thread",
                    labels=["INBOX", "UNREAD"] if is_inbox else ["SENT"],
                    is_read=not is_inbox,
                    is_starred=False,
                    is_trash=False,
                    is_spam=False,
                    is_draft=False,
                    is_sent=not is_inbox,
                    mail_action_version=0,
                    has_attachments=False,
                )
                db.add(email)
                messages.append(email)
            await db.commit()
            user_id = user.id
            label_id = label.id
            first_id = messages[0].id

        key = uuid4()
        async with sessions() as db:
            created_actions, created = await stage_mail_actions(
                db,
                user_id=user_id,
                email_ids=[first_id],
                action="move_to_label",
                label_id=label_id,
                idempotency_key=key,
                now=NOW,
            )
        assert created is True
        assert len(created_actions) == 2
        assert all(action.add_labels == ["Label_work"] for action in created_actions)
        assert all(action.remove_labels == ["INBOX"] for action in created_actions)

        # Exact replay is resolved before mutable catalog and mailbox state.
        # This models a lost response after the accepted move removed INBOX,
        # followed by authoritative label-sync deletion.
        async with sessions() as db:
            await db.execute(
                text("DELETE FROM email_labels WHERE id = :label_id"),
                {"label_id": label_id},
            )
            await db.commit()
        async with sessions() as db:
            replayed, replay_created = await stage_mail_actions(
                db,
                user_id=user_id,
                email_ids=[first_id],
                action="move_to_label",
                label_id=label_id,
                idempotency_key=key,
                now=NOW,
            )
            assert replay_created is False
            assert [action.id for action in replayed] == [
                action.id for action in created_actions
            ]
            with pytest.raises(MailActionConflict):
                await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=[first_id],
                    action="move_to_label",
                    label_id=label_id + 1,
                    idempotency_key=key,
                    now=NOW,
                )
            await db.rollback()

        async with sessions() as db:
            stored = list((await db.execute(
                select(Email)
                .where(Email.gmail_thread_id == "generated-label-thread")
                .order_by(Email.id)
            )).scalars().all())
            assert len(stored) == 2
            assert all("Label_work" in email.labels for email in stored)
            assert all("INBOX" not in email.labels for email in stored)
            assert "SENT" in stored[1].labels
    finally:
        await engine.dispose()


async def test_generic_conversation_scope_expands_exact_members_and_replays_snapshot():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        async with sessions() as db:
            user = User(username="generated-conversation-actions", is_admin=False, is_active=True)
            db.add(user)
            await db.flush()
            account = GoogleAccount(
                user_id=user.id,
                email="generated-conversation-actions@example.test",
                is_active=True,
            )
            db.add(account)
            await db.flush()
            first = Email(
                account_id=account.id,
                gmail_message_id="generated-conversation-action-first",
                gmail_thread_id="generated-conversation-action-thread",
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
            second = Email(
                account_id=account.id,
                gmail_message_id="generated-conversation-action-second",
                gmail_thread_id="generated-conversation-action-thread",
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
            db.add_all([first, second])
            await db.commit()
            user_id = user.id
            account_id = account.id
            first_id = first.id

        key = uuid4()
        async with sessions() as db:
            accepted, created = await stage_mail_actions(
                db,
                user_id=user_id,
                email_ids=[first_id],
                action="archive",
                scope="conversations",
                idempotency_key=key,
                now=NOW,
            )
        assert created is True
        assert len(accepted) == 2
        accepted_ids = [action.id for action in accepted]

        # A later synchronized reply belongs to a future user intent. Replaying
        # the lost response must return the exact originally accepted snapshot.
        async with sessions() as db:
            db.add(Email(
                account_id=account_id,
                gmail_message_id="generated-conversation-action-later",
                gmail_thread_id="generated-conversation-action-thread",
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                mail_action_version=0,
                has_attachments=False,
            ))
            await db.commit()

        async with sessions() as db:
            replay, replay_created = await stage_mail_actions(
                db,
                user_id=user_id,
                email_ids=[first_id],
                action="archive",
                scope="conversations",
                idempotency_key=key,
                now=NOW,
            )
            assert replay_created is False
            assert [action.id for action in replay] == accepted_ids
            with pytest.raises(MailActionConflict):
                await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=[first_id],
                    action="archive",
                    scope="messages",
                    idempotency_key=key,
                    now=NOW,
                )
            await db.rollback()

        async with sessions() as db:
            messages = list((await db.execute(
                select(Email)
                .where(Email.account_id == account_id)
                .order_by(Email.id)
            )).scalars().all())
            assert ["INBOX" in email.labels for email in messages] == [False, False, True]
    finally:
        await engine.dispose()


async def test_label_action_rejects_system_and_cross_account_targets_atomically():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        async with sessions() as db:
            user = User(username="generated-label-scope", is_admin=False, is_active=True)
            db.add(user)
            await db.flush()
            accounts = []
            emails = []
            for suffix in ("first", "second"):
                account = GoogleAccount(
                    user_id=user.id,
                    email=f"generated-label-{suffix}@example.test",
                    is_active=True,
                )
                db.add(account)
                await db.flush()
                accounts.append(account)
                email = Email(
                    account_id=account.id,
                    gmail_message_id=f"generated-label-scope-{suffix}",
                    gmail_thread_id=f"generated-label-scope-thread-{suffix}",
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
                db.add(email)
                emails.append(email)
            system_label = EmailLabel(
                account_id=accounts[0].id,
                gmail_label_id="CATEGORY_UPDATES",
                name="Updates",
                label_type="system",
            )
            user_label = EmailLabel(
                account_id=accounts[0].id,
                gmail_label_id="Label_work",
                name="Work",
                label_type="user",
            )
            db.add_all([system_label, user_label])
            await db.commit()
            user_id = user.id
            email_ids = [email.id for email in emails]
            system_label_id = system_label.id
            user_label_id = user_label.id

        async with sessions() as db:
            with pytest.raises(MailActionValidationError, match="Only user labels"):
                await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=[email_ids[0]],
                    action="add_label",
                    label_id=system_label_id,
                    idempotency_key=uuid4(),
                    now=NOW,
                )
            await db.rollback()
            with pytest.raises(MailActionValidationError, match="one account"):
                await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=email_ids,
                    action="add_label",
                    label_id=user_label_id,
                    idempotency_key=uuid4(),
                    now=NOW,
                )
            await db.rollback()

        async with sessions() as db:
            non_inbox = await db.get(Email, email_ids[0])
            non_inbox.labels = ["Label_source"]
            await db.commit()
        async with sessions() as db:
            with pytest.raises(MailActionValidationError, match="Inbox conversations"):
                await stage_mail_actions(
                    db,
                    user_id=user_id,
                    email_ids=[email_ids[0]],
                    action="move_to_label",
                    label_id=user_label_id,
                    idempotency_key=uuid4(),
                    now=NOW,
                )
            await db.rollback()

        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(MailAction)) == 0
            stored = list((await db.execute(select(Email).order_by(Email.id))).scalars().all())
            assert all(email.mail_action_version == 0 for email in stored)
            assert stored[0].labels == ["Label_source"]
            assert stored[1].labels == ["INBOX"]
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
