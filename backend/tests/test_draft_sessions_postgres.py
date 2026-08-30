"""Opt-in disposable-PostgreSQL checks for durable Gmail draft sessions.

Set DRAFT_POSTGRES_TEST_URL to a freshly migrated disposable database. Never
point this at development or production data.
"""

import asyncio
import base64
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.services.drafts as draft_module
import backend.services.outbound_messages as outbound_module
from backend.models.account import GoogleAccount
from backend.models.draft import DraftAttachment, DraftMutation, DraftSession
from backend.models.email import Email
from backend.models.outbound_message import OutboundMessage
from backend.models.user import User
from backend.schemas.email import ComposeDraftRequest, ComposeRequest
from backend.services.drafts import (
    DraftConflict,
    DraftNotFound,
    _claim_due_drafts,
    _process_discard,
    discard_draft_session,
    get_draft_session_for_email,
    stage_draft_upsert,
    undo_discard_draft_session,
)
from backend.services.outbound_messages import stage_outbound_message, undo_outbound_message
from backend.services.outbound_messages import OutboundMessageConflict


DATABASE_URL = os.getenv("DRAFT_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires DRAFT_POSTGRES_TEST_URL for a disposable PostgreSQL database",
    ),
]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _session_factory():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset_database(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def _seed_account(sessions, *, suffix="one", with_source=False):
    async with sessions() as db:
        user = User(username=f"generated-draft-{suffix}", is_admin=False, is_active=True)
        db.add(user)
        await db.flush()
        account = GoogleAccount(
            user_id=user.id,
            email=f"generated-draft-{suffix}@example.test",
            is_active=True,
        )
        db.add(account)
        await db.flush()
        source = None
        if with_source:
            source = Email(
                account_id=account.id,
                gmail_message_id=f"source-message-{suffix}",
                gmail_thread_id=f"source-thread-{suffix}",
                message_id_header=f"<source-message-{suffix}@example.test>",
                references_header=f"<source-root-{suffix}@example.test>",
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


def _request(account_id, *, client_draft_id=None, mutation_id=None, revision=1, content=b"attachment"):
    return ComposeDraftRequest(
        client_draft_id=client_draft_id or uuid4(),
        revision=revision,
        mutation_id=mutation_id or uuid4(),
        account_id=account_id,
        to=["recipient@example.test"],
        subject="Generated draft",
        body_text="Generated body",
        attachments=[{
            "filename": "generated.bin",
            "content_type": "application/octet-stream",
            "data_base64": base64.b64encode(content).decode(),
        }],
    )


@pytest.fixture(autouse=True)
def _disable_external_events(monkeypatch):
    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(draft_module, "_publish_draft_event", no_publish)
    monkeypatch.setattr(outbound_module, "_publish_outbound_event", no_publish)


async def test_concurrent_idempotent_upsert_and_monotonic_attachment_replacement(monkeypatch):
    engine, sessions = _session_factory()
    monkeypatch.setattr(draft_module, "async_session", sessions)
    try:
        await _reset_database(engine)
        user_id, account_id, _source = await _seed_account(sessions)
        client_draft_id = uuid4()
        mutation_id = uuid4()
        request = _request(
            account_id,
            client_draft_id=client_draft_id,
            mutation_id=mutation_id,
        )

        async def submit():
            async with sessions() as db:
                return await stage_draft_upsert(
                    db,
                    user_id=user_id,
                    request=request,
                    now=NOW,
                )

        first, second = await asyncio.gather(submit(), submit())
        assert sorted((first[1], second[1])) == [False, True]
        assert first[0].id == second[0].id
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(DraftSession)) == 1
            assert await db.scalar(select(func.count()).select_from(DraftMutation)) == 1
            attachment = (await db.execute(select(DraftAttachment))).scalar_one()
            assert attachment.content == b"attachment"
            assert attachment.size_bytes == len(b"attachment")

        changed_same_mutation = request.model_copy(update={"subject": "Changed"})
        async with sessions() as db:
            with pytest.raises(DraftConflict, match="Mutation ID"):
                await stage_draft_upsert(
                    db,
                    user_id=user_id,
                    request=changed_same_mutation,
                    now=NOW,
                )

        replacement = _request(
            account_id,
            client_draft_id=client_draft_id,
            revision=2,
            content=b"replacement bytes",
        )
        async with sessions() as db:
            draft, created = await stage_draft_upsert(
                db,
                user_id=user_id,
                request=replacement,
                now=NOW + timedelta(seconds=1),
            )
            assert created is False and draft.revision == 2
        async with sessions() as db:
            attachments = list((await db.execute(select(DraftAttachment))).scalars())
            assert len(attachments) == 1
            assert attachments[0].content == b"replacement bytes"
    finally:
        await engine.dispose()


async def test_foreign_reply_source_is_non_disclosing_and_atomic(monkeypatch):
    engine, sessions = _session_factory()
    monkeypatch.setattr(draft_module, "async_session", sessions)
    try:
        await _reset_database(engine)
        first_user, first_account, _first_source = await _seed_account(
            sessions, suffix="first", with_source=True
        )
        _second_user, _second_account, second_source = await _seed_account(
            sessions, suffix="second", with_source=True
        )
        request = ComposeDraftRequest(
            client_draft_id=uuid4(),
            revision=1,
            mutation_id=uuid4(),
            account_id=first_account,
            source_email_id=second_source,
            to=["recipient@example.test"],
            thread_id="source-thread-second",
            in_reply_to="<source-message-second@example.test>",
            references=(
                "<source-root-second@example.test> "
                "<source-message-second@example.test>"
            ),
        )
        async with sessions() as db:
            with pytest.raises(DraftNotFound, match="Reply source not found"):
                await stage_draft_upsert(
                    db,
                    user_id=first_user,
                    request=request,
                    now=NOW,
                )
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(DraftSession)) == 0
    finally:
        await engine.dispose()


