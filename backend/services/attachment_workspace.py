"""Bounded, provider-free attachment metadata queries."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from email.utils import getaddresses
import hashlib
import hmac
import json
import re
import unicodedata
from typing import Any

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.email import Attachment, Email
from backend.schemas.attachment_workspace import (
    AttachmentWorkspaceItemResponse,
    AttachmentWorkspaceQueryResponse,
)
from backend.services.attachments import safe_attachment_filename, safe_content_type


CURSOR_VERSION = 1

_MAILBOX_ADDRESS_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)

_IMAGE_EXTENSIONS = ("gif", "heic", "heif", "jpeg", "jpg", "png", "webp")
_ARCHIVE_EXTENSIONS = ("7z", "bz2", "cab", "gz", "rar", "tar", "tgz", "xz", "zip")
_DOCUMENT_EXTENSIONS = (
    "csv", "doc", "docx", "json", "log", "md", "ods", "odt", "pdf",
    "ppt", "pptx", "rtf", "txt", "xls", "xlsx",
)
_ARCHIVE_MIMES = (
    "application/gzip",
    "application/vnd.rar",
    "application/x-7z-compressed",
    "application/x-bzip2",
    "application/x-rar-compressed",
    "application/x-tar",
    "application/zip",
)
_DOCUMENT_MIMES = (
    "application/json",
    "application/msword",
    "application/pdf",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)


class AttachmentWorkspaceNotFound(Exception):
    """Raised when an account scope is unavailable without disclosing why."""


class AttachmentWorkspaceInvalidCursor(Exception):
    """Raised when a cursor is malformed, stale, or belongs to another query."""


def _row_value(row: Any, name: str, default=None):
    mapping = getattr(row, "_mapping", None)
    if mapping is not None and name in mapping:
        return mapping[name]
    return getattr(row, name, default)


def _filter_digest(*, account_id: int, query: str, kind: str, direction: str) -> str:
    canonical = json.dumps(
        {
            "account_id": account_id,
            "direction": direction,
            "kind": kind,
            "query": query.casefold(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )


def _encode_cursor(
    *,
    secret_key: str,
    user_id: int,
    account_id: int,
    query: str,
    kind: str,
    direction: str,
    message_date: datetime | None,
    email_id: int,
    attachment_id: int,
) -> str:
    payload = json.dumps(
        {
            "v": CURSOR_VERSION,
            "u": user_id,
            "f": _filter_digest(
                account_id=account_id,
                query=query,
                kind=kind,
                direction=direction,
            ),
            "d": message_date.isoformat() if message_date is not None else None,
            "e": email_id,
            "a": attachment_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


def _decode_cursor(
    cursor: str,
    *,
    secret_key: str,
    user_id: int,
    account_id: int,
    query: str,
    kind: str,
    direction: str,
) -> tuple[datetime | None, int, int]:
    try:
        payload_part, signature_part = cursor.split(".")
        payload = _b64decode(payload_part)
        signature = _b64decode(signature_part)
        expected = hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature mismatch")
        decoded = json.loads(payload)
        expected_filter = _filter_digest(
            account_id=account_id,
            query=query,
            kind=kind,
            direction=direction,
        )
        if (
            not isinstance(decoded, dict)
            or decoded.get("v") != CURSOR_VERSION
            or decoded.get("u") != user_id
            or not hmac.compare_digest(str(decoded.get("f", "")), expected_filter)
        ):
            raise ValueError("cursor scope mismatch")
        email_id = decoded.get("e")
        attachment_id = decoded.get("a")
        if (
            isinstance(email_id, bool)
            or not isinstance(email_id, int)
            or email_id <= 0
            or isinstance(attachment_id, bool)
            or not isinstance(attachment_id, int)
            or attachment_id <= 0
        ):
            raise ValueError("invalid cursor IDs")
        date_value = decoded.get("d")
        if date_value is None:
            message_date = None
        elif isinstance(date_value, str):
            message_date = datetime.fromisoformat(date_value)
            if message_date.tzinfo is None:
                raise ValueError("cursor date lacks timezone")
        else:
            raise ValueError("invalid cursor date")
        return message_date, email_id, attachment_id
    except (
        AttributeError,
        TypeError,
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        raise AttachmentWorkspaceInvalidCursor("Attachment cursor is invalid") from error


def _extension_clause(filename, extensions: tuple[str, ...]):
    return or_(*(filename.like(f"%.{extension}") for extension in extensions))


def _kind_clauses():
    mime = func.split_part(
        func.lower(func.coalesce(Attachment.content_type, "")),
        ";",
        1,
    )
    filename = func.lower(func.coalesce(Attachment.filename, ""))
    image = or_(mime.like("image/%"), _extension_clause(filename, _IMAGE_EXTENSIONS))
    archive = or_(mime.in_(_ARCHIVE_MIMES), _extension_clause(filename, _ARCHIVE_EXTENSIONS))
    document = and_(
        not_(or_(image, archive)),
        or_(
            mime.like("text/%"),
            mime.in_(_DOCUMENT_MIMES),
            _extension_clause(filename, _DOCUMENT_EXTENSIONS),
        ),
    )
    other = not_(or_(image, archive, document))
    return {
        "all": None,
        "document": document,
        "image": image,
        "archive": archive,
        "other": other,
    }


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _cursor_clause(message_date: datetime | None, email_id: int, attachment_id: int):
    if message_date is None:
        return and_(
            Email.date.is_(None),
            or_(
                Email.id < email_id,
                and_(Email.id == email_id, Attachment.id < attachment_id),
            ),
        )
    return or_(
        Email.date < message_date,
        Email.date.is_(None),
        and_(
            Email.date == message_date,
            or_(
                Email.id < email_id,
                and_(Email.id == email_id, Attachment.id < attachment_id),
            ),
        ),
    )


def _attachment_query_statement(
    *,
    user_id: int,
    account_id: int,
    query: str,
    kind: str,
    direction: str,
    page_size: int,
    cursor_position: tuple[datetime | None, int, int] | None = None,
):
    statement = (
        select(
            Email.account_id.label("account_id"),
            Attachment.id.label("attachment_id"),
            Attachment.email_id.label("email_id"),
            Attachment.filename.label("filename"),
            Attachment.content_type.label("content_type"),
            Attachment.size_bytes.label("size_bytes"),
            Email.date.label("message_date"),
            Email.from_name.label("sender_name"),
            Email.from_address.label("sender_address"),
            Email.subject.label("subject"),
            Email.is_sent.label("is_sent"),
        )
        .select_from(Attachment)
        .join(Email, Email.id == Attachment.email_id)
        .join(GoogleAccount, GoogleAccount.id == Email.account_id)
        .where(
            GoogleAccount.user_id == user_id,
            GoogleAccount.id == account_id,
            GoogleAccount.is_active.is_(True),
            Email.account_id == account_id,
            Email.is_draft.is_not(True),
            Email.is_spam.is_not(True),
            Email.is_trash.is_not(True),
            Attachment.is_inline.is_not(True),
        )
    )
    if query:
        escaped = _escape_like_literal(query.lower())
        literal_pattern = f"%{escaped}%"
        statement = statement.where(
            or_(
                func.lower(func.coalesce(Attachment.filename, "")).like(
                    literal_pattern,
                    escape="\\",
                ),
                func.lower(func.coalesce(Email.subject, "")).like(
                    literal_pattern,
                    escape="\\",
                ),
                func.lower(func.coalesce(Email.from_name, "")).like(
                    literal_pattern,
                    escape="\\",
                ),
                func.lower(func.coalesce(Email.from_address, "")).like(
                    literal_pattern,
                    escape="\\",
                ),
            )
        )
    kind_clause = _kind_clauses()[kind]
    if kind_clause is not None:
        statement = statement.where(kind_clause)
    if direction == "sent":
        statement = statement.where(Email.is_sent.is_(True))
    elif direction == "received":
        statement = statement.where(Email.is_sent.is_not(True))
    if cursor_position is not None:
        statement = statement.where(_cursor_clause(*cursor_position))
    return statement.order_by(
        Email.date.desc().nulls_last(),
        Email.id.desc(),
        Attachment.id.desc(),
    ).limit(page_size + 1)


def _safe_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = "".join(
        character
        for character in str(value)
        if not unicodedata.category(character).startswith("C")
    )
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:max_length] or None


def _safe_sender_address(value: Any) -> str | None:
    raw = _safe_text(value, 998)
    if raw is None:
        return None
    parsed = getaddresses([raw])
    if len(parsed) != 1:
        return None
    address = parsed[0][1].strip().lower()
    if len(address) > 254 or not _MAILBOX_ADDRESS_RE.fullmatch(address):
        return None
    return address


def _item_from_row(row: Any, *, account_id: int) -> AttachmentWorkspaceItemResponse:
    row_account_id = int(_row_value(row, "account_id", 0))
    if row_account_id != account_id:
        raise AttachmentWorkspaceNotFound("Attachment workspace not found")
    size_value = _row_value(row, "size_bytes")
    size_bytes = size_value if isinstance(size_value, int) and size_value >= 0 else None
    return AttachmentWorkspaceItemResponse(
        account_id=row_account_id,
        attachment_id=int(_row_value(row, "attachment_id", 0)),
        email_id=int(_row_value(row, "email_id", 0)),
        filename=safe_attachment_filename(_row_value(row, "filename")),
        content_type=safe_content_type(_row_value(row, "content_type")),
        size_bytes=size_bytes,
        message_date=_row_value(row, "message_date"),
        sender_name=_safe_text(_row_value(row, "sender_name"), 255),
        sender_address=_safe_sender_address(_row_value(row, "sender_address")),
        subject=_safe_text(_row_value(row, "subject"), 500),
        is_sent=bool(_row_value(row, "is_sent", False)),
    )


async def query_attachment_workspace(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    secret_key: str,
    query: str = "",
    kind: str = "all",
    direction: str = "all",
    cursor: str | None = None,
    page_size: int = 50,
) -> AttachmentWorkspaceQueryResponse:
    account_result = await db.execute(
        select(GoogleAccount.id).where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user_id,
            GoogleAccount.is_active.is_(True),
        )
    )
    if account_result.scalar_one_or_none() is None:
        raise AttachmentWorkspaceNotFound("Attachment workspace not found")

    cursor_position = None
    if cursor is not None:
        cursor_position = _decode_cursor(
            cursor,
            secret_key=secret_key,
            user_id=user_id,
            account_id=account_id,
            query=query,
            kind=kind,
            direction=direction,
        )
    statement = _attachment_query_statement(
        user_id=user_id,
        account_id=account_id,
        query=query,
        kind=kind,
        direction=direction,
        page_size=page_size,
        cursor_position=cursor_position,
    )
    result = await db.execute(statement)
    rows = list(result.all())
    has_more = len(rows) > page_size
    visible_rows = rows[:page_size]
    items = [_item_from_row(row, account_id=account_id) for row in visible_rows]
    next_cursor = None
    if has_more and visible_rows:
        last = visible_rows[-1]
        next_cursor = _encode_cursor(
            secret_key=secret_key,
            user_id=user_id,
            account_id=account_id,
            query=query,
            kind=kind,
            direction=direction,
            message_date=_row_value(last, "message_date"),
            email_id=int(_row_value(last, "email_id")),
            attachment_id=int(_row_value(last, "attachment_id")),
        )
    return AttachmentWorkspaceQueryResponse(
        account_id=account_id,
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )
