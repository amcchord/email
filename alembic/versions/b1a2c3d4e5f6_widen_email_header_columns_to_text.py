"""Widen email header columns to TEXT to handle arbitrarily long values.

Revision ID: b1a2c3d4e5f6
Revises: 068972a23b37
Create Date: 2026-02-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b1a2c3d4e5f6"
down_revision: Union[str, None] = "068972a23b37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Email columns that can receive arbitrarily long header data
    op.alter_column("emails", "from_address", type_=sa.Text(), existing_type=sa.String(255), existing_nullable=True)
    op.alter_column("emails", "from_name", type_=sa.Text(), existing_type=sa.String(255), existing_nullable=True)
    op.alter_column("emails", "reply_to", type_=sa.Text(), existing_type=sa.String(255), existing_nullable=True)
    op.alter_column("emails", "message_id_header", type_=sa.Text(), existing_type=sa.String(500), existing_nullable=True)
    op.alter_column("emails", "in_reply_to", type_=sa.Text(), existing_type=sa.String(500), existing_nullable=True)

    # Attachment columns that can be long
    op.alter_column("attachments", "gmail_attachment_id", type_=sa.Text(), existing_type=sa.String(500), existing_nullable=True)
    op.alter_column("attachments", "filename", type_=sa.Text(), existing_type=sa.String(500), existing_nullable=True)
    op.alter_column("attachments", "content_id", type_=sa.Text(), existing_type=sa.String(255), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("emails", "from_address", type_=sa.String(255), existing_type=sa.Text(), existing_nullable=True)
    op.alter_column("emails", "from_name", type_=sa.String(255), existing_type=sa.Text(), existing_nullable=True)
    op.alter_column("emails", "reply_to", type_=sa.String(255), existing_type=sa.Text(), existing_nullable=True)
    op.alter_column("emails", "message_id_header", type_=sa.String(500), existing_type=sa.Text(), existing_nullable=True)
    op.alter_column("emails", "in_reply_to", type_=sa.String(500), existing_type=sa.Text(), existing_nullable=True)

    op.alter_column("attachments", "gmail_attachment_id", type_=sa.String(500), existing_type=sa.Text(), existing_nullable=True)
    op.alter_column("attachments", "filename", type_=sa.String(500), existing_type=sa.Text(), existing_nullable=True)
    op.alter_column("attachments", "content_id", type_=sa.String(255), existing_type=sa.Text(), existing_nullable=True)
