"""Opt-in disposable-PostgreSQL checks for authoritative conversation rows."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis, ThreadDigest
from backend.models.email import Email
from backend.models.inbox_placement_rule import InboxPlacementRule
from backend.models.user import User
from backend.routers.emails import list_conversations, list_split_conversations


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


async def test_split_inbox_places_each_conversation_once_from_its_newest_anchor():
    engine, sessions = _session_factory()
    try:
        await _reset_database(engine)
        async with sessions() as db:
            user = User(username="generated-focused-inbox", is_admin=False, is_active=True)
            db.add(user)
            await db.flush()
            account = GoogleAccount(
                user_id=user.id,
                email="focused-owner@example.test",
                is_active=True,
            )
            db.add(account)
            await db.flush()

            def message(message_id, thread_id, subject, date, sender="sender@example.test", **values):
                return Email(
                    account_id=account.id,
                    gmail_message_id=message_id,
                    gmail_thread_id=thread_id,
                    subject=subject,
                    from_address=sender,
                    date=date,
                    labels=values.pop("labels", ["INBOX"]),
                    is_read=values.pop("is_read", False),
                    is_starred=False,
                    is_trash=False,
                    is_spam=False,
                    is_draft=False,
                    is_sent=values.pop("is_sent", False),
                    has_attachments=False,
                    **values,
                )

            mixed_older = message(
                "generated-mixed-older",
                "mixed-thread",
                "Generated mixed older",
                NOW - timedelta(hours=8),
                sender="overlap@precedence.example",
            )
            mixed_newer = message(
                "generated-mixed-newer",
                "mixed-thread",
                "Generated mixed newest",
                NOW - timedelta(hours=7),
                sender="overlap@precedence.example",
            )
            subscription = message(
                "generated-subscription",
                "subscription-thread",
                "Generated subscription",
                NOW - timedelta(hours=6),
                sender="newsletter@subscription.example",
            )
            delegated = message(
                "generated-delegated",
                "delegated-thread",
                "Generated delegated scheduling",
                NOW - timedelta(hours=5),
                cc_addresses=[{"address": "andrea@mcchord.net"}],
            )
            unclassified = message(
                "generated-unclassified",
                "unclassified-thread",
                "Generated new mail",
                NOW - timedelta(hours=4),
                sender="person@domain-rule.example",
            )
            replied = message(
                "generated-needs-reply",
                "replied-thread",
                "Generated already answered",
                NOW - timedelta(hours=3),
            )
            sent_reply = message(
                "generated-sent-reply",
                "replied-thread",
                "Generated reply",
                NOW - timedelta(hours=2),
                labels=["SENT"],
                is_read=True,
                is_sent=True,
            )
            trusted = message(
                "generated-trusted",
                "trusted-thread",
                "Generated trusted sender",
                NOW - timedelta(hours=1),
                sender="andrea@mcchord.net",
            )
            malformed_sender = message(
                "generated-malformed-sender",
                "malformed-sender-thread",
                "Generated malformed sender",
                NOW - timedelta(minutes=30),
                sender="newsletter@subscription.example@attacker.example",
            )
            db.add_all([
                mixed_older,
                mixed_newer,
                subscription,
                delegated,
                unclassified,
                replied,
                sent_reply,
                trusted,
                malformed_sender,
            ])
            await db.flush()
            db.add_all([
                AIAnalysis(
                    email_id=mixed_older.id,
                    category="can_ignore",
                    priority=0,
                    is_subscription=True,
                ),
                AIAnalysis(
                    email_id=mixed_newer.id,
                    category="urgent",
                    priority=2,
                    is_subscription=True,
                ),
                AIAnalysis(
                    email_id=subscription.id,
                    category="can_ignore",
                    priority=0,
                    is_subscription=True,
                ),
                AIAnalysis(
                    email_id=delegated.id,
                    category="fyi",
                    priority=1,
                    conversation_type="scheduling",
                    needs_reply=True,
                ),
                AIAnalysis(
                    email_id=replied.id,
                    category="awaiting_reply",
                    priority=1,
                    needs_reply=True,
                ),
                AIAnalysis(
                    email_id=trusted.id,
                    category="can_ignore",
                    priority=0,
                    is_subscription=True,
                ),
            ])
            db.add_all([
                InboxPlacementRule(
                    create_id=uuid4(),
                    account_id=account.id,
                    scope="conversation",
                    match_value="thread:mixed-thread",
                    placement="other",
                    enabled=True,
                ),
                InboxPlacementRule(
                    create_id=uuid4(),
                    account_id=account.id,
                    scope="sender",
                    match_value="newsletter@subscription.example",
                    placement="focused",
                    enabled=True,
                ),
                InboxPlacementRule(
                    create_id=uuid4(),
                    account_id=account.id,
                    scope="domain",
                    match_value="subscription.example",
                    placement="other",
                    enabled=True,
                ),
                InboxPlacementRule(
                    create_id=uuid4(),
                    account_id=account.id,
                    scope="sender",
                    match_value="overlap@precedence.example",
                    placement="focused",
                    enabled=True,
                ),
                InboxPlacementRule(
                    create_id=uuid4(),
                    account_id=account.id,
                    scope="domain",
                    match_value="domain-rule.example",
                    placement="other",
                    enabled=True,
                ),
                InboxPlacementRule(
                    create_id=uuid4(),
                    account_id=account.id,
                    scope="sender",
                    match_value="andrea@mcchord.net",
                    placement="other",
                    enabled=False,
                ),
            ])
            await db.commit()
            user_id = user.id

        async with sessions() as db:
            split = await list_split_conversations(
                page=1,
                page_size=50,
                db=db,
                user=type("OwnedUser", (), {"id": user_id})(),
            )
            empty_page = await list_split_conversations(
                page=99,
                page_size=2,
                db=db,
                user=type("OwnedUser", (), {"id": user_id})(),
            )
            focused = split.focused
            other = split.other

        focused_by_subject = {row.subject: row for row in focused.conversations}
        other_by_subject = {row.subject: row for row in other.conversations}
        assert focused.total == 4
        assert other.total == 3
        assert set(focused_by_subject) == {
            "Generated subscription",
            "Generated already answered",
            "Generated trusted sender",
            "Generated malformed sender",
        }
        assert set(other_by_subject) == {
            "Generated mixed newest",
            "Generated new mail",
            "Generated delegated scheduling",
        }
        assert other_by_subject["Generated mixed newest"].inbox_placement_reason == "user_rule_other"
        assert other_by_subject["Generated mixed newest"].inbox_placement_rule_scope == "conversation"
        assert other_by_subject["Generated new mail"].inbox_placement_reason == "user_rule_other"
        assert other_by_subject["Generated new mail"].inbox_placement_rule_scope == "domain"
        assert focused_by_subject["Generated subscription"].inbox_placement_reason == "user_rule_focused"
        assert focused_by_subject["Generated subscription"].inbox_placement_rule_scope == "sender"
        assert focused_by_subject["Generated subscription"].inbox_placement_source == "rule"
        assert focused_by_subject["Generated subscription"].inbox_placement_rule_revision == 1
        assert focused_by_subject["Generated subscription"].inbox_placement_rule_id is not None
        assert focused_by_subject["Generated already answered"].inbox_placement_reason == "direct_or_fyi"
        assert focused_by_subject["Generated trusted sender"].inbox_placement_reason == "trusted_contact"
        assert focused_by_subject["Generated trusted sender"].inbox_placement_source == "system"
        assert focused_by_subject["Generated trusted sender"].inbox_placement_rule_id is None
        assert focused_by_subject["Generated malformed sender"].inbox_placement_reason == "unclassified"
        assert focused_by_subject["Generated malformed sender"].inbox_placement_source == "system"
        assert focused_by_subject["Generated malformed sender"].inbox_placement_rule_id is None
        assert other_by_subject["Generated delegated scheduling"].inbox_placement_reason == "delegated_scheduling"
        assert other_by_subject["Generated delegated scheduling"].needs_reply is False
        assert split.total == focused.total + other.total == 7
        assert empty_page.total == 7
        assert empty_page.focused.total == 4
        assert empty_page.other.total == 3
        assert empty_page.focused.conversations == []
        assert empty_page.other.conversations == []
        assert {row.conversation_key for row in focused.conversations}.isdisjoint(
            {row.conversation_key for row in other.conversations}
        )
    finally:
        await engine.dispose()
