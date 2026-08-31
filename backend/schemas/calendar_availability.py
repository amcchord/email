"""Frozen request and response contracts for private calendar availability."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


MAX_AVAILABILITY_ACCOUNTS = 20
MAX_AVAILABILITY_SLOTS = 256
LOCAL_TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")

AvailabilityCoverageState = Literal[
    "ready",
    "calendar_not_enabled",
    "reauthorization_required",
    "sync_incomplete",
    "stale",
    "sync_error",
    "syncing",
]


def _local_minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


class CalendarAvailabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=MAX_AVAILABILITY_ACCOUNTS,
    )
    start_date: date
    end_date: date
    timezone: str = Field(min_length=1, max_length=64)
    duration_minutes: Literal[15, 30, 45, 60, 90, 120]
    step_minutes: Literal[15, 30]
    day_start: str
    day_end: str
    include_weekends: StrictBool
    minimum_notice_minutes: StrictInt = Field(ge=0, le=10080)

    @field_validator("account_ids")
    @classmethod
    def require_unique_positive_accounts(cls, value: list[int]) -> list[int]:
        if any(account_id <= 0 for account_id in value):
            raise ValueError("account_ids must contain positive integers")
        if len(set(value)) != len(value):
            raise ValueError("account_ids must not contain duplicates")
        return value

    @field_validator("timezone")
    @classmethod
    def require_iana_timezone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must be a valid IANA time zone") from error
        return value

    @field_validator("day_start", "day_end")
    @classmethod
    def require_bounded_local_time(cls, value: str) -> str:
        if not LOCAL_TIME_RE.fullmatch(value):
            raise ValueError("local times must use 24-hour HH:MM format")
        minutes = _local_minutes(value)
        if not 6 * 60 <= minutes <= 22 * 60:
            raise ValueError("local times must be between 06:00 and 22:00")
        return value

    @model_validator(mode="after")
    def require_ordered_window(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if _local_minutes(self.day_end) <= _local_minutes(self.day_start):
            raise ValueError("day_end must be after day_start")
        return self


class CalendarAvailabilityCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int
    account_email: str
    state: AvailabilityCoverageState
    last_success_at: datetime | None


class CalendarAvailabilitySlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str


class CalendarAvailabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    generated_at: datetime
    timezone: str
    duration_minutes: int
    coverage: list[CalendarAvailabilityCoverage]
    slots: list[CalendarAvailabilitySlot]
