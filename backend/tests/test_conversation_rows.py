from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from backend.models.email import Email
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
