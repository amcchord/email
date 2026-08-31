from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Request

import backend.routers.terminal_enrollment as enrollment_router
import backend.routers.terminal_ota as ota_router
from backend.config import Settings
from backend.models.terminal import TerminalDevice, TerminalOtaAttempt, TerminalOtaEvent
from backend.routers.auth import get_current_user
from backend.services.terminal.ota_control import (
    OtaControlError,
    apply_ota_telemetry,
    build_offer,
    offer_etag_component,
    offer_record,
    parse_ota_telemetry,
    require_fresh_power_reserve,
    require_rollout,
    rollout_bucket,
    validate_event_runtime,
)
from backend.services.terminal.ota_protocol import AttemptState, OtaEvent

NOW = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
PUBLIC_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ATTEMPT_ID = UUID("22222222-2222-4222-8222-222222222222")
OFFER_ID = UUID("11111111-1111-4111-8111-111111111111")
RELEASE_ID = "b" * 64
SOURCE_BUILD = "c" * 40
TARGET_BUILD = "d" * 40
TOKEN = "A" * 43


def _headers(**updates) -> dict[str, str]:
    values = {
        "x-fw-version": "0.2.0-candidate.6",
        "x-firmware-build-id": SOURCE_BUILD,
        "x-running-partition": "ota_0",
        "x-boot-count": "4294967295",
        "x-battery-valid": "1",
        "x-battery-mv": "4050",
        "x-battery-pct": "82",
    }
    values.update(updates)
    return values


def _device() -> TerminalDevice:
    device = TerminalDevice(
        id=7,
        public_id=PUBLIC_ID,
        user_id=3,
        mac="aa:bb:cc:dd:ee:ff",
        name="Test terminal",
        hardware_model="E1002",
        hardware_revision="rev_a",
        hardware_revision_confirmed_at=NOW,
        enrollment_state="enrolled",
        enrollment_generation=1,
        enrollment_config_sha256="e" * 64,
    )
    apply_ota_telemetry(device, parse_ota_telemetry(_headers(), now=NOW))
    return device


def _attempt() -> TerminalOtaAttempt:
    return TerminalOtaAttempt(
        id=9,
        attempt_id=ATTEMPT_ID,
        offer_id=OFFER_ID,
        user_id=3,
        device_id=7,
        credential_id=5,
        client_request_id=uuid4(),
        request_fingerprint="f" * 64,
        state="offered",
        last_sequence=0,
        has_event_gap=False,
        descriptor_release_id=RELEASE_ID,
        parent_release_id="a" * 64,
        signing_key_id="release-key",
        catalog_generation=4,
        device_model="E1002",
        hardware_revision="rev_a",
        partition_layout="ab-v1",
        target_version="0.3.0",
        target_build_id=TARGET_BUILD,
        firmware_size=1_200_000,
        firmware_sha256="9" * 64,
        descriptor_signature_sha256="8" * 64,
        source_version="0.2.0-candidate.6",
        source_build_id=SOURCE_BUILD,
        source_partition="ota_0",
        source_boot_count=41,
        offered_battery_mv=4050,
        offered_battery_pct=82,
        offered_external_power=None,
        rollout_percentage=25,
        cohort_bucket=100,
        expires_at=NOW + timedelta(hours=1),
        created_at=NOW,
        updated_at=NOW,
    )


def _event(state: AttemptState, **updates) -> OtaEvent:
    target = state in {
        AttemptState.BOOTED_PENDING_VALIDATION,
        AttemptState.SUCCEEDED,
    }
    values = {
        "schema_version": 1,
        "event_id": "33333333-3333-4333-8333-333333333333",
        "attempt_id": str(ATTEMPT_ID),
        "offer_id": str(OFFER_ID),
        "sequence": 1,
        "release_id": RELEASE_ID,
        "state": state,
        "running_version": "0.3.0" if target else "0.2.0-candidate.6",
        "running_build_id": TARGET_BUILD if target else SOURCE_BUILD,
        "running_partition": "ota_1" if target else "ota_0",
        "boot_count": 42 if target else 41,
        "reset_reason": None,
        "error_code": (
            "test_failure"
            if state
            in {
                AttemptState.FAILED,
                AttemptState.ROLLED_BACK,
                AttemptState.RECOVERY_REQUIRED,
            }
            else None
        ),
    }
    if state is AttemptState.ROLLED_BACK:
        values["boot_count"] = 42
    values.update(updates)
    return OtaEvent(**values)


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [
                (b"cookie", b"access_token=session"),
                (b"origin", b"http://localhost:8080"),
                (b"sec-fetch-site", b"same-origin"),
            ],
            "client": ("192.0.2.30", 12345),
            "scheme": "https",
            "server": ("email.mcchord.net", 443),
        }
    )


