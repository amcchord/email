"""Validation contracts for private, metadata-only contact projections."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


ContactRelationship = Literal[
    "bidirectional",
    "inbound_only",
    "outbound_only",
]
ContactRelationshipFilter = Literal[
    "all",
    "bidirectional",
    "inbound_only",
    "outbound_only",
]
ContactDirection = Literal["bidirectional", "inbound_only", "outbound_only"]


class ContactQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: StrictInt = Field(gt=0)
    query: str = Field(default="", max_length=254)
    relationship: ContactRelationshipFilter = "all"
    page: StrictInt = Field(default=1, gt=0)
    page_size: StrictInt = Field(default=50, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())


class ContactProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: StrictInt = Field(gt=0)
    contact_key: str = Field(min_length=1, max_length=128)
    recent_limit: StrictInt = Field(default=8, ge=1, le=20)


class ContactCoverageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    rows_scanned: int = Field(ge=0)
    row_limit: int = Field(ge=1)
    history_may_be_truncated: bool
    observed_oldest_at: datetime | None = None
    observed_newest_at: datetime | None = None


class ContactSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    account_id: int = Field(gt=0)
    contact_key: str = Field(min_length=64, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    address: str = Field(max_length=254)
    formatted: str = Field(max_length=998)
    relationship: ContactRelationship
    observed_message_count: int = Field(ge=1)
    observed_received_count: int = Field(ge=0)
    observed_sent_count: int = Field(ge=0)
    observed_conversation_count: int = Field(ge=1)
    observed_first_at: datetime
    observed_last_at: datetime
    observed_last_received_at: datetime | None = None
    observed_last_sent_at: datetime | None = None


class ContactQueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    account_id: int = Field(gt=0)
    page: int = Field(gt=0)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    coverage: ContactCoverageResponse
    contacts: list[ContactSummaryResponse]


class RecentContactConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    account_id: int = Field(gt=0)
    anchor_email_id: int = Field(gt=0)
    thread_id: str | None = Field(default=None, max_length=255)
    observed_last_at: datetime
    observed_message_count: int = Field(ge=1)
    direction: ContactDirection


class ContactProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    account_id: int = Field(gt=0)
    contact: ContactSummaryResponse
    recent_conversations: list[RecentContactConversationResponse]
