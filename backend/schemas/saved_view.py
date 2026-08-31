"""Strict API contracts for private deterministic Saved Views."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from backend.services.email_search_query import (
    MAX_QUERY_LENGTH,
    SearchQueryError,
    parse_email_search,
)


MAX_SAVED_VIEWS = 12
MAX_SAVED_VIEW_NAME_CHARS = 80


def normalize_saved_view_name(value: str) -> str:
    if not isinstance(value, str):
        return value
    return " ".join(value.strip().split())


def normalize_saved_view_query(value: str) -> str:
    if not isinstance(value, str):
        return value
    candidate = value.strip()
    if not candidate:
        raise ValueError("Saved view query cannot be empty")
    try:
        parsed = parse_email_search(candidate)
    except SearchQueryError as error:
        raise ValueError(str(error)) from error
    if not parsed.groups:
        raise ValueError("Saved view query cannot be empty")
    return candidate


class SavedViewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_SAVED_VIEW_NAME_CHARS)
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    account_id: StrictInt | None = Field(default=None, gt=0)

    _normalize_name = field_validator("name", mode="before")(
        normalize_saved_view_name
    )
    _normalize_query = field_validator("query", mode="before")(
        normalize_saved_view_query
    )


class SavedViewCreate(SavedViewBody):
    create_id: UUID


class SavedViewReplace(SavedViewBody):
    revision: StrictInt = Field(gt=0)


class SavedViewResponse(SavedViewBody):
    id: UUID
    create_id: UUID
    position: int
    revision: int
    created_at: datetime
    updated_at: datetime


class SavedViewListResponse(BaseModel):
    items: list[SavedViewResponse]
    max_views: int = MAX_SAVED_VIEWS


class SavedViewReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_order: list[UUID] = Field(max_length=MAX_SAVED_VIEWS)
    view_ids: list[UUID] = Field(max_length=MAX_SAVED_VIEWS)

    @field_validator("expected_order", "view_ids")
    @classmethod
    def require_unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Saved view order cannot contain duplicate IDs")
        return value