def _schedule_request(*, if_none_match: str | None = None) -> Request:
    headers = [(b"x-device-mac", b"aa:bb:cc:dd:ee:ff")]
    if if_none_match is not None:
        headers.append((b"if-none-match", if_none_match.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/terminal/device/{PUBLIC_ID}/{TOKEN}/schedule.json",
            "headers": headers,
            "client": ("192.0.2.30", 12345),
            "scheme": "https",
            "server": ("email.mcchord.net", 443),
        }
    )


def test_ota_settings_are_independently_default_closed():
    configured = Settings(_env_file=None)

    assert configured.terminal_ota_enabled is False
    assert configured.terminal_ota_qualified_releases == "{}"
    assert configured.terminal_ota_rollout_percentage == 0
    assert configured.terminal_ota_attempt_ttl_seconds == 3600
    assert configured.terminal_ota_telemetry_max_age_seconds == 300
    assert configured.terminal_ota_min_battery_pct == 80
    assert configured.terminal_ota_min_battery_mv == 4000


def test_telemetry_is_one_exact_uint32_snapshot_and_power_can_be_unknown():
    telemetry = parse_ota_telemetry(_headers(), now=NOW)

    assert telemetry.boot_count == 4_294_967_295
    assert telemetry.external_power is None

    direct = parse_ota_telemetry(_headers(**{"x-external-power": "1"}), now=NOW)
    assert direct.external_power is True

    for updates in (
        {"x-external-power": "yes"},
        {"x-battery-valid": "0"},
        {"x-firmware-build-id": "C" * 40},
        {"x-running-partition": "factory"},
        {"x-boot-count": "4294967296"},
    ):
        with pytest.raises(OtaControlError):
            parse_ota_telemetry(_headers(**updates), now=NOW)


def test_power_gate_uses_direct_truth_or_conservative_reserve_never_forecast():
    device = _device()
    configured = SimpleNamespace(
        terminal_ota_telemetry_max_age_seconds=300,
        terminal_ota_min_battery_pct=80,
        terminal_ota_min_battery_mv=4000,
    )
    assert require_fresh_power_reserve(device, configured, now=NOW).battery_pct == 82

    device.last_ota_battery_pct = 20
    device.last_ota_battery_mv = 3600
    with pytest.raises(OtaControlError, match="reserve"):
        require_fresh_power_reserve(device, configured, now=NOW)

    device.last_ota_external_power = True
    assert (
        require_fresh_power_reserve(device, configured, now=NOW).external_power is True
    )

    device.last_ota_telemetry_at = NOW - timedelta(seconds=301)
    with pytest.raises(OtaControlError, match="Fresh"):
        require_fresh_power_reserve(device, configured, now=NOW)


def test_rollout_bucket_is_stable_and_zero_is_closed():
    assert rollout_bucket(PUBLIC_ID, RELEASE_ID) == rollout_bucket(
        PUBLIC_ID, RELEASE_ID
    )
    with pytest.raises(OtaControlError, match="closed"):
        require_rollout(
            PUBLIC_ID,
            RELEASE_ID,
            SimpleNamespace(terminal_ota_rollout_percentage=0),
        )

    percentage, bucket = require_rollout(
        PUBLIC_ID,
        RELEASE_ID,
        SimpleNamespace(terminal_ota_rollout_percentage=100),
    )
    assert percentage == 100
    assert 0 <= bucket < 10_000


def test_offer_reuses_scoped_credential_without_persisting_it():
    attempt = _attempt()
    offer = build_offer(attempt, public_id=PUBLIC_ID, credential_token=TOKEN)
    record = offer_record(offer)

    assert record == {
        "schema_version": 1,
        "offer_id": str(OFFER_ID),
        "attempt_id": str(ATTEMPT_ID),
        "release_id": RELEASE_ID,
        "version": "0.3.0",
        "manifest_url": (
            f"/terminal/device/{PUBLIC_ID}/{TOKEN}/firmware/{RELEASE_ID}/manifest.json"
        ),
        "signature_url": (
            f"/terminal/device/{PUBLIC_ID}/{TOKEN}/firmware/{RELEASE_ID}/manifest.sig"
        ),
        "application_url": (
            f"/terminal/device/{PUBLIC_ID}/{TOKEN}/firmware/{RELEASE_ID}/application.bin"
        ),
        "event_url": f"/terminal/device/{PUBLIC_ID}/{TOKEN}/firmware/events",
        "required": False,
    }
    assert TOKEN not in repr(attempt.__dict__)
    assert offer_etag_component(offer) != offer_etag_component(None)


