"""Opt-in disposable-PostgreSQL checks for authoritative conversation rows."""

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.account import GoogleAccount
from backend.models.ai import ThreadDigest
from backend.models.email import Email
from backend.models.user import User
from backend.routers.emails import list_conversations


DATABASE_URL = os.getenv("CONVERSATION_POSTGRES_TEST_URL") or os.getenv(
    "MAIL_ACTION_POSTGRES_TEST_URL"
)
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires a freshly migrated disposable PostgreSQL database",
    ),
]
NOW = datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc)


def _session_factory():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset_database(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def test_conversation_route_groups_before_pagination_and_isolates_accounts():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        async with sessions() as db:
            user = User(username="generated-conversations", is_admin=False, is_active=True)
            db.add(user)
            await db.flush()
            first_account = GoogleAccount(
                user_id=user.id,
                email="first-conversations@example.test",
                is_active=True,
            )
            second_account = GoogleAccount(
                user_id=user.id,
                email="second-conversations@example.test",
                is_active=True,
            )
            db.add_all([first_account, second_account])
            await db.flush()

            older_match = Email(
                account_id=first_account.id,
                gmail_message_id="generated-conversation-older",
                gmail_thread_id="provider-shared-thread",
                subject="Generated matching subject",
                from_address="first-sender@example.test",
                date=NOW - timedelta(hours=3),
                labels=["INBOX", "UNREAD", "Label_project"],
                is_read=False,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                has_attachments=False,
            )
            newer_nonmatch = Email(
                account_id=first_account.id,
                gmail_message_id="generated-conversation-newer",
                gmail_thread_id="provider-shared-thread",
                subject="Generated nonmatching sent subject",
                from_address="first-owner@example.test",
                date=NOW - timedelta(hours=2),
                labels=["SENT", "STARRED", "Label_project"],
                is_read=True,
                is_starred=True,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=True,
                has_attachments=True,
            )
            other_account_same_thread = Email(
                account_id=second_account.id,
                gmail_message_id="generated-conversation-other-account",
                gmail_thread_id="provider-shared-thread",
                subject="Generated other account",
                from_address="second-sender@example.test",
                date=NOW - timedelta(hours=1),
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                has_attachments=False,
            )
            blank_first = Email(
                account_id=first_account.id,
                gmail_message_id="generated-blank-first",
                gmail_thread_id="",
                subject="Generated blank first",
                date=NOW - timedelta(minutes=30),
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                has_attachments=False,
            )
            blank_second = Email(
                account_id=first_account.id,
                gmail_message_id="generated-blank-second",
                gmail_thread_id=" ",
                subject="Generated blank second",
                date=NOW - timedelta(minutes=15),
                labels=["INBOX"],
                is_read=True,
                is_starred=False,
                is_trash=False,
                is_spam=False,
                is_draft=False,
                is_sent=False,
                has_attachments=False,
            )
            db.add_all([
                older_match,
                newer_nonmatch,
                other_account_same_thread,
                blank_first,
                blank_second,
            ])
            db.add_all([
                ThreadDigest(
                    account_id=first_account.id,
                    gmail_thread_id="provider-shared-thread",
                    summary="First account digest",
                    message_count=2,
                ),
                ThreadDigest(
                    account_id=second_account.id,
                    gmail_thread_id="provider-shared-thread",
                    summary="Second account digest",
                    message_count=1,
                ),
            ])
            await db.commit()
            user_id = user.id
            older_id = older_match.id

        async with sessions() as db:
            page_one = await list_conversations(
                mailbox="INBOX",
                page=1,
                page_size=2,
                db=db,
                user=type("OwnedUser", (), {"id": user_id})(),
            )
            page_two = await list_conversations(
                mailbox="INBOX",
                page=2,
                page_size=2,
                db=db,
                user=type("OwnedUser", (), {"id": user_id})(),
            )

        assert page_one.total == page_two.total == 4
        assert page_one.total_pages == page_two.total_pages == 2
        all_rows = [*page_one.conversations, *page_two.conversations]
        assert len({row.conversation_key for row in all_rows}) == 4
        assert len([row for row in all_rows if row.gmail_thread_id.strip() == ""]) == 2

        first = next(
            row
            for row in all_rows
            if row.account_email == "first-conversations@example.test"
            and row.gmail_thread_id == "provider-shared-thread"
        )
        second = next(
            row
            for row in all_rows
            if row.account_email == "second-conversations@example.test"
        )
        assert first.anchor_email_id == older_id
        assert first.member_count == 2
        assert first.matched_count == 1
        assert first.unread_count == 1
        assert first.star_state == "some"
        assert first.has_attachments is True
        assert first.labels == ["INBOX", "Label_project", "SENT", "STARRED", "UNREAD"]
        assert first.label_coverage["Label_project"] == "all"
        assert first.label_coverage["INBOX"] == "some"
        assert first.thread_digest_summary == "First account digest"
        assert second.thread_digest_summary == "Second account digest"
    finally:
        await engine.dispose()
