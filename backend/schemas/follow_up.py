"""Validation contracts for automatic follow-up account policies."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


WAKE_LOCAL_TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


class FollowUpPolicyValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    delay_days: StrictInt = Field(default=3, ge=1, le=30)
    wake_local_time: str = "09:00"
    time_zone: str = Field(default="UTC", min_length=1, max_length=64)
    weekdays_only: StrictBool = True

    @field_validator("wake_local_time")
    @classmethod
    def validate_wake_local_time(cls, value: str) -> str:
        if not WAKE_LOCAL_TIME_RE.fullmatch(value):
            raise ValueError("wake_local_time must use 24-hour HH:MM format")
        return value

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("time_zone must be a valid IANA time zone") from error
        return value


class FollowUpPolicyReplace(FollowUpPolicyValues):
    expected_revision: StrictInt = Field(ge=0)


class FollowUpPolicyResponse(FollowUpPolicyValues):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    account_id: int
    account_email: str
    revision: int = Field(ge=0)


class FollowUpPolicyListResponse(BaseModel):
    accounts: list[FollowUpPolicyResponse]
    total: int = Field(ge=0)
