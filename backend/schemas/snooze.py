from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, StrictInt, field_validator


SnoozeCondition = Literal["always", "if_no_reply"]
SnoozeStateFilter = Literal[
    "active", "scheduled", "returned", "cancelled", "failed", "all"
]


class SnoozeCreateRequest(BaseModel):
    email_id: StrictInt = Field(gt=0)
    wake_at: datetime
    time_zone: str = Field(min_length=1, max_length=64)
    condition: SnoozeCondition = "always"
    idempotency_key: UUID = Field(default_factory=uuid4)

    @field_validator("wake_at")
    @classmethod
    def require_zoned_wake_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("wake_at must include a UTC offset")
        return value.astimezone(timezone.utc)

    @field_validator("time_zone")
    @classmethod
    def require_iana_time_zone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("time_zone must be a valid IANA time zone") from exc
        return value


class SnoozeRescheduleRequest(BaseModel):
    wake_at: datetime
    time_zone: str = Field(min_length=1, max_length=64)

    @field_validator("wake_at")
    @classmethod
    def require_zoned_wake_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("wake_at must include a UTC offset")
        return value.astimezone(timezone.utc)

    @field_validator("time_zone")
    @classmethod
    def require_iana_time_zone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("time_zone must be a valid IANA time zone") from exc
        return value


class SnoozedEmailSummary(BaseModel):
    id: int
    gmail_message_id: str
    gmail_thread_id: str
    subject: str | None = None
    from_address: str | None = None
    from_name: str | None = None
    to_addresses: list = []
    date: datetime | None = None
    snippet: str | None = None
    is_read: bool = False
    is_starred: bool = False
    is_sent: bool = False
    is_trash: bool = False
    is_spam: bool = False
    has_attachments: bool = False
    labels: list = []
    account_email: str


class SnoozeResponse(BaseModel):
    id: UUID
    email_id: int | None
    account_id: int
    account_email: str
    gmail_thread_id: str
    wake_at: datetime
    time_zone: str
    condition: SnoozeCondition
    state: str
    status_detail: str | None = None
    archive_required: bool
    originally_in_inbox: bool
    conversation_message_count: int
    archive_action_request_id: UUID | None = None
    archive_undo_until: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None = None
    returned_at: datetime | None = None
    cancelled_at: datetime | None = None
    dismissed_at: datetime | None = None
    failed_at: datetime | None = None
    email: SnoozedEmailSummary | None


class SnoozeListResponse(BaseModel):
    items: list[SnoozeResponse]
    total: int
    limit: int
    offset: int