@pytest.mark.asyncio
async def test_scoped_schedule_offer_changes_etag_without_changing_image(monkeypatch):
    device = SimpleNamespace(name="Test terminal", refresh_interval_sec=300)
    variant = SimpleNamespace(
        query=None,
        next_checkin_sec=300,
        image_format="bmp",
    )

    async def scoped_device(*_args, **_kwargs):
        return device, SimpleNamespace(), variant

    async def render(*_args, **_kwargs):
        return b"same-image", '"img-static"'

    offer = offer_record(
        build_offer(_attempt(), public_id=PUBLIC_ID, credential_token=TOKEN)
    )
    current_offer = None

    async def schedule_offer(*_args, **_kwargs):
        return current_offer

    monkeypatch.setattr(enrollment_router, "_scoped_device", scoped_device)
    monkeypatch.setattr(enrollment_router, "_render_for_device", render)
    monkeypatch.setattr(ota_router, "schedule_offer", schedule_offer)

    absent = await enrollment_router.scoped_terminal_schedule(
        _schedule_request(), PUBLIC_ID, TOKEN, db=SimpleNamespace()
    )
    absent_payload = json.loads(absent.body)
    absent_etag = absent.headers["etag"]
    assert "firmware" not in absent_payload

    current_offer = offer
    offered = await enrollment_router.scoped_terminal_schedule(
        _schedule_request(if_none_match=absent_etag),
        PUBLIC_ID,
        TOKEN,
        db=SimpleNamespace(),
    )
    offered_payload = json.loads(offered.body)
    assert offered.status_code == 200
    assert offered.headers["etag"] != absent_etag
    assert offered_payload["image"] == absent_payload["image"]
    assert offered_payload["firmware"] == offer

    unchanged = await enrollment_router.scoped_terminal_schedule(
        _schedule_request(if_none_match=offered.headers["etag"]),
        PUBLIC_ID,
        TOKEN,
        db=SimpleNamespace(),
    )
    assert unchanged.status_code == 304


def test_runtime_identity_is_state_and_slot_aware():
    attempt = _attempt()
    for state in (AttemptState.DOWNLOADING, AttemptState.STAGED, AttemptState.FAILED):
        validate_event_runtime(attempt, _event(state))
    for state in (
        AttemptState.BOOTED_PENDING_VALIDATION,
        AttemptState.SUCCEEDED,
    ):
        validate_event_runtime(attempt, _event(state))
    validate_event_runtime(attempt, _event(AttemptState.ROLLED_BACK))

    with pytest.raises(OtaControlError):
        validate_event_runtime(
            attempt,
            _event(AttemptState.SUCCEEDED, running_partition="ota_0"),
        )
    with pytest.raises(OtaControlError):
        validate_event_runtime(
            attempt,
            _event(AttemptState.SUCCEEDED, running_build_id=SOURCE_BUILD),
        )
    with pytest.raises(OtaControlError):
        validate_event_runtime(
            attempt,
            _event(AttemptState.ROLLED_BACK, boot_count=41),
        )


def test_models_preserve_uint32_gap_and_active_uniqueness_contracts():
    assert TerminalDevice.__table__.c.last_ota_boot_count.type.python_type is int
    assert TerminalOtaAttempt.__table__.c.last_sequence.type.python_type is int
    assert TerminalOtaEvent.__table__.c.sequence.type.python_type is int
    assert "has_event_gap" in TerminalOtaAttempt.__table__.c
    assert "transition_kind" in TerminalOtaEvent.__table__.c
    active_index = next(
        index
        for index in TerminalOtaAttempt.__table__.indexes
        if index.name == "uq_terminal_ota_attempts_active_device"
    )
    assert active_index.unique is True
    assert "booted_pending_validation" in str(
        active_index.dialect_options["postgresql"]["where"]
    )


def test_owner_and_device_routes_keep_separate_auth_boundaries():
    owner_routes = [
        route
        for route in ota_router.router.routes
        if route.path.startswith("/api/terminal/")
    ]
    device_routes = [
        route
        for route in ota_router.router.routes
        if route.path.startswith("/terminal/device/")
    ]
    assert owner_routes
    assert device_routes
    assert all(
        any(
            dependency.call is get_current_user
            for dependency in route.dependant.dependencies
        )
        for route in owner_routes
    )
    assert all(
        not any(
            dependency.call is get_current_user
            for dependency in route.dependant.dependencies
        )
        for route in device_routes
    )
    # The owner mutation helper accepts the established cookie/same-origin
    # boundary used by enrollment; route handlers call it before work begins.
    from backend.routers.terminal_enrollment import _require_owner_mutation

    _require_owner_mutation(_request("/api/terminal/devices/7/ota/attempts"))
