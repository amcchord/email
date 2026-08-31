from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from backend.models.email import Email
from backend.routers.emails import _conversation_filter_statement, list_conversations
from backend.services.conversation_rows import (
    conversation_count_statement,
    conversation_page_statement,
)


def test_conversation_query_groups_before_pagination_with_account_identity():
    filtered = select(Email).where(Email.account_id.in_([7, 8]))

    count_sql = str(
        conversation_count_statement(filtered).compile(dialect=postgresql.dialect())
    )
    page_sql = str(conversation_page_statement(
        filtered,
        page=2,
        page_size=25,
        sort_by="date",
        sort_order="desc",
    ).compile(dialect=postgresql.dialect()))

    assert "row_number() OVER" in count_sql
    assert "PARTITION BY matching_messages.account_id" in count_sql
    assert "matching_messages.conversation_identity" in count_sql
    assert "count(*) OVER" in count_sql
    assert "conversation_anchors" in page_sql
    assert "conversation_aggregates" in page_sql
    assert "jsonb_agg" in page_sql
    assert " LIMIT " in page_sql
    assert " OFFSET " in page_sql


def test_conversation_query_falls_back_to_per_message_identity_for_blank_thread_ids():
    statement = conversation_page_statement(
        select(Email),
        page=1,
        page_size=50,
        sort_by="date",
        sort_order="desc",
    ).compile(dialect=postgresql.dialect())
    sql = str(statement)

    assert "btrim" in sql
    assert "nullif" in sql
    assert "__message__:" not in sql  # User values remain bound parameters.
    assert "concat" in sql
    assert "conversation_identity" in sql


def test_conversation_sort_uses_aggregate_state_for_read_and_attachment():
    filtered = select(Email).where(Email.account_id == 7)
    unread_sql = str(conversation_page_statement(
        filtered,
        page=1,
        page_size=50,
        sort_by="is_read",
        sort_order="asc",
    ).compile(dialect=postgresql.dialect()))
    attachment_sql = str(conversation_page_statement(
        filtered,
        page=1,
        page_size=50,
        sort_by="has_attachments",
        sort_order="desc",
    ).compile(dialect=postgresql.dialect()))

    assert "conversation_aggregates.unread_count ASC" in unread_sql
    assert "conversation_aggregates.attachment_count DESC" in attachment_sql


def test_inbox_placement_is_chosen_after_one_authoritative_thread_anchor():
    filtered = select(Email).where(Email.account_id.in_([7, 8]))
    count_sql = str(conversation_count_statement(
        filtered,
        inbox_placement="focused",
    ).compile(dialect=postgresql.dialect()))
    page_sql = str(conversation_page_statement(
        filtered,
        page=1,
        page_size=25,
        sort_by="date",
        sort_order="desc",
        inbox_placement="other",
    ).compile(dialect=postgresql.dialect()))

    for sql in (count_sql, page_sql):
        assert "conversation_anchors" in sql
        assert "reasoned_conversation_anchors" in sql
        assert "placed_conversation_anchors" in sql
        assert sql.index("match_rank =") < sql.index("reasoned_conversation_anchors")
        assert "LEFT OUTER JOIN ai_analyses" in sql
        assert "placed_conversation_anchors.inbox_placement =" in sql
        assert "emails_1.account_id = emails.account_id" in sql
        assert "emails_1.gmail_thread_id = emails.gmail_thread_id" in sql


@pytest.mark.asyncio
async def test_inbox_placement_rejects_mailbox_or_filter_combinations_before_db_work():
    user = SimpleNamespace(id=42)

    with pytest.raises(HTTPException) as non_inbox:
        await list_conversations(
            mailbox="SENT",
            inbox_placement="focused",
            db=None,
            user=user,
        )
    assert getattr(non_inbox.value, "status_code", None) == 422

    with pytest.raises(HTTPException) as filtered:
        await list_conversations(
            mailbox="INBOX",
            ai_category="urgent",
            inbox_placement="other",
            db=None,
            user=user,
        )
    assert getattr(filtered.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_inbox_filter_excludes_active_snoozes_before_grouping():
    statement = await _conversation_filter_statement(
        None,
        account_rows=[SimpleNamespace(
            id=7,
            email="owner@example.test",
            display_name="Generated owner",
            description=None,
            short_label=None,
        )],
        user_accounts={7: "owner@example.test"},
        user_id=42,
        account_id=None,
        mailbox="INBOX",
        label=None,
        search=None,
        tz=None,
        is_read=None,
        is_starred=None,
        ai_category=None,
        exclude_ai_category=None,
        ai_email_type=None,
        needs_reply=None,
    )
    compiled = statement.compile(dialect=postgresql.dialect())

    assert "email_snoozes" in str(compiled)
    assert "NOT (EXISTS" in str(compiled)
    bound_values = {
        item
        for value in compiled.params.values()
        for item in (value if isinstance(value, (list, tuple)) else [value])
    }
    assert bound_values >= {
        42,
        "pending_archive",
        "scheduled",
        "pending_return",
    }
