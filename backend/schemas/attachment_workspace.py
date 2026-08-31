"""Private metadata-only contracts for the first-class attachment workspace."""

from datetime import datetime
from typing import Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


AttachmentKind = Literal["all", "document", "image", "archive", "other"]
AttachmentDirection = Literal["all", "received", "sent"]


class AttachmentWorkspaceQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: StrictInt = Field(gt=0)
    query: str = Field(default="", max_length=256)
    kind: AttachmentKind = "all"
    direction: AttachmentDirection = "all"
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    page_size: StrictInt = Field(default=50, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError("query contains control characters")
        return " ".join(value.split())


class AttachmentWorkspaceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    account_id: int = Field(gt=0)
    attachment_id: int = Field(gt=0)
    email_id: int = Field(gt=0)
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)
    message_date: datetime | None = None
    sender_name: str | None = Field(default=None, max_length=255)
    sender_address: str | None = Field(default=None, max_length=254)
    subject: str | None = Field(default=None, max_length=500)
    is_sent: bool


class AttachmentWorkspaceQueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    account_id: int = Field(gt=0)
    items: list[AttachmentWorkspaceItemResponse]
    next_cursor: str | None = Field(default=None, max_length=2048)
    has_more: bool
