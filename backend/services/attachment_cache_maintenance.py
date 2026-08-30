"""Periodic lifecycle sweep for inactive canonical attachment-cache users."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import select

from backend.config import get_settings
from backend.database import async_session
from backend.models.account import GoogleAccount
from backend.models.email import Attachment, Email
from backend.services.attachment_cache import (
    AttachmentCachePolicy,
    AttachmentCacheReport,
    CacheKey,
    acquire_maintenance_lease,
    reserve_cache_capacity,
    run_blocking_cache_operation,
)

logger = logging.getLogger(__name__)

MAINTENANCE_INITIAL_DELAY_SECONDS = 5 * 60
MAINTENANCE_INTERVAL_SECONDS = 24 * 60 * 60
MAINTENANCE_MAX_USERS_PER_RUN = 10_000
MAINTENANCE_MAX_RUNTIME_SECONDS = 15 * 60
_POSITIVE_ID_RE = re.compile(r"^[1-9][0-9]*$")

LiveKeyLoader = Callable[[int], Awaitable[set[CacheKey] | None]]


@dataclass
class AttachmentMaintenanceReport:
    discovered_users: int = 0
    processed_users: int = 0
    database_failures: int = 0
    skipped_busy: bool = False
    truncated: bool = False
    scanned_files: int = 0
    retained_files: int = 0
    retained_bytes: int = 0
    removed_files: int = 0
    removed_bytes: int = 0
    busy_files: int = 0
    unsafe_entries: int = 0
    errors: int = 0

    def include(self, lifecycle: AttachmentCacheReport) -> None:
        self.scanned_files += lifecycle.scanned_files
        self.retained_files += lifecycle.retained_files
        self.retained_bytes += lifecycle.retained_bytes
        self.removed_files += lifecycle.removed_files
        self.removed_bytes += lifecycle.removed_bytes
        self.busy_files += lifecycle.busy_files
        self.unsafe_entries += lifecycle.unsafe_entries
        self.errors += lifecycle.errors


def _canonical_user_ids(storage_root: Path) -> list[int]:
    """List real positive-numeric user directories without following links."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(storage_root, flags)
        user_ids = []
        for name in os.listdir(descriptor):
            if not _POSITIVE_ID_RE.fullmatch(name):
                continue
            try:
                metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                user_ids.append(int(name))
        return sorted(user_ids)
    except FileNotFoundError:
        return []
    finally:
        if descriptor is not None:
            os.close(descriptor)


async def _database_live_keys(user_id: int) -> set[CacheKey] | None:
    try:
        async with async_session() as db:
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
        logger.warning("Attachment maintenance ownership snapshot unavailable", exc_info=True)
        return None


async def run_attachment_cache_maintenance(
    *,
    storage_root: str | Path | None = None,
    live_key_loader: LiveKeyLoader | None = None,
    policy: AttachmentCachePolicy | None = None,
    now: float | None = None,
    max_users: int = MAINTENANCE_MAX_USERS_PER_RUN,
    max_runtime_seconds: float = MAINTENANCE_MAX_RUNTIME_SECONDS,
) -> AttachmentMaintenanceReport:
    """Sweep every bounded canonical user root under one global process lease."""
    report = AttachmentMaintenanceReport()
    configured_root = storage_root or get_settings().attachment_storage_path
    root = Path(configured_root).expanduser().resolve()
    global_lease = await run_blocking_cache_operation(
        acquire_maintenance_lease,
        root,
        release_result_on_cancel=True,
    )
    if global_lease is None:
        report.skipped_busy = True
        return report

    started = time.monotonic()
    load_live_keys = live_key_loader or _database_live_keys
    active_policy = policy or AttachmentCachePolicy()
    sweep_now = time.time() if now is None else now
    try:
        user_ids = await run_blocking_cache_operation(_canonical_user_ids, root)
        report.discovered_users = len(user_ids)
        if len(user_ids) > max_users:
            user_ids = user_ids[:max_users]
            report.truncated = True
        for user_id in user_ids:
            if time.monotonic() - started >= max_runtime_seconds:
                report.truncated = True
                break
            live_keys = await load_live_keys(user_id)
            if live_keys is None:
                report.database_failures += 1
            reservation = await run_blocking_cache_operation(
                reserve_cache_capacity,
                root,
                user_id,
                reservation_bytes=0,
                live_keys=live_keys,
                protected_key=None,
                policy=active_policy,
                now=sweep_now,
                timeout_seconds=1.0,
                release_result_on_cancel=True,
            )
            try:
                report.processed_users += 1
                report.include(reservation.report)
            finally:
                reservation.release()
    finally:
        global_lease.release()

    logger.info(
        "Attachment maintenance users=%s/%s removed=%s removed_bytes=%s "
        "retained=%s retained_bytes=%s db_failures=%s busy=%s unsafe=%s "
        "errors=%s truncated=%s",
        report.processed_users,
        report.discovered_users,
        report.removed_files,
        report.removed_bytes,
        report.retained_files,
        report.retained_bytes,
        report.database_failures,
        report.busy_files,
        report.unsafe_entries,
        report.errors,
        report.truncated,
    )
    return report


async def attachment_cache_maintenance_loop(
    stop_event: asyncio.Event,
    *,
    initial_delay_seconds: float = MAINTENANCE_INITIAL_DELAY_SECONDS,
    interval_seconds: float = MAINTENANCE_INTERVAL_SECONDS,
) -> None:
    """Run a duplicate-safe sweep after startup and once per day thereafter."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=initial_delay_seconds)
        return
    except TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            await run_attachment_cache_maintenance()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Attachment cache maintenance run failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
