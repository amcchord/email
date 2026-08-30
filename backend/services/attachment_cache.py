"""Bounded, cross-process lifecycle management for canonical attachment blobs.

Only the browser-download namespace is managed here:

    <root>/<user_id>/<account_id>/<email_id>/<attachment_id>.blob

Legacy ``Attachment.storage_path`` values and every non-canonical path are
deliberately outside this module's authority.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import hashlib
import logging
import os
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

DEFAULT_USER_HARD_LIMIT_BYTES = 512 * 1024 * 1024
DEFAULT_USER_TARGET_BYTES = 384 * 1024 * 1024
DEFAULT_IDLE_RETENTION_SECONDS = 30 * 24 * 60 * 60
DEFAULT_ORPHAN_GRACE_SECONDS = 24 * 60 * 60
DEFAULT_TEMP_GRACE_SECONDS = 60 * 60
DEFAULT_LOCK_TIMEOUT_SECONDS = 35.0
ENTRY_LOCK_SHARDS = 4096
USER_LOCK_SHARDS = 1024

_POSITIVE_ID_RE = re.compile(r"^[1-9][0-9]*$")
_BLOB_RE = re.compile(r"^([1-9][0-9]*)\.blob$")
_TEMP_RE = re.compile(r"^\.([1-9][0-9]*)\.blob-[A-Za-z0-9_-]+$")

CacheKey = tuple[int, int, int]
_BlockingResult = TypeVar("_BlockingResult")


async def run_blocking_cache_operation(
    operation: Callable[..., _BlockingResult],
    *args,
    release_result_on_cancel: bool = False,
    **kwargs,
) -> _BlockingResult:
    """Finish a filesystem syscall before propagating task cancellation."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            cancelled = True
            continue
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        try:
            if release_result_on_cancel and result is not None:
                result.release()
        finally:
            raise asyncio.CancelledError
    return result


@dataclass(frozen=True)
class AttachmentCachePolicy:
    """Validated per-user cache bounds."""

    hard_limit_bytes: int = DEFAULT_USER_HARD_LIMIT_BYTES
    target_bytes: int = DEFAULT_USER_TARGET_BYTES
    idle_retention_seconds: int = DEFAULT_IDLE_RETENTION_SECONDS
    orphan_grace_seconds: int = DEFAULT_ORPHAN_GRACE_SECONDS
    temp_grace_seconds: int = DEFAULT_TEMP_GRACE_SECONDS

    def __post_init__(self) -> None:
        if self.hard_limit_bytes <= 0:
            raise ValueError("Attachment cache hard limit must be positive")
        if not 0 < self.target_bytes <= self.hard_limit_bytes:
            raise ValueError("Attachment cache target must be within the hard limit")
        for value, label in (
            (self.idle_retention_seconds, "idle retention"),
            (self.orphan_grace_seconds, "orphan grace"),
            (self.temp_grace_seconds, "temporary-file grace"),
        ):
            if value < 0:
                raise ValueError(f"Attachment cache {label} cannot be negative")


@dataclass
class AttachmentCacheReport:
    scanned_files: int = 0
    retained_files: int = 0
    retained_bytes: int = 0
    removed_files: int = 0
    removed_bytes: int = 0
    retention_removals: int = 0
    orphan_removals: int = 0
    quota_removals: int = 0
    temp_removals: int = 0
    busy_files: int = 0
    unsafe_entries: int = 0
    errors: int = 0
    can_store: bool = True


@dataclass(frozen=True)
class _Candidate:
    key: CacheKey
    path: Path
    size: int
    modified_at: float
    device: int
    inode: int
    is_orphan: bool


@dataclass
class FileLease:
    """An advisory exclusive lock held by an open private lock file."""

    descriptor: int | None

    def release(self) -> None:
        if self.descriptor is None:
            return
        descriptor = self.descriptor
        self.descriptor = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> FileLease:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.release()


@dataclass
class CacheReservation:
    """A successful reservation keeps the per-user quota lease until release."""

    report: AttachmentCacheReport
    lease: FileLease | None = field(default=None, repr=False)

    @property
    def can_store(self) -> bool:
        return self.report.can_store and self.lease is not None

    def release(self) -> None:
        if self.lease is not None:
            self.lease.release()
            self.lease = None

    def __enter__(self) -> CacheReservation:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.release()


