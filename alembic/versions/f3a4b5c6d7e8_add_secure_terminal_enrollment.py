"""Add owner-scoped secure terminal enrollment state.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-30

The upgrade is additive. Existing terminals receive opaque public UUIDs and
remain in the legacy generation-zero state. Raw device credentials are never
stored: only SHA-256 digests are persisted. Downgrade removes enrollment
attempt/credential audit state and the additive device enrollment columns.
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "terminal_devices",
        sa.Column("public_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "terminal_devices",
        sa.Column("hardware_model", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "terminal_devices",
        sa.Column(
            "enrollment_state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'legacy'"),
        ),
    )
    op.add_column(
        "terminal_devices",
        sa.Column(
            "enrollment_generation",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "terminal_devices",
        sa.Column("enrollment_config_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "terminal_devices",
        sa.Column("enrollment_release_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "terminal_devices",
        sa.Column("enrollment_key_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "terminal_devices",
        sa.Column("enrollment_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "terminal_devices",
        sa.Column("enrollment_activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "terminal_devices",
        sa.Column("last_secure_checkin_at", sa.DateTime(timezone=True), nullable=True),
    )

    bind = op.get_bind()
    existing_ids = list(
        bind.execute(sa.text("SELECT id FROM terminal_devices")).scalars()
    )
    for device_id in existing_ids:
        bind.execute(
            sa.text(
                "UPDATE terminal_devices SET public_id = :public_id WHERE id = :device_id"
            ),
            {"public_id": uuid4(), "device_id": device_id},
        )
    op.alter_column("terminal_devices", "public_id", nullable=False)
    op.create_unique_constraint(
        "uq_terminal_devices_public_id", "terminal_devices", ["public_id"]
    )
    op.create_check_constraint(
        "ck_terminal_devices_enrollment_state",
        "terminal_devices",
        "enrollment_state IN ('legacy','pending','enrolled','revoked','review')",
    )
    op.create_check_constraint(
        "ck_terminal_devices_enrollment_generation",
        "terminal_devices",
        "enrollment_generation >= 0",
    )
    op.create_check_constraint(
        "ck_terminal_devices_enrolled_shape",
        "terminal_devices",
        "enrollment_state <> 'enrolled' OR "
        "(enrollment_generation > 0 AND enrollment_config_sha256 IS NOT NULL "
        "AND enrollment_activated_at IS NOT NULL)",
    )
    op.create_index("ix_terminal_devices_mac", "terminal_devices", ["mac"])
    op.create_index(
        "uq_terminal_devices_secure_mac",
        "terminal_devices",
        ["mac"],
        unique=True,
        postgresql_where=sa.text("enrollment_state <> 'legacy'"),
    )

    op.create_table(
        "terminal_device_credentials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'candidate'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('candidate','active','rollback','revoked')",
            name="ck_terminal_device_credentials_state",
        ),
        sa.CheckConstraint(
            "token_sha256 ~ '^[0-9a-f]{64}$' AND "
            "config_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_terminal_device_credentials_hashes",
        ),
        sa.CheckConstraint(
            "generation > 0", name="ck_terminal_device_credentials_generation"
        ),
        sa.CheckConstraint(
            "(state = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(state <> 'revoked' AND revoked_at IS NULL)",
            name="ck_terminal_device_credentials_revocation",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["terminal_devices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_sha256", name="uq_terminal_device_credentials_token_sha256"
        ),
        sa.UniqueConstraint(
            "device_id",
            "generation",
            name="uq_terminal_device_credentials_device_generation",
        ),
    )
    op.create_index(
        "ix_terminal_device_credentials_device_state",
        "terminal_device_credentials",
        ["device_id", "state"],
    )

    op.create_table(
        "terminal_enrollment_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.BigInteger(), nullable=True),
        sa.Column("client_intent_id", sa.Uuid(), nullable=False),
        sa.Column("intent_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("transcript_sha256", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=22), nullable=False),
        sa.Column(
            "operation",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'provision'"),
        ),
        sa.Column("device_model", sa.String(length=16), nullable=False),
        sa.Column("device_mac", sa.String(length=17), nullable=False),
        sa.Column("firmware_version", sa.String(length=128), nullable=False),
        sa.Column("firmware_release_id", sa.String(length=64), nullable=False),
        sa.Column("enrollment_key_id", sa.String(length=64), nullable=False),
        sa.Column("observed_generation", sa.Integer(), nullable=False),
        sa.Column("target_generation", sa.Integer(), nullable=False),
        sa.Column("client_ticket_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("config_sha256", sa.String(length=64), nullable=True),
        sa.Column("jti_sha256", sa.String(length=64), nullable=True),
        sa.Column("compact_jws", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'initialized'"),
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_generation", sa.Integer(), nullable=True),
        sa.Column("result_config_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "operation IN ('provision','rollback')",
            name="ck_terminal_enrollment_attempts_operation",
        ),
        sa.CheckConstraint(
            "status IN ('initialized','issued','client_confirmed','activated',"
            "'expired','superseded','review')",
            name="ck_terminal_enrollment_attempts_status",
        ),
        sa.CheckConstraint(
            "observed_generation >= 0 AND target_generation > 0 "
            "AND target_generation < 4294967295 "
            "AND target_generation = observed_generation + 1",
            name="ck_terminal_enrollment_attempts_generations",
        ),
        sa.CheckConstraint(
            "transcript_sha256 ~ '^[0-9a-f]{64}$' AND "
            "intent_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "(ticket_fingerprint IS NULL OR ticket_fingerprint ~ '^[0-9a-f]{64}$') AND "
            "(config_sha256 IS NULL OR config_sha256 ~ '^[0-9a-f]{64}$') AND "
            "(jti_sha256 IS NULL OR jti_sha256 ~ '^[0-9a-f]{64}$') AND "
            "(result_config_sha256 IS NULL OR result_config_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_terminal_enrollment_attempts_hashes",
        ),
        sa.CheckConstraint(
            "(status IN ('initialized','expired','superseded','review') "
            "AND compact_jws IS NULL AND credential_id IS NULL "
            "AND client_ticket_id IS NULL AND ticket_fingerprint IS NULL "
            "AND config_sha256 IS NULL AND jti_sha256 IS NULL "
            "AND issued_at IS NULL AND expires_at IS NULL) OR "
            "(status IN ('issued','client_confirmed','activated','expired','superseded','review') "
            "AND compact_jws IS NOT NULL AND credential_id IS NOT NULL "
            "AND client_ticket_id IS NOT NULL AND ticket_fingerprint IS NOT NULL "
            "AND config_sha256 IS NOT NULL AND jti_sha256 IS NOT NULL "
            "AND issued_at IS NOT NULL AND expires_at IS NOT NULL)",
            name="ck_terminal_enrollment_attempts_ticket_shape",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["device_id"], ["terminal_devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["terminal_device_credentials.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id", name="uq_terminal_enrollment_attempts_attempt_id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_intent_id",
            name="uq_terminal_enrollment_attempts_user_intent",
        ),
        sa.UniqueConstraint(
            "transcript_sha256", name="uq_terminal_enrollment_attempts_transcript"
        ),
        sa.UniqueConstraint(
            "jti_sha256", name="uq_terminal_enrollment_attempts_jti_sha256"
        ),
    )
    op.create_index(
        "ix_terminal_enrollment_attempts_user_created",
        "terminal_enrollment_attempts",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_terminal_enrollment_attempts_device_status",
        "terminal_enrollment_attempts",
        ["device_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_terminal_enrollment_attempts_device_status",
        table_name="terminal_enrollment_attempts",
    )
    op.drop_index(
        "ix_terminal_enrollment_attempts_user_created",
        table_name="terminal_enrollment_attempts",
    )
    op.drop_table("terminal_enrollment_attempts")
    op.drop_index(
        "ix_terminal_device_credentials_device_state",
        table_name="terminal_device_credentials",
    )
    op.drop_table("terminal_device_credentials")
    op.drop_index("uq_terminal_devices_secure_mac", table_name="terminal_devices")
    op.drop_index("ix_terminal_devices_mac", table_name="terminal_devices")
    op.drop_constraint(
        "ck_terminal_devices_enrolled_shape", "terminal_devices", type_="check"
    )
    op.drop_constraint(
        "ck_terminal_devices_enrollment_generation",
        "terminal_devices",
        type_="check",
    )
    op.drop_constraint(
        "ck_terminal_devices_enrollment_state",
        "terminal_devices",
        type_="check",
    )
    op.drop_constraint(
        "uq_terminal_devices_public_id", "terminal_devices", type_="unique"
    )
    op.drop_column("terminal_devices", "last_secure_checkin_at")
    op.drop_column("terminal_devices", "enrollment_activated_at")
    op.drop_column("terminal_devices", "enrollment_updated_at")
    op.drop_column("terminal_devices", "enrollment_key_id")
    op.drop_column("terminal_devices", "enrollment_release_id")
    op.drop_column("terminal_devices", "enrollment_config_sha256")
    op.drop_column("terminal_devices", "enrollment_generation")
    op.drop_column("terminal_devices", "enrollment_state")
    op.drop_column("terminal_devices", "hardware_model")
    op.drop_column("terminal_devices", "public_id")
