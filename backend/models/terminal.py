from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class TerminalSettings(Base):
    """Per-user e-ink terminal config: shared short URL code + Home Assistant link."""

    __tablename__ = "terminal_settings"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    # IANA timezone name (e.g. "America/New_York") used by the e-ink clock
    # renderer so the time on the panel matches the user's wall clock instead
    # of the server's UTC clock.
    timezone: Mapped[str] = mapped_column(
        String(100), nullable=False, default="America/New_York"
    )
    home_assistant_url: Mapped[str] = mapped_column(Text, nullable=True)
    home_assistant_token_encrypted: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", backref="terminal_settings")


class TerminalDevice(Base):
    """One row per (user, MAC) seen checking in to /terminal/{code}/."""

    __tablename__ = "terminal_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        default=uuid4,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    mac: Mapped[str] = mapped_column(String(17), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    variant: Mapped[str] = mapped_column(String(32), nullable=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="clock")
    content_config = mapped_column(JSONB, nullable=True)
    # Override for the schedule.json `next_checkin_sec`. NULL = use the
    # variant's baseline cadence. Server enforces a 30s floor and a 21600s
    # (6 hour) ceiling.
    refresh_interval_sec: Mapped[int] = mapped_column(Integer, nullable=True)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_wake_reason: Mapped[str] = mapped_column(String(32), nullable=True)
    last_battery_mv: Mapped[int] = mapped_column(Integer, nullable=True)
    last_battery_pct: Mapped[int] = mapped_column(Integer, nullable=True)
    last_rssi_dbm: Mapped[int] = mapped_column(Integer, nullable=True)
    last_uptime_sec: Mapped[int] = mapped_column(Integer, nullable=True)
    last_boot_count: Mapped[int] = mapped_column(Integer, nullable=True)
    last_fw_version: Mapped[str] = mapped_column(String(64), nullable=True)
    last_image_etag: Mapped[str] = mapped_column(String(128), nullable=True)

    # Secure serial enrollment is deliberately additive. Existing devices stay
    # ``legacy`` until an owner completes a RET1 provisioning flow and the
    # resulting per-device credential is observed on the scoped route.
    hardware_model: Mapped[str | None] = mapped_column(String(16), nullable=True)
    enrollment_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="legacy",
        server_default=text("'legacy'"),
    )
    enrollment_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    enrollment_config_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    enrollment_release_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    enrollment_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enrollment_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enrollment_activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_secure_checkin_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", backref="terminal_devices")

    __table_args__ = (
        UniqueConstraint("user_id", "mac", name="uq_terminal_devices_user_mac"),
        UniqueConstraint("public_id", name="uq_terminal_devices_public_id"),
        CheckConstraint(
            "enrollment_state IN ('legacy','pending','enrolled','revoked','review')",
            name="ck_terminal_devices_enrollment_state",
        ),
        CheckConstraint(
            "enrollment_generation >= 0",
            name="ck_terminal_devices_enrollment_generation",
        ),
        CheckConstraint(
            "enrollment_state <> 'enrolled' OR "
            "(enrollment_generation > 0 AND enrollment_config_sha256 IS NOT NULL "
            "AND enrollment_activated_at IS NOT NULL)",
            name="ck_terminal_devices_enrolled_shape",
        ),
        Index("ix_terminal_devices_user_last_seen", "user_id", "last_seen_at"),
        Index("ix_terminal_devices_mac", "mac"),
        Index(
            "uq_terminal_devices_secure_mac",
            "mac",
            unique=True,
            postgresql_where=text("enrollment_state <> 'legacy'"),
        ),
    )