async def test_delayed_discard_undo_and_terminal_scrub(monkeypatch):
    engine, sessions = _session_factory()
    monkeypatch.setattr(draft_module, "async_session", sessions)
    try:
        await _reset_database(engine)
        user_id, account_id, _source = await _seed_account(sessions)
        request = _request(account_id)
        async with sessions() as db:
            draft, _created = await stage_draft_upsert(
                db, user_id=user_id, request=request, now=NOW
            )
        async with sessions() as db:
            discarded = await discard_draft_session(
                db,
                user_id=user_id,
                client_draft_id=request.client_draft_id,
                mutation_id=uuid4(),
                now=NOW,
            )
            assert discarded.state == "discard_pending"
            assert discarded.discard_at == NOW + timedelta(seconds=10)
        async with sessions() as db:
            restored = await undo_discard_draft_session(
                db,
                user_id=user_id,
                client_draft_id=request.client_draft_id,
                mutation_id=uuid4(),
                now=NOW + timedelta(seconds=5),
            )
            assert restored.state == "pending"

        async with sessions() as db:
            await discard_draft_session(
                db,
                user_id=user_id,
                client_draft_id=request.client_draft_id,
                mutation_id=uuid4(),
                now=NOW + timedelta(seconds=20),
            )
        async with sessions() as db:
            claimed = await _claim_due_drafts(
                db,
                account_id=account_id,
                now=NOW + timedelta(seconds=31),
                limit=1,
            )
        assert len(claimed) == 1 and claimed[0].lease_operation == "discard"
        async with sessions() as db:
            scrubbed = (
                await db.execute(select(DraftSession).where(DraftSession.id == draft.id))
            ).scalar_one()
            assert scrubbed.payload is None
            assert scrubbed.attachment_count == scrubbed.attachment_bytes == 0
            assert await db.scalar(select(func.count()).select_from(DraftAttachment)) == 0

        class NoProviderGmail:
            pass

        await _process_discard(claimed[0], gmail=NoProviderGmail())
        async with sessions() as db:
            terminal = (
                await db.execute(
                    select(DraftSession).where(DraftSession.id == draft.id)
                )
            ).scalar_one()
            assert terminal.state == "discarded"
            assert terminal.payload is None
            assert terminal.attachment_count == terminal.attachment_bytes == 0
            assert await db.scalar(select(func.count()).select_from(DraftAttachment)) == 0
            with pytest.raises(DraftConflict, match="no longer editable"):
                await stage_draft_upsert(
                    db,
                    user_id=user_id,
                    request=request.model_copy(update={
                        "revision": 2,
                        "mutation_id": uuid4(),
                    }),
                    now=NOW + timedelta(seconds=32),
                )
    finally:
        await engine.dispose()


