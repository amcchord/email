"""Sanitize Todo links that cross user ownership boundaries.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-08-30

AI-derived Todo titles may contain content copied from their source email, so
rows whose source email is not owned by the Todo's user are removed. Manual
Todo titles are user-authored and remain useful; those rows are detached from
the inaccessible email and have any derived draft fields cleared.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MISMATCHED_EMAIL = """
    todo.email_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM emails AS email
        JOIN google_accounts AS account ON account.id = email.account_id
        WHERE email.id = todo.email_id
          AND account.user_id = todo.user_id
    )
"""


def upgrade() -> None:
    # The relationship spans three tables, so a normal CHECK constraint cannot
    # express it. Install the trigger before cleanup: PostgreSQL's trigger lock
    # prevents a concurrent Todo write from slipping between cleanup and
    # enforcement.
    op.execute(sa.text("""
        CREATE FUNCTION enforce_todo_email_ownership()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.email_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM emails AS email
                JOIN google_accounts AS account ON account.id = email.account_id
                WHERE email.id = NEW.email_id
                  AND account.user_id = NEW.user_id
            ) THEN
                RAISE EXCEPTION 'Todo source email is not owned by its user'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_todo_items_email_ownership';
            END IF;
            RETURN NEW;
        END;
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_todo_items_email_ownership
        BEFORE INSERT OR UPDATE OF user_id, email_id ON todo_items
        FOR EACH ROW
        EXECUTE FUNCTION enforce_todo_email_ownership()
    """))

    # These titles originated from an email the Todo owner cannot access, so
    # detaching the foreign key alone would retain derived private content.
    op.execute(sa.text(f"""
        DELETE FROM todo_items AS todo
        WHERE todo.source = 'ai_action_item'
          AND {_MISMATCHED_EMAIL}
    """))

    # Manual titles are authored by the Todo owner. Preserve that text while
    # removing the invalid source relationship and all derived reply material.
    op.execute(sa.text(f"""
        UPDATE todo_items AS todo
        SET email_id = NULL,
            ai_draft_status = NULL,
            ai_draft_body = NULL,
            ai_draft_to = NULL
        WHERE {_MISMATCHED_EMAIL}
    """))


def downgrade() -> None:
    # Restoring cross-user links would recreate the security defect, and
    # purged derived content cannot be reconstructed safely. This data cleanup
    # is intentionally irreversible; a pre-migration backup is the rollback.
    op.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_todo_items_email_ownership ON todo_items
    """))
    op.execute(sa.text("""
        DROP FUNCTION IF EXISTS enforce_todo_email_ownership()
    """))