class TerminalDeviceCredential(Base):
    """Hashed, revocable credential for one securely enrolled terminal.

    The raw credential exists only in the browser-created device config and in
    the subsequent HTTPS request path. PostgreSQL stores only its SHA-256.
    """

    __tablename__ = "terminal_device_credentials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("terminal_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default=text("'candidate'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    device = relationship("TerminalDevice", backref="enrollment_credentials")

    __table_args__ = (
        UniqueConstraint(
            "token_sha256", name="uq_terminal_device_credentials_token_sha256"
        ),
        UniqueConstraint(
            "device_id",
            "generation",
            name="uq_terminal_device_credentials_device_generation",
        ),
        CheckConstraint(
            "token_sha256 ~ '^[0-9a-f]{64}$' AND "
            "config_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_terminal_device_credentials_hashes",
        ),
        CheckConstraint(
            "state IN ('candidate','active','rollback','revoked')",
            name="ck_terminal_device_credentials_state",
        ),
        CheckConstraint(
            "generation > 0",
            name="ck_terminal_device_credentials_generation",
        ),
        CheckConstraint(
            "(state = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(state <> 'revoked' AND revoked_at IS NULL)",
            name="ck_terminal_device_credentials_revocation",
        ),
        Index(
            "ix_terminal_device_credentials_device_state",
            "device_id",
            "state",
        ),
    )


class TerminalEnrollmentAttempt(Base):
    """One owner-scoped RET1 transcript and at most one issued ticket."""

    __tablename__ = "terminal_enrollment_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, default=uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("terminal_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    credential_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("terminal_device_credentials.id", ondelete="RESTRICT"),
        nullable=True,
    )
    client_intent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    intent_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    transcript_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(22), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, default="provision", server_default=text("'provision'")
    )
    device_model: Mapped[str] = mapped_column(String(16), nullable=False)
    device_mac: Mapped[str] = mapped_column(String(17), nullable=False)
    firmware_version: Mapped[str] = mapped_column(String(128), nullable=False)
    firmware_release_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enrollment_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    target_generation: Mapped[int] = mapped_column(Integer, nullable=False)

    client_ticket_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    ticket_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jti_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    compact_jws: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="initialized",
        server_default=text("'initialized'"),
    )
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    client_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_config_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", backref="terminal_enrollment_attempts")
    device = relationship("TerminalDevice", backref="enrollment_attempts")
    credential = relationship("TerminalDeviceCredential")

    __table_args__ = (
        UniqueConstraint(
            "attempt_id", name="uq_terminal_enrollment_attempts_attempt_id"
        ),
        UniqueConstraint(
            "user_id",
            "client_intent_id",
            name="uq_terminal_enrollment_attempts_user_intent",
        ),
        UniqueConstraint(
            "transcript_sha256",
            name="uq_terminal_enrollment_attempts_transcript",
        ),
        UniqueConstraint(
            "jti_sha256", name="uq_terminal_enrollment_attempts_jti_sha256"
        ),
        CheckConstraint(
            "operation IN ('provision','rollback')",
            name="ck_terminal_enrollment_attempts_operation",
        ),
        CheckConstraint(
            "status IN ('initialized','issued','client_confirmed','activated',"
            "'expired','superseded','review')",
            name="ck_terminal_enrollment_attempts_status",
        ),
        CheckConstraint(
            "observed_generation >= 0 AND target_generation > 0 "
            "AND target_generation < 4294967295 "
            "AND target_generation = observed_generation + 1",
            name="ck_terminal_enrollment_attempts_generations",
        ),
        CheckConstraint(
            "transcript_sha256 ~ '^[0-9a-f]{64}$' AND "
            "intent_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "(ticket_fingerprint IS NULL OR ticket_fingerprint ~ '^[0-9a-f]{64}$') AND "
            "(config_sha256 IS NULL OR config_sha256 ~ '^[0-9a-f]{64}$') AND "
            "(jti_sha256 IS NULL OR jti_sha256 ~ '^[0-9a-f]{64}$') AND "
            "(result_config_sha256 IS NULL OR result_config_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_terminal_enrollment_attempts_hashes",
        ),
        CheckConstraint(
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
        Index(
            "ix_terminal_enrollment_attempts_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_terminal_enrollment_attempts_device_status",
            "device_id",
            "status",
        ),
    )


class TerminalBatterySample(Base):
    """Sparse battery history used for runtime and charging prediction."""

    __tablename__ = "terminal_battery_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("terminal_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    battery_pct: Mapped[int] = mapped_column(Integer, nullable=True)
    battery_mv: Mapped[int] = mapped_column(Integer, nullable=True)
    boot_count: Mapped[int] = mapped_column(Integer, nullable=True)

    device = relationship("TerminalDevice", backref="battery_samples")

    __table_args__ = (
        Index(
            "ix_terminal_battery_samples_device_observed",
            "device_id",
            "observed_at",
        ),
    )


class TerminalWebDisplay(Base):
    """Revocable browser-display credential bound to one catalog view."""

    __tablename__ = "terminal_web_displays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    view_key: Mapped[str] = mapped_column(String(32), nullable=False)
    # Empty string represents a design-less view (for example, Clock). Keeping
    # this non-null lets PostgreSQL enforce one credential per combination.
    design_key: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    profile_key: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", backref="terminal_web_displays")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "view_key",
            "design_key",
            "profile_key",
            name="uq_terminal_web_displays_user_view",
        ),
        Index("ix_terminal_web_displays_user_id", "user_id"),
        Index("ix_terminal_web_displays_token", "token", unique=True),
    )