async def test_expired_discard_scrubs_before_ambiguous_provider_reconciliation(monkeypatch):
    engine, sessions = _session_factory()
    monkeypatch.setattr(draft_module, "async_session", sessions)
    try:
        await _reset_database(engine)
        user_id, account_id, _source = await _seed_account(sessions, suffix="scrub-first")
        request = _request(account_id, content=b"sensitive generated bytes")
        async with sessions() as db:
            draft, _created = await stage_draft_upsert(
                db, user_id=user_id, request=request, now=NOW
            )
            draft.provider_create_attempted_at = NOW
            await db.commit()
        async with sessions() as db:
            await discard_draft_session(
                db,
                user_id=user_id,
                client_draft_id=request.client_draft_id,
                mutation_id=uuid4(),
                now=NOW,
            )
        async with sessions() as db:
            claimed = await _claim_due_drafts(
                db,
                account_id=account_id,
                now=NOW + timedelta(seconds=11),
                limit=1,
            )

        class AmbiguousProvider:
            async def find_drafts_by_rfc_message_id(self, *_args, **_kwargs):
                raise ConnectionError("generated provider ambiguity")

            def get_refreshed_token(self):
                return None

        await _process_discard(claimed[0], gmail=AmbiguousProvider())
        async with sessions() as db:
            tombstone = (
                await db.execute(select(DraftSession).where(DraftSession.id == draft.id))
            ).scalar_one()
            assert tombstone.state == "discard_pending"
            assert tombstone.payload is None
            assert tombstone.attachment_count == tombstone.attachment_bytes == 0
            assert await db.scalar(select(func.count()).select_from(DraftAttachment)) == 0
    finally:
        await engine.dispose()


async def test_autosave_and_send_race_completes_without_lock_inversion(monkeypatch):
    engine, sessions = _session_factory()
    monkeypatch.setattr(draft_module, "async_session", sessions)
    try:
        await _reset_database(engine)
        user_id, account_id, _source = await _seed_account(sessions, suffix="lock-order")
        first = _request(account_id)
        async with sessions() as db:
            await stage_draft_upsert(db, user_id=user_id, request=first, now=NOW)
        update_request = _request(
            account_id,
            client_draft_id=first.client_draft_id,
            revision=2,
            content=b"replacement",
        )
        send_request = ComposeRequest(
            account_id=account_id,
            to=first.to,
            subject=first.subject,
            body_text=first.body_text,
            attachments=first.attachments,
            client_draft_id=first.client_draft_id,
            draft_revision=1,
            idempotency_key=uuid4(),
        )

        async def autosave():
            async with sessions() as db:
                return await stage_draft_upsert(
                    db, user_id=user_id, request=update_request, now=NOW + timedelta(seconds=1)
                )

        async def send():
            async with sessions() as db:
                return await stage_outbound_message(
                    db, user_id=user_id, request=send_request, now=NOW + timedelta(seconds=1)
                )

        outcomes = await asyncio.wait_for(
            asyncio.gather(autosave(), send(), return_exceptions=True),
            timeout=5,
        )
        assert sum(not isinstance(item, Exception) for item in outcomes) == 1
        errors = [item for item in outcomes if isinstance(item, Exception)]
        assert len(errors) == 1
        assert isinstance(errors[0], (DraftConflict, OutboundMessageConflict))
    finally:
        await engine.dispose()


