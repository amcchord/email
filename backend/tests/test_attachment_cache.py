import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import backend.services.attachment_cache as cache_module
from backend.services.attachment_cache import (
    AttachmentCachePolicy,
    acquire_entry_lease,
    canonical_cache_path,
    reserve_cache_capacity,
)


def _write_blob(
    root: Path,
    user_id: int,
    key: tuple[int, int, int],
    content: bytes,
    *,
    modified_at: float,
) -> Path:
    account_id, email_id, attachment_id = key
    path = canonical_cache_path(
        root,
        user_id,
        account_id,
        email_id,
        attachment_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (modified_at, modified_at))
    return path


def _policy(**overrides) -> AttachmentCachePolicy:
    values = {
        "hard_limit_bytes": 1024,
        "target_bytes": 768,
        "idle_retention_seconds": 10_000,
        "orphan_grace_seconds": 1_000,
        "temp_grace_seconds": 100,
    }
    values.update(overrides)
    return AttachmentCachePolicy(**values)


def test_canonical_cache_path_requires_positive_numeric_ids(tmp_path):
    expected = tmp_path / "5" / "7" / "41" / "83.blob"
    assert canonical_cache_path(tmp_path, 5, 7, 41, 83) == expected

    for identifiers in ((0, 7, 41, 83), (5, -7, 41, 83), (5, 7, 41, True)):
        with pytest.raises(ValueError):
            canonical_cache_path(tmp_path, *identifiers)


def test_lifecycle_removes_only_exact_canonical_entries_for_one_user(tmp_path):
    now = time.time()
    root = tmp_path / "cache"
    old_orphan = _write_blob(root, 1, (7, 41, 83), b"orphan", modified_at=now - 2_000)
    other_user = _write_blob(root, 2, (7, 41, 83), b"other", modified_at=now - 2_000)

    legacy = root / "1" / "7" / "41" / "generated-name.txt"
    legacy.write_bytes(b"legacy")
    malformed = root / "1" / "7" / "not-an-email" / "83.blob"
    malformed.parent.mkdir(parents=True)
    malformed.write_bytes(b"malformed")
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside")
    leaf_symlink = root / "1" / "7" / "41" / "84.blob"
    leaf_symlink.symlink_to(outside)
    fifo = root / "1" / "7" / "41" / "85.blob"
    os.mkfifo(fifo)
    parent_target = tmp_path / "parent-target"
    parent_target.mkdir()
    parent_sentinel = parent_target / "42" / "86.blob"
    parent_sentinel.parent.mkdir()
    parent_sentinel.write_bytes(b"parent-symlink")
    (root / "1" / "8").symlink_to(parent_target, target_is_directory=True)

    reservation = reserve_cache_capacity(
        root,
        1,
        reservation_bytes=0,
        live_keys=set(),
        protected_key=None,
        policy=_policy(),
        now=now,
    )
    try:
        assert reservation.can_store
        assert reservation.report.orphan_removals == 1
        assert reservation.report.unsafe_entries == 3
    finally:
        reservation.release()

    assert not old_orphan.exists()
    assert other_user.read_bytes() == b"other"
    assert legacy.read_bytes() == b"legacy"
    assert malformed.read_bytes() == b"malformed"
    assert leaf_symlink.is_symlink()
    assert fifo.exists()
    assert outside.read_bytes() == b"outside"
    assert parent_sentinel.read_bytes() == b"parent-symlink"


def test_lifecycle_honors_orphan_and_temp_grace_and_fails_closed_without_db(tmp_path):
    now = time.time()
    root = tmp_path / "cache"
    live_key = (7, 41, 81)
    stale_orphan = _write_blob(root, 1, (7, 41, 82), b"old", modified_at=now - 2_000)
    fresh_orphan = _write_blob(root, 1, (7, 41, 83), b"fresh", modified_at=now - 10)
    outage_orphan = _write_blob(root, 2, (7, 41, 84), b"outage", modified_at=now - 2_000)
    _write_blob(root, 1, live_key, b"live", modified_at=now - 2_000)

    old_temp = root / "1" / "7" / "41" / ".85.blob-generatedold"
    old_temp.write_bytes(b"old temp")
    os.utime(old_temp, (now - 200, now - 200))
    fresh_temp = root / "1" / "7" / "41" / ".86.blob-generatedfresh"
    fresh_temp.write_bytes(b"fresh temp")
    os.utime(fresh_temp, (now - 10, now - 10))

    reservation = reserve_cache_capacity(
        root,
        1,
        reservation_bytes=0,
        live_keys={live_key},
        protected_key=None,
        policy=_policy(idle_retention_seconds=10_000),
        now=now,
    )
    reservation.release()
    assert not stale_orphan.exists()
    assert fresh_orphan.exists()
    assert not old_temp.exists()
    assert fresh_temp.exists()
    assert reservation.report.orphan_removals == 1
    assert reservation.report.temp_removals == 1

    unavailable_snapshot = reserve_cache_capacity(
        root,
        2,
        reservation_bytes=0,
        live_keys=None,
        protected_key=None,
        policy=_policy(idle_retention_seconds=10_000),
        now=now,
    )
    unavailable_snapshot.release()
    assert outage_orphan.read_bytes() == b"outage"
    assert unavailable_snapshot.report.orphan_removals == 0


