from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Response
from starlette.requests import Request

from backend.routers import terminal as terminal_router
from backend.services.terminal import legacy_ota
from backend.services.terminal.legacy_ota import (
    LegacyOtaUnavailable,
    artifact_bytes,
    load_current_release,
    load_release,
    offer_record,
    record_event,
)
from backend.services.terminal.ota_protocol import AttemptState, OtaEvent, encode_event

DEVICE_ID = "11111111-2222-4333-8444-555555555555"
TEST_KEY = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)


@pytest.fixture(autouse=True)
def _legacy_test_trust(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(legacy_ota, "LEGACY_OTA_PUBLIC_KEY", TEST_KEY.public_key())


def _stage_release(root: Path, model: str = "E1001", version: str = "0.3.0"):
    application = b"signed-application-image"
    manifest = (
        json.dumps(
            {
                "schema_version": 1,
                "model": model,
                "layout": "ab-v1",
                "version": version,
                "firmware_size": len(application),
                "firmware_sha256": hashlib.sha256(application).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")
    release_id = hashlib.sha256(manifest).hexdigest()
    release_root = root / "legacy" / model / release_id
    release_root.mkdir(parents=True)
    (release_root / "manifest.json").write_bytes(manifest)
    (release_root / "manifest.sig").write_bytes(TEST_KEY.sign(manifest))
    (release_root / "application.bin").write_bytes(application)
    pointer_root = release_root.parent / "devices" / DEVICE_ID
    pointer_root.mkdir(parents=True)
    (pointer_root / "current.json").write_text(
        json.dumps({"schema_version": 1, "release_id": release_id}) + "\n"
    )
    return release_id, manifest, application


def test_loads_current_release_and_builds_stable_legacy_offer(tmp_path: Path):
    release_id, manifest, application = _stage_release(tmp_path)
    release = load_current_release(str(tmp_path), "E1001", DEVICE_ID)
    assert release is not None
    assert release.release_id == release_id
    assert artifact_bytes(release, "manifest.json") == (
        manifest,
        "application/json",
    )
    assert artifact_bytes(release, "application.bin") == (
        application,
        "application/octet-stream",
    )
    first = offer_record(
        release,
        schedule_code="Legacy_123",
        device_public_id=DEVICE_ID,
        running_version="0.2.0",
    )
    second = offer_record(
        release,
        schedule_code="Legacy_123",
        device_public_id=DEVICE_ID,
        running_version="0.2.0",
    )
    assert first == second
    assert first is not None
    assert first["manifest_url"] == (
        f"/terminal/Legacy_123/firmware/{release_id}/manifest.json"
    )
    assert first["required"] is False
    assert (
        offer_record(
            release,
            schedule_code="Legacy_123",
            device_public_id=DEVICE_ID,
            running_version="0.3.0",
        )
        is None
    )


def test_missing_channel_is_an_absent_optional_feature(tmp_path: Path):
    assert load_current_release(str(tmp_path), "E1001", DEVICE_ID) is None
    assert load_current_release(str(tmp_path), "E1004", DEVICE_ID) is None


def test_rejects_payload_that_changes_after_manifest(tmp_path: Path):
    release_id, _manifest, _application = _stage_release(tmp_path)
    application = tmp_path / "legacy" / "E1001" / release_id / "application.bin"
    application.write_bytes(b"tampered")
    with pytest.raises(LegacyOtaUnavailable, match="does not match"):
        load_release(str(tmp_path), "E1001", release_id)


def test_rejects_pointer_outside_content_address(tmp_path: Path):
    model_root = tmp_path / "legacy" / "E1002"
    model_root.mkdir(parents=True)
    pointer_root = model_root / "devices" / DEVICE_ID
    pointer_root.mkdir(parents=True)
    (pointer_root / "current.json").write_text(
        '{"schema_version":1,"release_id":"../escape"}\n'
    )
    with pytest.raises(LegacyOtaUnavailable, match="pointer fields"):
        load_current_release(str(tmp_path), "E1002", DEVICE_ID)


def test_retains_bound_idempotent_lifecycle_event(tmp_path: Path):
    _stage_release(tmp_path)
    release = load_current_release(str(tmp_path), "E1001", DEVICE_ID)
    assert release is not None
    offer = offer_record(
        release,
        schedule_code="Legacy_123",
        device_public_id=DEVICE_ID,
        running_version="0.2.0",
    )
    assert offer is not None
    raw = encode_event(
        OtaEvent(
            schema_version=1,
            event_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            attempt_id=offer["attempt_id"],
            offer_id=offer["offer_id"],
            sequence=1,
            release_id=release.release_id,
            state=AttemptState.DOWNLOADING,
            running_version="0.2.0",
            running_build_id="a" * 40,
            running_partition="ota_0",
            boot_count=3,
            reset_reason="timer",
            error_code=None,
        )
    )
    assert record_event(
        str(tmp_path),
        release,
        schedule_code="Legacy_123",
        device_public_id=DEVICE_ID,
        raw=raw,
    ) == ("downloading", False)
    assert record_event(
        str(tmp_path),
        release,
        schedule_code="Legacy_123",
        device_public_id=DEVICE_ID,
        raw=raw,
    ) == ("downloading", True)


@pytest.mark.asyncio
async def test_legacy_schedule_advertises_current_signed_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    release_id, _manifest, _application = _stage_release(tmp_path)
    monkeypatch.setattr(
        terminal_router.app_settings,
        "terminal_firmware_storage_path",
        str(tmp_path),
    )

    async def settings(_db, _code):
        return SimpleNamespace(user_id=1, timezone="UTC")

    device = SimpleNamespace(
        id=7,
        public_id=DEVICE_ID,
        mac="aa:bb:cc:dd:ee:ff",
        name="Desk",
        refresh_interval_sec=60,
        content_type="clock",
        hardware_model="E1001",
        last_ota_battery_mv=4150,
        last_ota_battery_pct=92,
        last_ota_telemetry_at=datetime.now(timezone.utc),
    )

    async def upsert(_db, **_kwargs):
        return device

    async def render(_variant, **_kwargs):
        return b"bmp", '"img-test"'

    monkeypatch.setattr(terminal_router, "_resolve_settings", settings)
    monkeypatch.setattr(terminal_router, "_upsert_device", upsert)
    monkeypatch.setattr(terminal_router, "_render_for_device", render)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/terminal/Legacy_123/schedule.json",
            "headers": [
                (b"x-fw-version", b"0.2.0"),
                (b"x-device-mac", b"aa:bb:cc:dd:ee:ff"),
            ],
        }
    )
    response = Response()
    payload = await terminal_router.schedule(
        "Legacy_123",
        request,
        response,
        variant="bw",
        db=object(),
    )
    assert payload["firmware"]["release_id"] == release_id
    assert payload["firmware"]["version"] == "0.3.0"
    assert "-ota-" in response.headers["etag"]