async def test_outbound_acceptance_links_and_tombstones_draft(monkeypatch):
    engine, sessions = _session_factory()
    monkeypatch.setattr(draft_module, "async_session", sessions)
    try:
        await _reset_database(engine)
        user_id, account_id, _source = await _seed_account(sessions)
        request = _request(account_id)
        async with sessions() as db:
            draft, _created = await stage_draft_upsert(
                db, user_id=user_id, request=request, now=NOW
            )
        send = ComposeRequest(
            account_id=account_id,
            to=request.to,
            subject=request.subject,
            body_text=request.body_text,
            attachments=request.attachments,
            client_draft_id=request.client_draft_id,
            draft_revision=request.revision,
            idempotency_key=uuid4(),
        )
        async with sessions() as db:
            outbound, created = await stage_outbound_message(
                db,
                user_id=user_id,
                request=send,
                now=NOW,
            )
            assert created is True
            assert outbound.draft_session_id == draft.id
            assert outbound.client_draft_id == request.client_draft_id
            assert outbound.rfc_message_id == draft.rfc_message_id
            send_id = outbound.send_id
        async with sessions() as db:
            linked = (
                await db.execute(select(DraftSession).where(DraftSession.id == draft.id))
            ).scalar_one()
            assert linked.state == "sending"
            assert linked.linked_send_id == send_id
            assert linked.discard_at == NOW + timedelta(seconds=10)
            cancelled = await undo_outbound_message(
                db,
                user_id=user_id,
                send_id=send_id,
                now=NOW + timedelta(seconds=5),
            )
            assert cancelled.state == "cancelled"
        async with sessions() as db:
            still_tombstoned = (
                await db.execute(select(DraftSession).where(DraftSession.id == draft.id))
            ).scalar_one()
            assert still_tombstoned.state == "sending"
    finally:
        await engine.dispose()


async def test_synced_email_lookup_only_opens_app_managed_provider_mapping(monkeypatch):
    engine, sessions = _session_factory()
    monkeypatch.setattr(draft_module, "async_session", sessions)
    try:
        await _reset_database(engine)
        user_id, account_id, _source = await _seed_account(sessions)
        request = _request(account_id)
        async with sessions() as db:
            draft, _created = await stage_draft_upsert(
                db, user_id=user_id, request=request, now=NOW
            )
            draft.state = "synced"
            draft.synced_revision = draft.revision
            draft.provider_draft_id = "provider-draft"
            draft.provider_message_id = "provider-message"
            managed = Email(
                account_id=account_id,
                gmail_message_id="provider-message",
                gmail_thread_id="provider-thread",
                labels=["DRAFT"],
                is_draft=True,
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_sent=False,
                has_attachments=True,
            )
            external = Email(
                account_id=account_id,
                gmail_message_id="external-message",
                gmail_thread_id="external-thread",
                labels=["DRAFT"],
                is_draft=True,
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_sent=False,
                has_attachments=False,
            )
            db.add_all([managed, external])
            await db.flush()
            managed_id, external_id = managed.id, external.id
            await db.commit()
        async with sessions() as db:
            reopened = await get_draft_session_for_email(
                db, user_id=user_id, email_id=managed_id
            )
            assert reopened.id == draft.id
            assert reopened.attachments[0].content == b"attachment"
            with pytest.raises(DraftNotFound, match="not managed"):
                await get_draft_session_for_email(
                    db, user_id=user_id, email_id=external_id
                )
    finally:
        await engine.dispose()


async def test_migration_indexes_constraints_and_outbound_link_exist():
    engine, _sessions = _session_factory()
    try:
        async with engine.connect() as connection:
            indexes = set((await connection.execute(text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename IN ('draft_sessions','draft_attachments','draft_mutations','outbound_messages')"
            ))).scalars())
            assert {
                "uq_draft_sessions_account_provider_draft",
                "ix_draft_sessions_account_due",
                "ix_draft_sessions_expired_lease",
                "ix_draft_sessions_discard_due",
                "ix_draft_sessions_provider_message",
                "ix_outbound_messages_draft_session",
            } <= indexes
            constraints = set((await connection.execute(text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = current_schema() "
                "AND table_name IN ('draft_sessions','draft_attachments','draft_mutations')"
            ))).scalars())
            assert {
                "ck_draft_sessions_lease_state",
                "ck_draft_sessions_discard_scrubbed",
                "uq_draft_sessions_user_client_id",
                "uq_draft_attachments_session_attachment",
                "uq_draft_mutations_session_mutation",
            } <= constraints
            assert await connection.scalar(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name='outbound_messages' "
                "AND column_name IN ('draft_session_id','client_draft_id')"
            )) == 2
    finally:
        await engine.dispose()
