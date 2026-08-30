import os
import time

import pytest

import backend.services.attachment_cache_maintenance as maintenance_module
from backend.services.attachment_cache import (
    AttachmentCachePolicy,
    acquire_maintenance_lease,
    canonical_cache_path,
)
from backend.services.attachment_cache_maintenance import (
    attachment_cache_maintenance_loop,
    run_attachment_cache_maintenance,
)


def _policy() -> AttachmentCachePolicy:
    return AttachmentCachePolicy(
        hard_limit_bytes=1024,
        target_bytes=768,
        idle_retention_seconds=10_000,
        orphan_grace_seconds=100,
        temp_grace_seconds=100,
    )


@pytest.mark.asyncio
async def test_periodic_sweep_removes_deleted_user_orphans_without_a_download(tmp_path):
    now = time.time()
    root = tmp_path / "cache"
    orphan = canonical_cache_path(root, 5, 7, 41, 83)
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"generated deleted-account orphan")
    os.utime(orphan, (now - 1_000, now - 1_000))
    stale_temp = orphan.parent / ".84.blob-generatedcrash"
    stale_temp.write_bytes(b"generated crashed temporary file")
    os.utime(stale_temp, (now - 1_000, now - 1_000))

    async def no_live_keys(user_id):
        assert user_id == 5
        return set()

    report = await run_attachment_cache_maintenance(
        storage_root=root,
        live_key_loader=no_live_keys,
        policy=_policy(),
        now=now,
    )

    assert report.discovered_users == 1
    assert report.processed_users == 1
    assert report.removed_files == 2
    assert not orphan.exists()
    assert not stale_temp.exists()


@pytest.mark.asyncio
async def test_periodic_sweep_does_not_classify_orphans_during_db_failure(tmp_path):
    now = time.time()
    root = tmp_path / "cache"
    possible_live_blob = canonical_cache_path(root, 5, 7, 41, 83)
    possible_live_blob.parent.mkdir(parents=True)
    possible_live_blob.write_bytes(b"generated ownership unknown")
    os.utime(possible_live_blob, (now - 1_000, now - 1_000))

    async def unavailable_snapshot(_user_id):
        return None

    report = await run_attachment_cache_maintenance(
        storage_root=root,
        live_key_loader=unavailable_snapshot,
        policy=_policy(),
        now=now,
    )

    assert report.database_failures == 1
    assert report.removed_files == 0
    assert possible_live_blob.read_bytes() == b"generated ownership unknown"


@pytest.mark.asyncio
async def test_duplicate_periodic_sweep_is_skipped_by_global_lease(tmp_path):
    root = tmp_path / "cache"
    held_lease = acquire_maintenance_lease(root)
    assert held_lease is not None
    try:
        report = await run_attachment_cache_maintenance(
            storage_root=root,
            live_key_loader=lambda _user_id: None,
        )
    finally:
        held_lease.release()

    assert report.skipped_busy
    assert report.processed_users == 0


@pytest.mark.asyncio
async def test_maintenance_loop_runs_after_its_bounded_initial_delay(monkeypatch):
    stop_event = maintenance_module.asyncio.Event()
    calls = 0

    async def generated_run():
        nonlocal calls
        calls += 1
        stop_event.set()

    monkeypatch.setattr(
        maintenance_module,
        "run_attachment_cache_maintenance",
        generated_run,
    )
    await attachment_cache_maintenance_loop(
        stop_event,
        initial_delay_seconds=0,
        interval_seconds=0.01,
    )

    assert calls == 1
