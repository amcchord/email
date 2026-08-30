"""Add durable existing Gmail label and move action names.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-30

The mail-action rows already persist exact add/remove label deltas. This
revision only gives existing-user-label operations truthful audit names.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_mail_actions_action", "mail_actions", type_="check")
    op.create_check_constraint(
        "ck_mail_actions_action",
        "mail_actions",
        "action IN ('mark_read','mark_unread','star','unstar','archive','unarchive',"
        "'trash','untrash','spam','unspam','add_label','remove_label','move_to_label')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mail_actions_action", "mail_actions", type_="check")
    # Older workers execute the persisted add_labels/remove_labels delta and
    # do not derive provider behavior from ``action``. Translate only the
    # display/audit name so accepted staged, retrying, failed, and completed
    # work remains executable after restoring the older constraint.
    op.execute(
        "UPDATE mail_actions SET action = CASE "
        "WHEN action = 'add_label' THEN 'star' "
        "WHEN action = 'remove_label' THEN 'unstar' "
        "WHEN action = 'move_to_label' THEN 'archive' "
        "ELSE action END "
        "WHERE action IN ('add_label','remove_label','move_to_label')"
    )
    op.create_check_constraint(
        "ck_mail_actions_action",
        "mail_actions",
        "action IN ('mark_read','mark_unread','star','unstar','archive','unarchive',"
        "'trash','untrash','spam','unspam')",
    )
