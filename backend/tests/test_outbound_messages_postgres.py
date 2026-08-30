"""Opt-in disposable-PostgreSQL checks for durable outbound delivery.

Set OUTBOUND_POSTGRES_TEST_URL to a freshly migrated disposable database.
Never point this at development or production data.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.services.outbound_messages as outbound_module
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.outbound_message import OutboundMessage
from backend.models.user import User
from backend.schemas.email import ComposeRequest
from backend.services.outbound_messages import (
    OutboundMessageConflict,
    OutboundMessageNotFound,
    OutboundMessageQuotaExceeded,
    _claim_due_outbound,
    stage_outbound_message,
    undo_outbound_message,
)


DATABASE_URL = os.getenv("OUTBOUND_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires OUTBOUND_POSTGRES_TEST_URL for a disposable PostgreSQL database",
    ),
]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _session_factory():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset_database(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def _seed_account(session_factory, *, suffix: str = "one", with_source: bool = False):
    async with session_factory() as db:
        user = User(username=f"generated-outbound-{suffix}", is_admin=False, is_active=True)
        db.add(user)
        await db.flush()
        account = GoogleAccount(
            user_id=user.id,
            email=f"generated-{suffix}@example.test",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        source = None
        if with_source:
            source = Email(
                account_id=account.id,
                gmail_message_id=f"generated-message-{suffix}",
                gmail_thread_id=f"generated-thread-{suffix}",
                message_id_header=f"<generated-message-{suffix}@example.test>",
                references_header=f"<generated-root-{suffix}@example.test>",
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                has_attachments=False,
            )
            db.add(source)
            await db.flush()
        await db.commit()
        return user.id, account.id, source.id if source else None


async def _seed_second_account(session_factory, *, user_id: int, suffix: str = "second") -> int:
    async with session_factory() as db:
        account = GoogleAccount(
            user_id=user_id,
            email=f"generated-{suffix}@example.test",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        account_id = account.id
        await db.commit()
        return account_id


def _request(account_id: int, *, key=None, source_id=None):
    values = {
        "account_id": account_id,
        "to": ["recipient@example.test"],
        "subject": "Generated",
        "body_text": "Generated body",
        "idempotency_key": key or uuid4(),
    }
    if source_id is not None:
        values.update({
            "source_email_id": source_id,
            "thread_id": "generated-thread-one",
            "in_reply_to": "<generated-message-one@example.test>",
            "references": (
                "<generated-root-one@example.test> "
                "<generated-message-one@example.test>"
            ),
        })
    return ComposeRequest(**values)


@pytest.fixture(autouse=True)
def _disable_notifications(monkeypatch):
    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_publish_outbound_event", no_publish)


async def test_concurrent_idempotent_stage_creates_one_send(monkeypatch):
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, account_id, _source_id = await _seed_account(sessions)
        key = uuid4()
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_ACTIVE_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_ACTIVE_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_RECENT_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_RECENT_LIMIT", 1)

        async def submit():
            async with sessions() as db:
                return await stage_outbound_message(
                    db,
                    user_id=user_id,
                    request=_request(account_id, key=key),
                    now=NOW,
                )

        first, second = await asyncio.gather(submit(), submit())

        assert sorted((first[1], second[1])) == [False, True]
        assert first[0].send_id == second[0].send_id
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(OutboundMessage)) == 1

        async with sessions() as db:
            with pytest.raises(OutboundMessageConflict):
                await stage_outbound_message(
                    db,
                    user_id=user_id,
                    request=_request(account_id, key=key).model_copy(
                        update={"subject": "Changed payload"}
                    ),
                    now=NOW,
                )
    finally:
        await engine.dispose()


async def test_foreign_reply_source_is_non_disclosing_and_atomic():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        first_user, first_account, _first_source = await _seed_account(
            sessions,
            suffix="first",
            with_source=True,
        )
        _second_user, _second_account, second_source = await _seed_account(
            sessions,
            suffix="second",
            with_source=True,
        )
        request = ComposeRequest(
            account_id=first_account,
            source_email_id=second_source,
            to=["recipient@example.test"],
            subject="Generated reply",
            body_text="Generated",
            thread_id="generated-thread-second",
            in_reply_to="<generated-message-second@example.test>",
            references=(
                "<generated-root-second@example.test> "
                "<generated-message-second@example.test>"
            ),
            idempotency_key=uuid4(),
        )

        async with sessions() as db:
            with pytest.raises(OutboundMessageNotFound, match="Reply source not found"):
                await stage_outbound_message(
                    db,
                    user_id=first_user,
                    request=request,
                    now=NOW,
                )
            await db.rollback()
            assert await db.scalar(select(func.count()).select_from(OutboundMessage)) == 0
    finally:
        await engine.dispose()


async def test_claim_and_undo_race_has_one_winner():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, account_id, _source_id = await _seed_account(sessions)
        async with sessions() as db:
            outbound, _created = await stage_outbound_message(
                db,
                user_id=user_id,
                request=_request(account_id),
                now=NOW,
            )
            send_id = outbound.send_id

        async def claim():
            async with sessions() as db:
                return len(await _claim_due_outbound(
                    db,
                    account_id=account_id,
                    now=NOW + timedelta(seconds=11),
                    limit=1,
                ))

        async def undo():
            async with sessions() as db:
                try:
                    result = await undo_outbound_message(
                        db,
                        user_id=user_id,
                        send_id=send_id,
                        now=NOW + timedelta(seconds=5),
                    )
                    return result.state
                except OutboundMessageConflict:
                    return "conflict"

        claimed, undo_state = await asyncio.gather(claim(), undo())
        assert (claimed, undo_state) in {(1, "conflict"), (0, "cancelled")}
    finally:
        await engine.dispose()


async def test_expired_attempted_lease_is_claimed_for_reconciliation_only():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, account_id, _source_id = await _seed_account(sessions)
        async with sessions() as db:
            outbound, _created = await stage_outbound_message(
                db,
                user_id=user_id,
                request=_request(account_id),
                now=NOW,
            )

        async with sessions() as db:
            claimed = await _claim_due_outbound(
                db,
                account_id=account_id,
                now=NOW + timedelta(seconds=11),
                limit=1,
            )
            assert len(claimed) == 1
            lease_expiry = NOW + timedelta(seconds=12)
            await db.execute(
                update(OutboundMessage)
                .where(OutboundMessage.id == outbound.id)
                .values(
                    provider_attempted_at=NOW + timedelta(seconds=11),
                    lease_expires_at=lease_expiry,
                )
            )
            await db.commit()

        async with sessions() as db:
            reclaimed = await _claim_due_outbound(
                db,
                account_id=account_id,
                now=lease_expiry + timedelta(seconds=1),
                limit=1,
            )
            assert len(reclaimed) == 1
            assert reclaimed[0].provider_attempted_at is not None
            assert reclaimed[0].state == "processing"
    finally:
        await engine.dispose()


async def test_concurrent_account_capacity_quota_cannot_be_overrun(monkeypatch):
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, account_id, _source_id = await _seed_account(sessions, suffix="account-capacity")
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_ACTIVE_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_ACTIVE_LIMIT", 100)
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_RECENT_LIMIT", 100)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_RECENT_LIMIT", 100)

        async def submit():
            async with sessions() as db:
                return await stage_outbound_message(
                    db,
                    user_id=user_id,
                    request=_request(account_id),
                    now=NOW,
                )

        results = await asyncio.gather(submit(), submit(), return_exceptions=True)
        successes = [result for result in results if not isinstance(result, Exception)]
        rejections = [result for result in results if isinstance(result, OutboundMessageQuotaExceeded)]
        assert len(successes) == 1
        assert len(rejections) == 1
        assert rejections[0].retry_after_seconds == outbound_module.OUTBOUND_ACTIVE_RETRY_AFTER_SECONDS
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(OutboundMessage)) == 1
    finally:
        await engine.dispose()


async def test_concurrent_user_capacity_quota_spans_accounts(monkeypatch):
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, first_account, _source_id = await _seed_account(sessions, suffix="user-capacity")
        second_account = await _seed_second_account(
            sessions,
            user_id=user_id,
            suffix="user-capacity-second",
        )
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_ACTIVE_LIMIT", 100)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_ACTIVE_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_RECENT_LIMIT", 100)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_RECENT_LIMIT", 100)

        async def submit(account_id):
            async with sessions() as db:
                return await stage_outbound_message(
                    db,
                    user_id=user_id,
                    request=_request(account_id),
                    now=NOW,
                )

        results = await asyncio.gather(
            submit(first_account),
            submit(second_account),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(isinstance(result, OutboundMessageQuotaExceeded) for result in results) == 1
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(OutboundMessage)) == 1
    finally:
        await engine.dispose()


async def test_recent_account_and_user_quotas_include_completed_acceptances(monkeypatch):
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, first_account, _source_id = await _seed_account(sessions, suffix="recent")
        second_account = await _seed_second_account(
            sessions,
            user_id=user_id,
            suffix="recent-second",
        )
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_ACTIVE_LIMIT", 100)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_ACTIVE_LIMIT", 100)

        async with sessions() as db:
            first, _created = await stage_outbound_message(
                db,
                user_id=user_id,
                request=_request(first_account),
                now=NOW,
            )
            await undo_outbound_message(
                db,
                user_id=user_id,
                send_id=first.send_id,
                now=NOW + timedelta(seconds=5),
            )

        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_RECENT_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_RECENT_LIMIT", 100)
        async with sessions() as db:
            with pytest.raises(OutboundMessageQuotaExceeded) as account_quota:
                await stage_outbound_message(
                    db,
                    user_id=user_id,
                    request=_request(first_account),
                    now=NOW + timedelta(seconds=10),
                )
        assert account_quota.value.retry_after_seconds == 50

        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_RECENT_LIMIT", 100)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_RECENT_LIMIT", 1)
        async with sessions() as db:
            with pytest.raises(OutboundMessageQuotaExceeded) as user_quota:
                await stage_outbound_message(
                    db,
                    user_id=user_id,
                    request=_request(second_account),
                    now=NOW + timedelta(seconds=10),
                )
        assert user_quota.value.retry_after_seconds == 50
    finally:
        await engine.dispose()


async def test_expired_retry_payload_is_scrubbed_during_admission(monkeypatch):
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        user_id, account_id, _source_id = await _seed_account(sessions, suffix="retry-expiry")
        async with sessions() as db:
            expired, _created = await stage_outbound_message(
                db,
                user_id=user_id,
                request=_request(account_id),
                now=NOW,
            )
            expired_id = expired.id
            await db.execute(
                update(OutboundMessage)
                .where(OutboundMessage.id == expired_id)
                .values(
                    state="failed",
                    next_attempt_at=None,
                    failed_at=NOW + timedelta(seconds=1),
                    retry_authorized=True,
                    retry_expires_at=NOW + timedelta(seconds=2),
                )
            )
            await db.commit()

        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_ACTIVE_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_ACTIVE_LIMIT", 1)
        monkeypatch.setattr(outbound_module, "OUTBOUND_ACCOUNT_RECENT_LIMIT", 100)
        monkeypatch.setattr(outbound_module, "OUTBOUND_USER_RECENT_LIMIT", 100)
        async with sessions() as db:
            replacement, created = await stage_outbound_message(
                db,
                user_id=user_id,
                request=_request(account_id),
                now=NOW + timedelta(seconds=3),
            )
            assert created is True
            assert replacement.id != expired_id

        async with sessions() as db:
            scrubbed = await db.get(OutboundMessage, expired_id)
            assert scrubbed.state == "failed"
            assert scrubbed.payload is None
            assert scrubbed.retry_authorized is False
            assert scrubbed.retry_expires_at is None
            payload_is_sql_null = await db.scalar(
                text("SELECT payload IS NULL FROM outbound_messages WHERE id = :id"),
                {"id": expired_id},
            )
            assert payload_is_sql_null is True
    finally:
        await engine.dispose()


async def test_outbound_quota_migration_indexes_and_retry_column_exist():
    engine, sessions = _session_factory()
    try:
        async with sessions() as db:
            index_names = set((await db.execute(text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = 'outbound_messages'"
            ))).scalars().all())
            assert {
                "ix_outbound_messages_account_created",
                "ix_outbound_messages_user_capacity",
                "ix_outbound_messages_account_capacity",
                "ix_outbound_messages_retry_expiry",
            } <= index_names
            retry_column = await db.scalar(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'outbound_messages' "
                "AND column_name = 'retry_authorized'"
            ))
            assert retry_column == "retry_authorized"
            retry_expiry_column = await db.scalar(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'outbound_messages' "
                "AND column_name = 'retry_expires_at'"
            ))
            assert retry_expiry_column == "retry_expires_at"
            constraint_names = set((await db.execute(text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'outbound_messages'"
            ))).scalars().all())
            assert {
                "ck_outbound_messages_retry_authorized",
                "ck_outbound_messages_failed_payload",
                "ck_outbound_messages_retry_expiry",
            } <= constraint_names
    finally:
        await engine.dispose()
