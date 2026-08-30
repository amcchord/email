"""Safe retrieval and caching for received email attachments."""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import re
import secrets
import stat
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.account import GoogleAccount
from backend.models.email import Attachment, Email
from backend.services.attachment_cache import (
    AttachmentCachePolicy,
    CacheKey,
    acquire_entry_lease,
    canonical_cache_path,
    ensure_private_cache_parent,
    open_canonical_cache_file,
    open_canonical_cache_parent,
    reserve_cache_capacity,
    run_blocking_cache_operation,
)
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


def _read_bounded_file(
    storage_root: Path,
    user_id: int,
    account_id: int,
    email_id: int,
    attachment_id: int,
    expected_size: int | None,
) -> bytes:
    descriptor = open_canonical_cache_file(
        storage_root,
        user_id,
        account_id,
        email_id,
        attachment_id,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("Attachment cache entry is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as file_handle:
            content = file_handle.read(MAX_ATTACHMENT_DOWNLOAD_BYTES + 1)
        validated = _validate_content_size(content, expected_size)
        try:
            os.utime(descriptor, None)
        except OSError:
            logger.warning("Attachment cache access-time update failed", exc_info=True)
        return validated
    finally:
        os.close(descriptor)


def _write_private_file_atomic(
    storage_root: Path,
    user_id: int,
    account_id: int,
    email_id: int,
    attachment_id: int,
    content: bytes,
) -> None:
    parent_descriptor = open_canonical_cache_parent(
        storage_root,
        user_id,
        account_id,
        email_id,
    )
    filename = f"{attachment_id}.blob"
    temporary_name = f".{filename}-{secrets.token_hex(8)}"
    temporary_descriptor = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        temporary_descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fchmod(temporary_descriptor, 0o600)
        with os.fdopen(temporary_descriptor, "wb", closefd=False) as file_handle:
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        try:
            existing_metadata = os.stat(
                filename,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing_metadata = None
        if existing_metadata is not None and (
            stat.S_ISLNK(existing_metadata.st_mode)
            or not stat.S_ISREG(existing_metadata.st_mode)
        ):
            raise OSError("Unsafe attachment cache replacement target")
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        temporary_name = ""
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


async def _load_live_cache_keys(
    db: AsyncSession,
    user_id: int,
) -> set[CacheKey] | None:
    """Return the canonical entries currently owned by one user, or fail closed."""
    try:
        result = await db.execute(
            select(Email.account_id, Email.id, Attachment.id)
            .select_from(Attachment)
            .join(Email, Email.id == Attachment.email_id)
            .join(GoogleAccount, GoogleAccount.id == Email.account_id)
            .where(GoogleAccount.user_id == user_id)
        )
        return {
            (int(account_id), int(email_id), int(attachment_id))
            for account_id, email_id, attachment_id in result.all()
        }
    except Exception:
        # A database outage must never be interpreted as an empty ownership set.
        logger.warning("Attachment cache ownership snapshot unavailable", exc_info=True)
        return None


async def load_attachment_bytes(
    db: AsyncSession,
    email: Email,
    attachment: Attachment,
    account: GoogleAccount,
    *,
    storage_root: str | Path | None = None,
    credential_resolver: Callable[[AsyncSession], Awaitable[tuple[str, str]]] | None = None,
    gmail_service_factory: Callable[..., GmailService] | None = None,
    cache_policy: AttachmentCachePolicy | None = None,
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

    try:
        cache_path = canonical_cache_path(
            root,
            int(account.user_id),
            int(email.account_id),
            int(email.id),
            int(attachment.id),
        )
    except (TypeError, ValueError) as exc:
        raise AttachmentDownloadError("Attachment cache path is invalid") from exc

    try:
        entry_lease = await run_blocking_cache_operation(
            acquire_entry_lease,
            root,
            int(account.user_id),
            int(email.account_id),
            int(email.id),
            int(attachment.id),
            release_result_on_cancel=True,
        )
    except OSError as exc:
        raise AttachmentDownloadError(
            "Attachment cache lease is unavailable",
            status_code=503,
            public_detail="Attachment download is temporarily unavailable",
        ) from exc
    if entry_lease is None:
        raise AttachmentDownloadError(
            "Attachment cache entry is busy",
            status_code=503,
            public_detail="Attachment download is temporarily unavailable",
        )

    try:
        try:
            await run_blocking_cache_operation(ensure_private_cache_parent, cache_path, root)
            try:
                return await run_blocking_cache_operation(
                    _read_bounded_file,
                    root,
                    int(account.user_id),
                    int(email.account_id),
                    int(email.id),
                    int(attachment.id),
                    attachment.size_bytes,
                )
            except FileNotFoundError:
                pass
            except AttachmentDownloadError:
                logger.warning(
                    "Attachment cache validation failed; falling back to Gmail",
                    exc_info=True,
                )
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise AttachmentDownloadError("Attachment cache path is invalid") from exc
                logger.warning(
                    "Attachment cache read failed; falling back to Gmail",
                    exc_info=True,
                )
        except AttachmentDownloadError:
            raise
        except OSError as exc:
            raise AttachmentDownloadError("Attachment cache path is invalid") from exc

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
                transport_timeout=ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("Gmail attachment client setup failed", exc_info=True)
            raise AttachmentDownloadError(
                "Attachment could not be downloaded",
                status_code=503,
                public_detail="Attachment download is temporarily unavailable",
            ) from exc

        try:
            raw_bytes = await asyncio.wait_for(
                gmail.get_attachment(
                    email.gmail_message_id,
                    attachment.gmail_attachment_id,
                    max_bytes=MAX_ATTACHMENT_DOWNLOAD_BYTES,
                ),
                timeout=ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS,
            )
        except ValueError as exc:
            if "size limit" in str(exc).lower():
                raise AttachmentDownloadError(
                    "Attachment exceeds the download size limit",
                    status_code=413,
                    public_detail="Attachment is too large to download",
                ) from exc
            raise AttachmentDownloadError(
                "Attachment service returned invalid content",
                public_detail="Attachment data is invalid",
            ) from exc
        except Exception as exc:
            logger.warning("Gmail attachment retrieval failed", exc_info=True)
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

        live_keys = await _load_live_cache_keys(db, int(account.user_id))
        try:
            reservation = await run_blocking_cache_operation(
                reserve_cache_capacity,
                root,
                int(account.user_id),
                reservation_bytes=len(raw_bytes),
                live_keys=live_keys,
                protected_key=(
                    int(email.account_id),
                    int(email.id),
                    int(attachment.id),
                ),
                policy=cache_policy,
                release_result_on_cancel=True,
            )
            try:
                if reservation.can_store:
                    await run_blocking_cache_operation(
                        _write_private_file_atomic,
                        root,
                        int(account.user_id),
                        int(email.account_id),
                        int(email.id),
                        int(attachment.id),
                        raw_bytes,
                    )
                else:
                    logger.warning(
                        "Attachment download succeeded but cache capacity was unavailable"
                    )
            finally:
                reservation.release()
        except Exception:
            logger.warning(
                "Attachment download succeeded but private caching failed",
                exc_info=True,
            )
        return raw_bytes
    finally:
        entry_lease.release()
