"""Safe retrieval and caching for received email attachments."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.account import GoogleAccount
from backend.models.email import Attachment, Email
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService

logger = logging.getLogger(__name__)

# Gmail normally limits message attachments to 25 MiB. A small margin keeps
# valid encoded messages usable while providing a firm application memory cap.
MAX_ATTACHMENT_DOWNLOAD_BYTES = 32 * 1024 * 1024
ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS = 30

_MIME_TYPE_RE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
    re.IGNORECASE,
)


class AttachmentDownloadError(Exception):
    """Raised when an owned attachment cannot currently be retrieved."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        public_detail: str = "Attachment is temporarily unavailable",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.public_detail = public_detail


def safe_attachment_filename(filename: str | None) -> str:
    """Return a display/download filename without path or control characters."""
    raw_name = (filename or "attachment").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(
        character
        for character in raw_name
        if not unicodedata.category(character).startswith("C")
    ).strip()
    if cleaned in {"", ".", ".."}:
        return "attachment"

    if len(cleaned) <= 180:
        return cleaned

    suffix = Path(cleaned).suffix[:24]
    stem_limit = max(1, 180 - len(suffix))
    return f"{cleaned[:stem_limit]}{suffix}"


def safe_content_type(content_type: str | None) -> str:
    """Allow a single syntactically valid MIME type and reject header data."""
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    if _MIME_TYPE_RE.fullmatch(mime_type):
        return mime_type
    return "application/octet-stream"


def attachment_content_disposition(filename: str | None) -> str:
    """Build an attachment header with safe ASCII and RFC 5987 filenames."""
    safe_name = safe_attachment_filename(filename)
    ascii_name = (
        unicodedata.normalize("NFKD", safe_name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", ascii_name).strip()
    if ascii_name in {"", ".", ".."}:
        ascii_name = "attachment"
    encoded_name = quote(safe_name, safe="")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )


def _cache_target(
    storage_root: Path,
    email: Email,
    attachment: Attachment,
    account: GoogleAccount,
) -> Path:
    return (
        storage_root
        / str(account.user_id)
        / str(email.account_id)
        / str(email.id)
        / f"{attachment.id}.blob"
    )


def _validate_content_size(content: bytes, expected_size: int | None) -> bytes:
    if not content:
        raise AttachmentDownloadError(
            "Attachment content is empty",
            public_detail="Attachment data is invalid",
        )
    if len(content) > MAX_ATTACHMENT_DOWNLOAD_BYTES:
        raise AttachmentDownloadError(
            "Attachment exceeds the download size limit",
            status_code=413,
            public_detail="Attachment is too large to download",
        )
    if expected_size is not None and len(content) != expected_size:
        raise AttachmentDownloadError(
            "Attachment content length does not match metadata",
            public_detail="Attachment data is invalid",
        )
    return content


def _read_bounded_file(path: Path, expected_size: int | None) -> bytes:
    with path.open("rb") as file_handle:
        content = file_handle.read(MAX_ATTACHMENT_DOWNLOAD_BYTES + 1)
    return _validate_content_size(content, expected_size)


def _write_private_file_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}-",
            delete=False,
        ) as file_handle:
            temporary_path = Path(file_handle.name)
            os.chmod(temporary_path, 0o600)
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


async def load_attachment_bytes(
    db: AsyncSession,
    email: Email,
    attachment: Attachment,
    account: GoogleAccount,
    *,
    storage_root: str | Path | None = None,
    credential_resolver: Callable[[AsyncSession], Awaitable[tuple[str, str]]] | None = None,
    gmail_service_factory: Callable[..., GmailService] | None = None,
) -> bytes:
    """Return attachment bytes from the private cache or the owning Gmail account."""
    configured_root = storage_root or get_settings().attachment_storage_path
    root = Path(configured_root).expanduser().resolve()

    if (
        attachment.size_bytes is not None
        and attachment.size_bytes > MAX_ATTACHMENT_DOWNLOAD_BYTES
    ):
        raise AttachmentDownloadError(
            "Attachment exceeds the download size limit",
            status_code=413,
            public_detail="Attachment is too large to download",
        )
    if attachment.size_bytes is not None and attachment.size_bytes <= 0:
        raise AttachmentDownloadError(
            "Attachment content is empty",
            status_code=409,
            public_detail="Attachment content is unavailable",
        )

    # Deliberately ignore the legacy filename-keyed storage_path. Cache reads
    # use only an ID-derived canonical location beneath the configured root.
    cache_path = _cache_target(root, email, attachment, account)
    try:
        resolved_cache_path = cache_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise AttachmentDownloadError("Attachment cache path is invalid") from exc
    if not resolved_cache_path.is_relative_to(root):
        raise AttachmentDownloadError("Attachment cache path is invalid")
    if resolved_cache_path != cache_path:
        raise AttachmentDownloadError("Attachment cache path is invalid")

    if cache_path.is_file() and not cache_path.is_symlink():
        try:
            cached_content = await asyncio.to_thread(
                _read_bounded_file,
                cache_path,
                attachment.size_bytes,
            )
            if attachment.storage_path != str(cache_path):
                previous_storage_path = attachment.storage_path
                try:
                    attachment.storage_path = str(cache_path)
                    await db.commit()
                except Exception:
                    attachment.storage_path = previous_storage_path
                    logger.warning(
                        "Attachment cache path normalization failed for attachment_id=%s",
                        attachment.id,
                        exc_info=True,
                    )
                    try:
                        await db.rollback()
                    except Exception:
                        logger.warning("Attachment cache rollback failed", exc_info=True)
            return cached_content
        except (OSError, AttachmentDownloadError):
            logger.warning(
                "Attachment cache read failed; falling back to Gmail",
                exc_info=True,
            )

    if not attachment.gmail_attachment_id:
        raise AttachmentDownloadError(
            "Attachment content is unavailable",
            status_code=409,
            public_detail="Attachment content is unavailable",
        )

    resolve_credentials = credential_resolver or get_google_credentials
    create_gmail_service = gmail_service_factory or GmailService
    try:
        client_id, client_secret = await resolve_credentials(db)
        gmail = create_gmail_service(
            account,
            client_id=client_id,
            client_secret=client_secret,
        )
        raw_bytes = await asyncio.wait_for(
            gmail.get_attachment(
                email.gmail_message_id,
                attachment.gmail_attachment_id,
                max_bytes=MAX_ATTACHMENT_DOWNLOAD_BYTES,
            ),
            timeout=ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "Gmail attachment retrieval failed for email_id=%s attachment_id=%s",
            email.id,
            attachment.id,
            exc_info=True,
        )
        raise AttachmentDownloadError(
            "Attachment could not be downloaded",
            status_code=503,
            public_detail="Attachment download is temporarily unavailable",
        ) from exc

    if not isinstance(raw_bytes, bytes):
        raise AttachmentDownloadError(
            "Attachment service returned invalid content",
            public_detail="Attachment data is invalid",
        )
    _validate_content_size(raw_bytes, attachment.size_bytes)

    try:
        resolved_parent = cache_path.parent.resolve()
        if not resolved_parent.is_relative_to(root):
            raise OSError("Attachment cache target escaped configured storage root")
        await asyncio.to_thread(_write_private_file_atomic, cache_path, raw_bytes)
        attachment.storage_path = str(cache_path)
        await db.commit()
    except Exception:
        logger.warning(
            "Attachment download succeeded but private caching failed for attachment_id=%s",
            attachment.id,
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            logger.warning("Attachment cache rollback failed", exc_info=True)

    return raw_bytes
