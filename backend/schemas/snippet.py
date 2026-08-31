"""Validation contracts for private reusable Personal Snippets."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
)


MAX_SNIPPET_NAME_CHARS = 120
MAX_SNIPPET_SHORTCUT_CHARS = 32
MAX_SNIPPET_TEXT_CHARS = 20_000
MAX_SNIPPET_HTML_CHARS = 50_000
MAX_PERSONAL_SNIPPETS = 250
SHORTCUT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_name(value: str) -> str:
    if not isinstance(value, str):
        return value
    return " ".join(value.strip().split())


def normalize_shortcut(value: str) -> str:
    if not isinstance(value, str):
        return value
    candidate = value.strip().lower()
    if candidate.startswith(";"):
        candidate = candidate[1:].strip()
    return candidate


def normalize_body(value: str) -> str:
    if not isinstance(value, str):
        return value
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if CONTROL_RE.search(value):
        raise ValueError("Snippet content contains unsupported control characters")
    return value


class SnippetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_SNIPPET_NAME_CHARS)
    shortcut: str = Field(min_length=1, max_length=MAX_SNIPPET_SHORTCUT_CHARS + 1)
    body_html: str = Field(min_length=1, max_length=MAX_SNIPPET_HTML_CHARS)
    body_text: str = Field(min_length=1, max_length=MAX_SNIPPET_TEXT_CHARS)

    _normalize_name = field_validator("name", mode="before")(normalize_name)
    _normalize_shortcut = field_validator("shortcut", mode="before")(normalize_shortcut)
    _normalize_body = field_validator("body_html", "body_text", mode="before")(
        normalize_body
    )

    @field_validator("shortcut")
    @classmethod
    def validate_shortcut(cls, value: str) -> str:
        if not SHORTCUT_RE.fullmatch(value):
            raise ValueError(
                "Shortcut must start with a letter or number and use only letters, "
                "numbers, hyphens, or underscores"
            )
        return value


class PersonalSnippetCreate(SnippetBody):
    snippet_id: UUID


class PersonalSnippetReplace(SnippetBody):
    expected_revision: StrictInt = Field(gt=0)


class PersonalSnippetResponse(SnippetBody):
    snippet_id: UUID
    revision: int
    created_at: datetime
    updated_at: datetime


class PersonalSnippetListResponse(BaseModel):
    snippets: list[PersonalSnippetResponse]
    total: int
    limit: int = MAX_PERSONAL_SNIPPETS