def canonical_cache_path(
    storage_root: Path,
    user_id: int,
    account_id: int,
    email_id: int,
    attachment_id: int,
) -> Path:
    """Derive a canonical path only from positive owned database IDs."""
    identifiers = (user_id, account_id, email_id, attachment_id)
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in identifiers):
        raise ValueError("Attachment cache identifiers must be positive integers")
    return (
        storage_root
        / str(user_id)
        / str(account_id)
        / str(email_id)
        / f"{attachment_id}.blob"
    )


def _lock_root(storage_root: Path) -> Path:
    return storage_root / ".attachment-locks"


def _lock_shard(parts: tuple[int, ...], shard_count: int) -> int:
    payload = ":".join(str(part) for part in parts).encode("ascii")
    digest = hashlib.blake2b(payload, digest_size=8, person=b"mailcache").digest()
    return int.from_bytes(digest, "big") % shard_count


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise OSError(f"Unsafe attachment cache directory: {path}")
    os.chmod(path, 0o700)


def ensure_private_cache_parent(path: Path, storage_root: Path) -> None:
    """Create the canonical directory chain through stable no-follow dirfds."""
    _ensure_private_directory(storage_root)
    relative_parent = path.parent.relative_to(storage_root)
    if len(relative_parent.parts) != 3:
        raise OSError("Attachment cache directory depth is not canonical")
    descriptor = os.open(storage_root, _directory_open_flags())
    try:
        for component in relative_parent.parts:
            if not _POSITIVE_ID_RE.fullmatch(component):
                raise OSError("Attachment cache directory is not canonical")
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            report = AttachmentCacheReport()
            child_descriptor = _open_verified_numeric_directory(
                descriptor,
                component,
                report,
            )
            if child_descriptor is None:
                raise OSError("Attachment cache directory topology is unsafe")
            os.fchmod(child_descriptor, 0o700)
            os.close(descriptor)
            descriptor = child_descriptor
    finally:
        os.close(descriptor)


def open_canonical_cache_file(
    storage_root: Path,
    user_id: int,
    account_id: int,
    email_id: int,
    attachment_id: int,
) -> int:
    """Open one canonical blob read-only without following any parent or leaf link."""
    canonical_cache_path(
        storage_root,
        user_id,
        account_id,
        email_id,
        attachment_id,
    )
    descriptor = os.open(storage_root, _directory_open_flags())
    try:
        for component in (user_id, account_id, email_id):
            report = AttachmentCacheReport()
            child_descriptor = _open_verified_numeric_directory(
                descriptor,
                str(component),
                report,
            )
            if child_descriptor is None:
                raise OSError(errno.ELOOP, "Attachment cache directory topology is unsafe")
            os.close(descriptor)
            descriptor = child_descriptor
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        return os.open(f"{attachment_id}.blob", flags, dir_fd=descriptor)
    finally:
        os.close(descriptor)


def open_canonical_cache_parent(
    storage_root: Path,
    user_id: int,
    account_id: int,
    email_id: int,
) -> int:
    """Open the exact canonical email directory for an atomic leaf operation."""
    probe_path = canonical_cache_path(storage_root, user_id, account_id, email_id, 1)
    ensure_private_cache_parent(probe_path, storage_root)
    descriptor = os.open(storage_root, _directory_open_flags())
    try:
        for component in (user_id, account_id, email_id):
            report = AttachmentCacheReport()
            child_descriptor = _open_verified_numeric_directory(
                descriptor,
                str(component),
                report,
            )
            if child_descriptor is None:
                raise OSError(errno.ELOOP, "Attachment cache directory topology is unsafe")
            os.close(descriptor)
            descriptor = child_descriptor
        result = descriptor
        descriptor = -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _private_lock_path(path: Path) -> None:
    current = path.parent
    pending: list[Path] = []
    while current.name and current != current.parent:
        pending.append(current)
        if current.name == ".attachment-locks":
            break
        current = current.parent
    if not pending or pending[-1].name != ".attachment-locks":
        raise OSError("Attachment lease is outside the lock namespace")
    _ensure_private_directory(pending[-1].parent)
    for directory in reversed(pending):
        _ensure_private_directory(directory)


