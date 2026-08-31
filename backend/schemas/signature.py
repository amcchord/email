"""Validation contracts for private per-account signatures."""

import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


MAX_SIGNATURE_HTML_CHARS = 50_000
MAX_SIGNATURE_TEXT_CHARS = 20_000
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_signature_body(value: str) -> str:
    if not isinstance(value, str):
        return value
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if CONTROL_RE.search(value):
        raise ValueError("Signature content contains unsupported control characters")
    return value


class AccountSignatureValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    include_on_new: StrictBool = True
    include_on_replies: StrictBool = True
    include_on_forwards: StrictBool = True
    body_html: str = Field(default="", max_length=MAX_SIGNATURE_HTML_CHARS)
    body_text: str = Field(default="", max_length=MAX_SIGNATURE_TEXT_CHARS)

    _normalize_body = field_validator("body_html", "body_text", mode="before")(
        normalize_signature_body
    )


class AccountSignatureReplace(AccountSignatureValues):
    expected_revision: StrictInt = Field(ge=0)


class AccountSignatureResponse(AccountSignatureValues):
    account_id: int
    account_email: str
    revision: int = Field(ge=0)
    sanitizer_version: int = Field(ge=1)


class AccountSignatureListResponse(BaseModel):
    accounts: list[AccountSignatureResponse]
    total: int = Field(ge=0)


class SignatureSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: StrictBool
    account_id: StrictInt
    policy_revision: StrictInt = Field(ge=0)
    body_html: str = ""
    body_text: str = ""
    content_hash: str = Field(min_length=64, max_length=64)
    sanitizer_version: StrictInt = Field(ge=1)