def test_quota_eviction_is_deterministic_and_user_isolated(tmp_path):
    now = time.time()
    root = tmp_path / "cache"
    first = _write_blob(root, 1, (7, 41, 81), b"1111", modified_at=now - 100)
    second = _write_blob(root, 1, (7, 41, 82), b"2222", modified_at=now - 100)
    third = _write_blob(root, 1, (7, 41, 83), b"3333", modified_at=now - 50)
    other_user = _write_blob(root, 2, (7, 41, 81), b"safe", modified_at=now - 100)

    reservation = reserve_cache_capacity(
        root,
        1,
        reservation_bytes=4,
        live_keys={(7, 41, 81), (7, 41, 82), (7, 41, 83)},
        protected_key=(7, 41, 84),
        policy=_policy(hard_limit_bytes=12, target_bytes=8),
        now=now,
    )
    try:
        assert reservation.can_store
        assert reservation.report.quota_removals == 2
        assert reservation.report.retained_bytes + 4 <= 12
    finally:
        reservation.release()

    assert not first.exists()
    assert not second.exists()
    assert third.read_bytes() == b"3333"
    assert other_user.read_bytes() == b"safe"


def test_busy_candidate_fails_closed_instead_of_overshooting_quota(tmp_path):
    now = time.time()
    root = tmp_path / "cache"
    key = (7, 41, 81)
    cached = _write_blob(root, 1, key, b"12345678", modified_at=now - 100)
    entry_lease = acquire_entry_lease(root, 1, *key)
    assert entry_lease is not None
    try:
        reservation = reserve_cache_capacity(
            root,
            1,
            reservation_bytes=4,
            live_keys={key},
            protected_key=(7, 41, 82),
            policy=_policy(hard_limit_bytes=10, target_bytes=4),
            now=now,
            timeout_seconds=0.1,
        )
        assert not reservation.can_store
        assert reservation.report.busy_files == 1
        assert cached.read_bytes() == b"12345678"
    finally:
        entry_lease.release()


def test_entry_lease_coordinates_with_a_separate_process(tmp_path):
    root = tmp_path / "cache"
    entry_lease = acquire_entry_lease(root, 1, 7, 41, 83)
    assert entry_lease is not None
    child_code = """
import sys
from pathlib import Path
from backend.services.attachment_cache import acquire_entry_lease

lease = acquire_entry_lease(Path(sys.argv[1]), 1, 7, 41, 83, blocking=False)
if lease is not None:
    lease.release()
    raise SystemExit(1)
raise SystemExit(0)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", child_code, str(root)],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        entry_lease.release()

    assert result.returncode == 0, result.stderr


def test_incomplete_namespace_scan_disables_caching(tmp_path, monkeypatch):
    now = time.time()
    root = tmp_path / "cache"
    cached = _write_blob(root, 1, (7, 41, 81), b"12345678", modified_at=now - 10)
    original_list_directory = cache_module._list_directory
    directory_calls = 0

    def fail_one_directory(descriptor, report):
        nonlocal directory_calls
        directory_calls += 1
        if directory_calls == 3:
            report.errors += 1
            return None
        return original_list_directory(descriptor, report)

    monkeypatch.setattr(cache_module, "_list_directory", fail_one_directory)
    reservation = reserve_cache_capacity(
        root,
        1,
        reservation_bytes=4,
        live_keys={(7, 41, 81)},
        protected_key=(7, 41, 82),
        policy=_policy(hard_limit_bytes=10, target_bytes=4),
        now=now,
    )

    assert not reservation.can_store
    assert reservation.report.errors == 1
    assert cached.read_bytes() == b"12345678"


def test_parent_swap_cannot_redirect_cleanup_outside_the_cache(tmp_path, monkeypatch):
    now = time.time()
    root = tmp_path / "cache"
    original_blob = _write_blob(root, 1, (7, 41, 83), b"orphan", modified_at=now - 2_000)
    outside_account = tmp_path / "outside-account"
    outside_blob = outside_account / "41" / "83.blob"
    outside_blob.parent.mkdir(parents=True)
    outside_blob.write_bytes(b"outside sentinel")
    original_remove_candidate = cache_module._remove_candidate
    swapped = False

    def swap_before_removal(storage_root, user_id, candidate, report, reason):
        nonlocal swapped
        if not swapped:
            swapped = True
            account_path = root / "1" / "7"
            account_path.rename(root / "1" / "7-original")
            account_path.symlink_to(outside_account, target_is_directory=True)
        return original_remove_candidate(storage_root, user_id, candidate, report, reason)

    monkeypatch.setattr(cache_module, "_remove_candidate", swap_before_removal)
    reservation = reserve_cache_capacity(
        root,
        1,
        reservation_bytes=0,
        live_keys=set(),
        protected_key=None,
        policy=_policy(),
        now=now,
    )

    assert not reservation.can_store
    assert reservation.report.errors >= 1
    assert outside_blob.read_bytes() == b"outside sentinel"
    assert (root / "1" / "7-original" / "41" / original_blob.name).exists()