def _acquire_lease(
    lock_path: Path,
    *,
    blocking: bool,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> FileLease | None:
    _private_lock_path(lock_path)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return FileLease(descriptor)
        except BlockingIOError:
            if not blocking or time.monotonic() >= deadline:
                os.close(descriptor)
                return None
            time.sleep(0.025)
        except Exception:
            os.close(descriptor)
            raise


def acquire_entry_lease(
    storage_root: Path,
    user_id: int,
    account_id: int,
    email_id: int,
    attachment_id: int,
    *,
    blocking: bool = True,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> FileLease | None:
    canonical_cache_path(storage_root, user_id, account_id, email_id, attachment_id)
    shard = _lock_shard(
        (user_id, account_id, email_id, attachment_id),
        ENTRY_LOCK_SHARDS,
    )
    lock_path = (
        _lock_root(storage_root)
        / "entries"
        / f"{shard:04x}.lock"
    )
    return _acquire_lease(
        lock_path,
        blocking=blocking,
        timeout_seconds=timeout_seconds,
    )


def _acquire_user_lease(
    storage_root: Path,
    user_id: int,
    *,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> FileLease | None:
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ValueError("Attachment cache user ID must be a positive integer")
    shard = _lock_shard((user_id,), USER_LOCK_SHARDS)
    return _acquire_lease(
        _lock_root(storage_root) / "users" / f"{shard:03x}.lock",
        blocking=True,
        timeout_seconds=timeout_seconds,
    )


def acquire_maintenance_lease(storage_root: Path) -> FileLease | None:
    """Try to become the sole cross-process periodic lifecycle runner."""
    return _acquire_lease(
        _lock_root(storage_root) / "maintenance.lock",
        blocking=False,
        timeout_seconds=0,
    )


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_verified_numeric_directory(
    parent_descriptor: int,
    name: str,
    report: AttachmentCacheReport,
) -> int | None:
    if not _POSITIVE_ID_RE.fullmatch(name):
        return None
    try:
        before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        report.errors += 1
        return None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        report.unsafe_entries += 1
        return None
    try:
        descriptor = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent_descriptor,
        )
        after = os.fstat(descriptor)
    except OSError:
        report.errors += 1
        return None
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        os.close(descriptor)
        report.errors += 1
        return None
    return descriptor


def _list_directory(descriptor: int, report: AttachmentCacheReport) -> list[str] | None:
    try:
        return os.listdir(descriptor)
    except OSError:
        report.errors += 1
        return None


def _scan_user_cache(
    storage_root: Path,
    user_id: int,
    *,
    live_keys: set[CacheKey] | None,
    now: float,
    policy: AttachmentCachePolicy,
    report: AttachmentCacheReport,
) -> tuple[
    list[_Candidate],
    list[tuple[CacheKey, Path, int, float, int, int]],
    int,
]:
    root_descriptor = None
    user_descriptor = None
    try:
        root_descriptor = os.open(storage_root, _directory_open_flags())
        user_descriptor = _open_verified_numeric_directory(
            root_descriptor,
            str(user_id),
            report,
        )
        if user_descriptor is None:
            return [], [], 0
        account_names = _list_directory(user_descriptor, report)
        if account_names is None:
            return [], [], 0

        candidates: list[_Candidate] = []
        stale_temps: list[tuple[CacheKey, Path, int, float, int, int]] = []
        temp_bytes = 0
        for account_name in account_names:
            account_descriptor = _open_verified_numeric_directory(
                user_descriptor,
                account_name,
                report,
            )
            if account_descriptor is None:
                continue
            try:
                email_names = _list_directory(account_descriptor, report)
                if email_names is None:
                    continue
                for email_name in email_names:
                    email_descriptor = _open_verified_numeric_directory(
                        account_descriptor,
                        email_name,
                        report,
                    )
                    if email_descriptor is None:
                        continue
                    try:
                        entry_names = _list_directory(email_descriptor, report)
                        if entry_names is None:
                            continue
                        for entry_name in entry_names:
                            blob_match = _BLOB_RE.fullmatch(entry_name)
                            temp_match = _TEMP_RE.fullmatch(entry_name)
                            if not blob_match and not temp_match:
                                continue
                            attachment_id = int((blob_match or temp_match).group(1))
                            account_id = int(account_name)
                            email_id = int(email_name)
                            key = (account_id, email_id, attachment_id)
                            path = (
                                storage_root
                                / str(user_id)
                                / account_name
                                / email_name
                                / entry_name
                            )
                            try:
                                metadata = os.stat(
                                    entry_name,
                                    dir_fd=email_descriptor,
                                    follow_symlinks=False,
                                )
                            except OSError:
                                report.errors += 1
                                continue
                            if not stat.S_ISREG(metadata.st_mode):
                                report.unsafe_entries += 1
                                continue
                            report.scanned_files += 1
                            if temp_match:
                                temp_bytes += metadata.st_size
                                if now - metadata.st_mtime >= policy.temp_grace_seconds:
                                    stale_temps.append((
                                        key,
                                        path,
                                        metadata.st_size,
                                        metadata.st_mtime,
                                        metadata.st_dev,
                                        metadata.st_ino,
                                    ))
                                continue
                            candidates.append(
                                _Candidate(
                                    key=key,
                                    path=path,
                                    size=metadata.st_size,
                                    modified_at=metadata.st_mtime,
                                    device=metadata.st_dev,
                                    inode=metadata.st_ino,
                                    is_orphan=live_keys is not None and key not in live_keys,
                                )
                            )
                    finally:
                        os.close(email_descriptor)
            finally:
                os.close(account_descriptor)
        return candidates, stale_temps, temp_bytes
    except FileNotFoundError:
        return [], [], 0
    except OSError:
        report.errors += 1
        return [], [], 0
    finally:
        if user_descriptor is not None:
            os.close(user_descriptor)
        if root_descriptor is not None:
            os.close(root_descriptor)


def _unlink_regular_file(
    storage_root: Path,
    user_id: int,
    key: CacheKey,
    filename: str,
    expected_size: int,
    expected_mtime: float,
    expected_device: int,
    expected_inode: int,
) -> bool:
    """Unlink only if the leased leaf still has the scanned identity."""
    root_descriptor = None
    user_descriptor = None
    account_descriptor = None
    email_descriptor = None
    try:
        account_id, email_id, _attachment_id = key
        report = AttachmentCacheReport()
        root_descriptor = os.open(storage_root, _directory_open_flags())
        user_descriptor = _open_verified_numeric_directory(
            root_descriptor,
            str(user_id),
            report,
        )
        if user_descriptor is None:
            raise OSError("Canonical user cache directory changed")
        account_descriptor = _open_verified_numeric_directory(
            user_descriptor,
            str(account_id),
            report,
        )
        if account_descriptor is None:
            raise OSError("Canonical account cache directory changed")
        email_descriptor = _open_verified_numeric_directory(
            account_descriptor,
            str(email_id),
            report,
        )
        if email_descriptor is None:
            raise OSError("Canonical email cache directory changed")
        metadata = os.stat(filename, dir_fd=email_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_size != expected_size
            or metadata.st_mtime != expected_mtime
            or metadata.st_dev != expected_device
            or metadata.st_ino != expected_inode
        ):
            return False
        os.unlink(filename, dir_fd=email_descriptor)
        return True
    except FileNotFoundError:
        return False
    finally:
        for descriptor in (
            email_descriptor,
            account_descriptor,
            user_descriptor,
            root_descriptor,
        ):
            if descriptor is not None:
                os.close(descriptor)


def _remove_candidate(
    storage_root: Path,
    user_id: int,
    candidate: _Candidate,
    report: AttachmentCacheReport,
    reason: str,
) -> bool:
    account_id, email_id, attachment_id = candidate.key
    lease = acquire_entry_lease(
        storage_root,
        user_id,
        account_id,
        email_id,
        attachment_id,
        blocking=False,
    )
    if lease is None:
        report.busy_files += 1
        return False
    with lease:
        try:
            removed = _unlink_regular_file(
                storage_root,
                user_id,
                candidate.key,
                candidate.path.name,
                candidate.size,
                candidate.modified_at,
                candidate.device,
                candidate.inode,
            )
        except OSError:
            report.errors += 1
            return False
    if not removed:
        report.unsafe_entries += 1
        return False
    report.removed_files += 1
    report.removed_bytes += candidate.size
    if reason == "retention":
        report.retention_removals += 1
    elif reason == "orphan":
        report.orphan_removals += 1
    elif reason == "quota":
        report.quota_removals += 1
    return True


def _remove_stale_temp(
    storage_root: Path,
    user_id: int,
    candidate: tuple[CacheKey, Path, int, float, int, int],
    report: AttachmentCacheReport,
) -> bool:
    key, path, size, modified_at, device, inode = candidate
    account_id, email_id, attachment_id = key
    lease = acquire_entry_lease(
        storage_root,
        user_id,
        account_id,
        email_id,
        attachment_id,
        blocking=False,
    )
    if lease is None:
        report.busy_files += 1
        return False
    with lease:
        try:
            removed = _unlink_regular_file(
                storage_root,
                user_id,
                key,
                path.name,
                size,
                modified_at,
                device,
                inode,
            )
        except OSError:
            report.errors += 1
            return False
    if removed:
        report.removed_files += 1
        report.removed_bytes += size
        report.temp_removals += 1
    else:
        report.unsafe_entries += 1
    return removed


def _apply_policy(
    storage_root: Path,
    user_id: int,
    *,
    reservation_bytes: int,
    live_keys: set[CacheKey] | None,
    protected_key: CacheKey | None,
    policy: AttachmentCachePolicy,
    now: float,
    report: AttachmentCacheReport,
) -> None:
    candidates, stale_temps, temp_bytes = _scan_user_cache(
        storage_root,
        user_id,
        live_keys=live_keys,
        now=now,
        policy=policy,
        report=report,
    )
    for stale_temp in sorted(stale_temps, key=lambda item: (item[3], item[0], item[1].name)):
        if _remove_stale_temp(storage_root, user_id, stale_temp, report):
            temp_bytes -= stale_temp[2]

    retained: list[_Candidate] = []
    current_bytes = temp_bytes + sum(candidate.size for candidate in candidates)
    for candidate in sorted(candidates, key=lambda item: (item.modified_at, item.key)):
        if candidate.key == protected_key:
            retained.append(candidate)
            continue
        age = now - candidate.modified_at
        reason = None
        if candidate.is_orphan and age >= policy.orphan_grace_seconds:
            reason = "orphan"
        elif not candidate.is_orphan and age >= policy.idle_retention_seconds:
            reason = "retention"
        if reason and _remove_candidate(storage_root, user_id, candidate, report, reason):
            current_bytes -= candidate.size
        else:
            retained.append(candidate)

    if reservation_bytes > policy.hard_limit_bytes:
        report.can_store = False
    elif current_bytes + reservation_bytes > policy.hard_limit_bytes:
        target_existing_bytes = max(0, policy.target_bytes - reservation_bytes)
        quota_candidates = sorted(
            (candidate for candidate in retained if candidate.key != protected_key),
            key=lambda item: (item.modified_at, item.key),
        )
        for candidate in quota_candidates:
            if current_bytes <= target_existing_bytes:
                break
            if _remove_candidate(storage_root, user_id, candidate, report, "quota"):
                current_bytes -= candidate.size

    if current_bytes + reservation_bytes > policy.hard_limit_bytes:
        report.can_store = False
    if report.errors:
        # Any unreadable or unstable portion of the canonical namespace makes
        # a hard-limit proof impossible. Downloaded bytes may still be served,
        # but the caller must not add another cache entry.
        report.can_store = False
    report.retained_bytes = current_bytes
    report.retained_files = max(0, report.scanned_files - report.removed_files)


def reserve_cache_capacity(
    storage_root: Path,
    user_id: int,
    *,
    reservation_bytes: int,
    live_keys: set[CacheKey] | None,
    protected_key: CacheKey | None,
    policy: AttachmentCachePolicy | None = None,
    now: float | None = None,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> CacheReservation:
    """Sweep one user and retain the quota lease for a subsequent atomic write."""
    active_policy = policy or AttachmentCachePolicy()
    report = AttachmentCacheReport()
    if reservation_bytes < 0:
        raise ValueError("Attachment cache reservation cannot be negative")
    try:
        lease = _acquire_user_lease(
            storage_root,
            user_id,
            timeout_seconds=timeout_seconds,
        )
    except OSError:
        report.errors += 1
        report.can_store = False
        return CacheReservation(report)
    if lease is None:
        report.busy_files += 1
        report.can_store = False
        return CacheReservation(report)
    try:
        _apply_policy(
            storage_root,
            user_id,
            reservation_bytes=reservation_bytes,
            live_keys=live_keys,
            protected_key=protected_key,
            policy=active_policy,
            now=time.time() if now is None else now,
            report=report,
        )
    except Exception:
        report.errors += 1
        report.can_store = False
        logger.warning("Attachment cache lifecycle sweep failed", exc_info=True)
    if not report.can_store:
        lease.release()
        lease = None
    logger.info(
        "Attachment cache lifecycle scanned=%s retained=%s retained_bytes=%s "
        "removed=%s removed_bytes=%s retention=%s orphan=%s quota=%s temp=%s "
        "busy=%s unsafe=%s errors=%s can_store=%s",
        report.scanned_files,
        report.retained_files,
        report.retained_bytes,
        report.removed_files,
        report.removed_bytes,
        report.retention_removals,
        report.orphan_removals,
        report.quota_removals,
        report.temp_removals,
        report.busy_files,
        report.unsafe_entries,
        report.errors,
        report.can_store,
    )
    return CacheReservation(report, lease)
