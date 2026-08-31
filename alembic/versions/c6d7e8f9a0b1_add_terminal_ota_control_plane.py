"""Add the durable, default-locked terminal OTA control plane.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-08-30

The upgrade adds explicit owner-confirmed hardware revision and coherent OTA
poll telemetry to terminals, plus one active attempt per device and an
append-only-by-service acknowledgement ledger. It does not enable OTA, install
release evidence, qualify hardware, or expose a second device credential.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTIVE_STATES = "('offered','downloading','staged','booted_pending_validation')"
TERMINAL_STATES = (
    "('succeeded','failed','rolled_back','recovery_required','expired','cancelled')"
)
ALL_STATES = (
    "('offered','downloading','staged','booted_pending_validation','succeeded',"
    "'failed','rolled_back','recovery_required','expired','cancelled')"
)


def upgrade() -> None:
    for column in (
        sa.Column("hardware_revision", sa.String(length=64), nullable=True),
        sa.Column(
            "hardware_revision_confirmed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_ota_fw_version", sa.String(length=48), nullable=True),
        sa.Column("last_ota_build_id", sa.String(length=40), nullable=True),
        sa.Column("last_ota_partition", sa.String(length=8), nullable=True),
        sa.Column("last_ota_boot_count", sa.BigInteger(), nullable=True),
        sa.Column("last_ota_battery_mv", sa.Integer(), nullable=True),
        sa.Column("last_ota_battery_pct", sa.Integer(), nullable=True),
        sa.Column("last_ota_external_power", sa.Boolean(), nullable=True),
        sa.Column("last_ota_telemetry_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("terminal_devices", column)
    op.create_check_constraint(
        "ck_terminal_devices_hardware_revision",
        "terminal_devices",
        "(hardware_revision IS NULL AND hardware_revision_confirmed_at IS NULL) OR "
        "(hardware_revision ~ '^[A-Za-z0-9._-]{1,64}$' "
        "AND hardware_revision_confirmed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_terminal_devices_ota_telemetry",
        "terminal_devices",
        "(last_ota_telemetry_at IS NULL AND last_ota_fw_version IS NULL "
        "AND last_ota_build_id IS NULL AND last_ota_partition IS NULL "
        "AND last_ota_boot_count IS NULL AND last_ota_battery_mv IS NULL "
        "AND last_ota_battery_pct IS NULL AND last_ota_external_power IS NULL) OR "
        "(last_ota_telemetry_at IS NOT NULL "
        "AND last_ota_fw_version ~ '^[A-Za-z0-9._+-]{1,48}$' "
        "AND last_ota_build_id ~ '^[0-9a-f]{40}$' "
        "AND last_ota_partition IN ('ota_0','ota_1') "
        "AND last_ota_boot_count > 0 "
        "AND last_ota_battery_mv BETWEEN 2500 AND 5000 "
        "AND last_ota_battery_pct BETWEEN 0 AND 100)",
    )

    op.create_table(
        "terminal_ota_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.BigInteger(), nullable=False),
        sa.Column("client_request_id", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'offered'"),
        ),
        sa.Column(
            "last_sequence",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "has_event_gap",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("descriptor_release_id", sa.String(length=64), nullable=False),
        sa.Column("parent_release_id", sa.String(length=64), nullable=False),
        sa.Column("signing_key_id", sa.String(length=64), nullable=False),
        sa.Column("catalog_generation", sa.Integer(), nullable=False),
        sa.Column("device_model", sa.String(length=16), nullable=False),
        sa.Column("hardware_revision", sa.String(length=64), nullable=False),
        sa.Column("partition_layout", sa.String(length=16), nullable=False),
        sa.Column("target_version", sa.String(length=48), nullable=False),
        sa.Column("target_build_id", sa.String(length=40), nullable=False),
        sa.Column("firmware_size", sa.Integer(), nullable=False),
        sa.Column("firmware_sha256", sa.String(length=64), nullable=False),
        sa.Column("descriptor_signature_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=48), nullable=False),
        sa.Column("source_build_id", sa.String(length=40), nullable=False),
        sa.Column("source_partition", sa.String(length=8), nullable=False),
        sa.Column("source_boot_count", sa.BigInteger(), nullable=False),
        sa.Column("offered_battery_mv", sa.Integer(), nullable=False),
        sa.Column("offered_battery_pct", sa.Integer(), nullable=False),
        sa.Column("offered_external_power", sa.Boolean(), nullable=True),
        sa.Column("rollout_percentage", sa.Integer(), nullable=False),
        sa.Column("cohort_bucket", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
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
            "state IN " + ALL_STATES,
            name="ck_terminal_ota_attempts_state",
        ),
        sa.CheckConstraint(
            "last_sequence >= 0 AND last_sequence < 4294967296",
            name="ck_terminal_ota_attempts_sequence",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "descriptor_release_id ~ '^[0-9a-f]{64}$' AND "
            "parent_release_id ~ '^[0-9a-f]{64}$' AND "
            "target_build_id ~ '^[0-9a-f]{40}$' AND "
            "source_build_id ~ '^[0-9a-f]{40}$' AND "
            "firmware_sha256 ~ '^[0-9a-f]{64}$' AND "
            "descriptor_signature_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_terminal_ota_attempts_hashes",
        ),
        sa.CheckConstraint(
            "device_model IN ('E1001','E1002') AND partition_layout = 'ab-v1' "
            "AND hardware_revision ~ '^[A-Za-z0-9._-]{1,64}$'",
            name="ck_terminal_ota_attempts_target",
        ),
        sa.CheckConstraint(
            "source_partition IN ('ota_0','ota_1') "
            "AND source_boot_count > 0 AND source_boot_count < 4294967296",
            name="ck_terminal_ota_attempts_source",
        ),
        sa.CheckConstraint(
            "firmware_size > 0 AND firmware_size <= 3145728 AND catalog_generation > 0",
            name="ck_terminal_ota_attempts_release",
        ),
        sa.CheckConstraint(
            "offered_battery_mv BETWEEN 2500 AND 5000 "
            "AND offered_battery_pct BETWEEN 0 AND 100",
            name="ck_terminal_ota_attempts_power",
        ),
        sa.CheckConstraint(
            "rollout_percentage BETWEEN 1 AND 100 "
            "AND cohort_bucket BETWEEN 0 AND 9999 "
            "AND cohort_bucket < rollout_percentage * 100",
            name="ck_terminal_ota_attempts_cohort",
        ),
        sa.CheckConstraint(
            "(state IN " + TERMINAL_STATES + " AND terminal_at IS NOT NULL) OR "
            "(state IN " + ACTIVE_STATES + " AND terminal_at IS NULL)",
            name="ck_terminal_ota_attempts_terminal_shape",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["device_id"], ["terminal_devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["terminal_device_credentials.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_terminal_ota_attempts_attempt_id"),
        sa.UniqueConstraint("offer_id", name="uq_terminal_ota_attempts_offer_id"),
        sa.UniqueConstraint(
            "user_id", "client_request_id", name="uq_terminal_ota_attempts_user_request"
        ),
    )
    op.create_index(
        "ix_terminal_ota_attempts_user_created",
        "terminal_ota_attempts",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_terminal_ota_attempts_device_created",
        "terminal_ota_attempts",
        ["device_id", "created_at"],
    )
    op.create_index(
        "uq_terminal_ota_attempts_active_device",
        "terminal_ota_attempts",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("state IN " + ACTIVE_STATES),
    )

    op.create_table(
        "terminal_ota_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_row_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("transition_kind", sa.String(length=24), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("running_version", sa.String(length=48), nullable=False),
        sa.Column("running_build_id", sa.String(length=40), nullable=False),
        sa.Column("running_partition", sa.String(length=8), nullable=False),
        sa.Column("boot_count", sa.BigInteger(), nullable=False),
        sa.Column("reset_reason", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "schema_version = 1 AND sequence > 0 AND sequence < 4294967296",
            name="ck_terminal_ota_events_sequence",
        ),
        sa.CheckConstraint(
            "state IN ('downloading','staged','booted_pending_validation','succeeded',"
            "'failed','rolled_back','recovery_required')",
            name="ck_terminal_ota_events_state",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$' AND running_build_id ~ '^[0-9a-f]{40}$'",
            name="ck_terminal_ota_events_hashes",
        ),
        sa.CheckConstraint(
            "transition_kind IN ('advance','advance_with_gap')",
            name="ck_terminal_ota_events_transition",
        ),
        sa.CheckConstraint(
            "running_partition IN ('ota_0','ota_1') "
            "AND boot_count > 0 AND boot_count < 4294967296",
            name="ck_terminal_ota_events_runtime",
        ),
        sa.CheckConstraint(
            "(state IN ('failed','rolled_back','recovery_required') AND error_code IS NOT NULL) OR "
            "(state NOT IN ('failed','rolled_back','recovery_required') AND error_code IS NULL)",
            name="ck_terminal_ota_events_error_shape",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_row_id"], ["terminal_ota_attempts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_terminal_ota_events_event_id"),
        sa.UniqueConstraint(
            "attempt_row_id", "sequence", name="uq_terminal_ota_events_attempt_sequence"
        ),
    )
    op.create_index(
        "ix_terminal_ota_events_attempt_received",
        "terminal_ota_events",
        ["attempt_row_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_terminal_ota_events_attempt_received", table_name="terminal_ota_events"
    )
    op.drop_table("terminal_ota_events")
    op.drop_index(
        "uq_terminal_ota_attempts_active_device", table_name="terminal_ota_attempts"
    )
    op.drop_index(
        "ix_terminal_ota_attempts_device_created", table_name="terminal_ota_attempts"
    )
    op.drop_index(
        "ix_terminal_ota_attempts_user_created", table_name="terminal_ota_attempts"
    )
    op.drop_table("terminal_ota_attempts")
    op.drop_constraint(
        "ck_terminal_devices_ota_telemetry", "terminal_devices", type_="check"
    )
    op.drop_constraint(
        "ck_terminal_devices_hardware_revision", "terminal_devices", type_="check"
    )
    for name in (
        "last_ota_telemetry_at",
        "last_ota_external_power",
        "last_ota_battery_pct",
        "last_ota_battery_mv",
        "last_ota_boot_count",
        "last_ota_partition",
        "last_ota_build_id",
        "last_ota_fw_version",
        "hardware_revision_confirmed_at",
        "hardware_revision",
    ):
        op.drop_column("terminal_devices", name)
