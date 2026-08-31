"""Opt-in disposable-PostgreSQL OTA ledger and concurrency checks.

Set TERMINAL_OTA_POSTGRES_TEST_URL only to a freshly migrated disposable
database. These tests truncate it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.routers.terminal_admin as terminal_admin
import backend.routers.terminal_ota as ota_router
from backend.models.terminal import (
    TerminalDevice,
    TerminalDeviceCredential,
    TerminalOtaAttempt,
    TerminalOtaEvent,
)
from backend.models.user import User
from backend.routers.terminal_admin import TerminalDeviceUpdate
from backend.routers.terminal_ota import CreateOtaAttemptRequest
from backend.services.terminal.ota_control import LoadedOtaRelease
from backend.services.terminal.ota_policy import ParentBundleLink, VerifiedOtaRelease

DATABASE_URL = os.getenv("TERMINAL_OTA_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires TERMINAL_OTA_POSTGRES_TEST_URL for disposable PostgreSQL",
    ),
]

PUBLIC_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TOKEN = "A" * 43
RELEASE_ID = "b" * 64
SOURCE_BUILD = "c" * 40
TARGET_BUILD = "d" * 40
NOW = datetime.now(timezone.utc)


def _sessions():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset(engine):
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


def _request(
    path: str,
    *,
    method: str,
    body: bytes = b"",
    owner: bool = False,
) -> Request:
    headers = [(b"x-device-mac", b"aa:bb:cc:dd:ee:ff")]
    if owner:
        headers.extend(
            [
                (b"cookie", b"access_token=session"),
                (b"origin", b"http://localhost:8080"),
                (b"sec-fetch-site", b"same-origin"),
            ]
        )
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "client": ("192.0.2.40", 12345),
            "scheme": "https",
            "server": ("email.mcchord.net", 443),
        },
        receive,
    )


def _loaded_release() -> LoadedOtaRelease:
    parent = ParentBundleLink(
        release_id="a" * 64,
        signing_key_id="ota-test-key",
        catalog_generation=7,
        model="E1002",
        firmware_version="0.3.0",
        source_build_id=TARGET_BUILD,
        partition_layout="ab-v1",
        application_size=1024,
        application_sha256="9" * 64,
        hardware_revisions=("rev_a",),
        release_ota_eligible=True,
        model_ota_eligible=True,
    )
    return LoadedOtaRelease(
        release=VerifiedOtaRelease(
            release_id=RELEASE_ID,
            signing_key_id=parent.signing_key_id,
            model="E1002",
            layout="ab-v1",
            version="0.3.0",
            firmware_size=1024,
            firmware_sha256="9" * 64,
            manifest_bytes=b"{}",
            signature_bytes=b"s" * 64,
            parent=parent,
        ),
        application_bytes=b"a" * 1024,
        descriptor_signature_sha256=hashlib.sha256(b"s" * 64).hexdigest(),
        catalog_generation=7,
    )


async def _seed(sessions):
    async with sessions() as db:
        user = User(username=f"ota-owner-{uuid4()}", is_active=True)
        db.add(user)
        await db.flush()
        device = TerminalDevice(
            public_id=PUBLIC_ID,
            user_id=user.id,
            mac="aa:bb:cc:dd:ee:ff",
            name="OTA test",
            hardware_model="E1002",
            hardware_revision="rev_a",
            hardware_revision_confirmed_at=NOW,
            enrollment_state="enrolled",
            enrollment_generation=1,
            enrollment_config_sha256="e" * 64,
            enrollment_activated_at=NOW,
            last_ota_fw_version="0.2.0-candidate.6",
            last_ota_build_id=SOURCE_BUILD,
            last_ota_partition="ota_0",
            last_ota_boot_count=4_294_967_295 - 1,
            last_ota_battery_mv=4050,
            last_ota_battery_pct=82,
            last_ota_external_power=None,
            last_ota_telemetry_at=datetime.now(timezone.utc),
        )
        db.add(device)
        await db.flush()
        credential = TerminalDeviceCredential(
            device_id=device.id,
            token_sha256=hashlib.sha256(TOKEN.encode("ascii")).hexdigest(),
            config_sha256="e" * 64,
            generation=1,
            state="active",
            activated_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(credential)
        await db.commit()
        return SimpleNamespace(id=user.id), device.id


@pytest.fixture(autouse=True)
def _policy(monkeypatch):
    loaded = _loaded_release()

    async def load(_release_id):
        return loaded

    monkeypatch.setattr(ota_router, "_loaded_release", load)
    monkeypatch.setattr(ota_router, "_require_release_policy", lambda _loaded: None)
    monkeypatch.setattr(ota_router.settings, "terminal_ota_rollout_percentage", 100)
    monkeypatch.setattr(ota_router.settings, "terminal_ota_attempt_ttl_seconds", 3600)
    monkeypatch.setattr(
        ota_router.settings, "terminal_ota_telemetry_max_age_seconds", 300
    )
    monkeypatch.setattr(ota_router.settings, "terminal_ota_min_battery_pct", 80)
    monkeypatch.setattr(ota_router.settings, "terminal_ota_min_battery_mv", 4000)
    return loaded


async def test_concurrent_create_and_lost_response_replay_are_one_attempt(monkeypatch):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        user, device_id = await _seed(sessions)
        client_request_id = uuid4()
        payload = CreateOtaAttemptRequest(
            client_request_id=client_request_id,
            release_id=RELEASE_ID,
        )

        async def create_one():
            async with sessions() as db:
                return await ota_router.create_ota_attempt(
                    _request(
                        f"/api/terminal/devices/{device_id}/ota/attempts",
                        method="POST",
                        owner=True,
                    ),
                    device_id,
                    payload,
                    Response(),
                    db,
                    user,
                )

        first, second = await asyncio.wait_for(
            asyncio.gather(create_one(), create_one()), timeout=5
        )
        assert first["attempt_id"] == second["attempt_id"]
        async with sessions() as db:
            assert await db.scalar(select(func.count(TerminalOtaAttempt.id))) == 1

        async def forbidden_load(_release_id):
            raise AssertionError(
                "idempotent replay must not reload paused release evidence"
            )

        monkeypatch.setattr(ota_router, "_loaded_release", forbidden_load)
        replay = await create_one()
        assert replay["attempt_id"] == first["attempt_id"]
    finally:
        await engine.dispose()


def _event(attempt: dict, *, event_id: UUID, sequence: int, state: str) -> bytes:
    target = state in {"booted_pending_validation", "succeeded"}
    error = (
        "test_failure"
        if state in {"failed", "rolled_back", "recovery_required"}
        else None
    )
    return json.dumps(
        {
            "schema_version": 1,
            "event_id": str(event_id),
            "attempt_id": attempt["attempt_id"],
            "offer_id": attempt["offer_id"],
            "sequence": sequence,
            "release_id": RELEASE_ID,
            "state": state,
            "running_version": "0.3.0" if target else "0.2.0-candidate.6",
            "running_build_id": TARGET_BUILD if target else SOURCE_BUILD,
            "running_partition": "ota_1" if target else "ota_0",
            "boot_count": 4_294_967_295 if target else 4_294_967_294,
            "reset_reason": None,
            "error_code": error,
        },
        separators=(",", ":"),
    ).encode("ascii")


async def test_event_replay_gap_and_runtime_identity_are_durable():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        user, device_id = await _seed(sessions)
        async with sessions() as db:
            attempt = await ota_router.create_ota_attempt(
                _request(
                    f"/api/terminal/devices/{device_id}/ota/attempts",
                    method="POST",
                    owner=True,
                ),
                device_id,
                CreateOtaAttemptRequest(
                    client_request_id=uuid4(), release_id=RELEASE_ID
                ),
                Response(),
                db,
                user,
            )

        event_id = uuid4()
        raw = _event(attempt, event_id=event_id, sequence=2, state="downloading")

        async def post(body: bytes):
            async with sessions() as db:
                return await ota_router.terminal_ota_event(
                    _request(
                        f"/terminal/device/{PUBLIC_ID}/{TOKEN}/firmware/events",
                        method="POST",
                        body=body,
                    ),
                    PUBLIC_ID,
                    TOKEN,
                    db,
                )

        accepted = await post(raw)
        replay = await post(raw)
        assert accepted.status_code == 201
        assert replay.status_code == 200
        assert b'"idempotent":true' in replay.body

        conflict = json.loads(raw)
        conflict["boot_count"] -= 1
        with pytest.raises(HTTPException) as exc_info:
            await post(json.dumps(conflict, separators=(",", ":")).encode())
        assert exc_info.value.status_code == 409

        async with sessions() as db:
            persisted = await db.scalar(
                select(TerminalOtaAttempt).where(
                    TerminalOtaAttempt.attempt_id == UUID(attempt["attempt_id"])
                )
            )
            events = list((await db.scalars(select(TerminalOtaEvent))).all())
            assert persisted.state == "downloading"
            assert persisted.last_sequence == 2
            assert persisted.has_event_gap is True
            assert len(events) == 1
            assert events[0].transition_kind == "advance_with_gap"
    finally:
        await engine.dispose()


async def test_active_credential_only_and_expiry_is_committed():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        user, device_id = await _seed(sessions)
        async with sessions() as db:
            response = await ota_router.create_ota_attempt(
                _request(
                    f"/api/terminal/devices/{device_id}/ota/attempts",
                    method="POST",
                    owner=True,
                ),
                device_id,
                CreateOtaAttemptRequest(
                    client_request_id=uuid4(), release_id=RELEASE_ID
                ),
                Response(),
                db,
                user,
            )
            attempt = await db.scalar(
                select(TerminalOtaAttempt).where(
                    TerminalOtaAttempt.attempt_id == UUID(response["attempt_id"])
                )
            )
            attempt.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()

        async with sessions() as db:
            device = await db.get(TerminalDevice, device_id)
            credential = await db.scalar(
                select(TerminalDeviceCredential).where(
                    TerminalDeviceCredential.device_id == device_id,
                    TerminalDeviceCredential.state == "active",
                )
            )
            with pytest.raises(HTTPException) as exc_info:
                await ota_router._attempt_for_artifact(
                    db,
                    device=device,
                    credential=credential,
                    release_id=RELEASE_ID,
                )
            assert exc_info.value.status_code == 404
        async with sessions() as db:
            expired = await db.scalar(
                select(TerminalOtaAttempt).where(
                    TerminalOtaAttempt.attempt_id == UUID(response["attempt_id"])
                )
            )
            assert expired.state == "expired"
            assert expired.terminal_at is not None

        # A distinct expired offer cannot be started by a forged first event;
        # rejecting it also durably releases the active-attempt slot.
        async with sessions() as db:
            second = await ota_router.create_ota_attempt(
                _request(
                    f"/api/terminal/devices/{device_id}/ota/attempts",
                    method="POST",
                    owner=True,
                ),
                device_id,
                CreateOtaAttemptRequest(
                    client_request_id=uuid4(), release_id=RELEASE_ID
                ),
                Response(),
                db,
                user,
            )
            second_row = await db.scalar(
                select(TerminalOtaAttempt).where(
                    TerminalOtaAttempt.attempt_id == UUID(second["attempt_id"])
                )
            )
            second_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()

        raw = _event(
            second,
            event_id=uuid4(),
            sequence=1,
            state="downloading",
        )
        async with sessions() as db:
            with pytest.raises(HTTPException) as expired_event:
                await ota_router.terminal_ota_event(
                    _request(
                        f"/terminal/device/{PUBLIC_ID}/{TOKEN}/firmware/events",
                        method="POST",
                        body=raw,
                    ),
                    PUBLIC_ID,
                    TOKEN,
                    db,
                )
            assert expired_event.value.status_code == 409
        async with sessions() as db:
            expired = await db.scalar(
                select(TerminalOtaAttempt).where(
                    TerminalOtaAttempt.attempt_id == UUID(second["attempt_id"])
                )
            )
            assert expired.state == "expired"
            assert await db.scalar(select(func.count(TerminalOtaEvent.id))) == 0

            rollback_token = "B" * 43
            db.add(
                TerminalDeviceCredential(
                    device_id=device_id,
                    token_sha256=hashlib.sha256(rollback_token.encode()).hexdigest(),
                    config_sha256="f" * 64,
                    generation=2,
                    state="rollback",
                    activated_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await db.commit()
        async with sessions() as db:
            with pytest.raises(HTTPException) as exc_info:
                await ota_router._lock_active_device(
                    db,
                    public_id=PUBLIC_ID,
                    credential_token="B" * 43,
                    request=_request(
                        f"/terminal/device/{PUBLIC_ID}/{'B' * 43}/firmware/events",
                        method="POST",
                    ),
                )
            assert exc_info.value.status_code == 404
    finally:
        await engine.dispose()


async def test_owner_revision_confirmation_is_explicit_and_frozen_during_attempt():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        user, device_id = await _seed(sessions)
        async with sessions() as db:
            updated = await terminal_admin.update_device(
                _request(
                    f"/api/terminal/devices/{device_id}", method="PATCH", owner=True
                ),
                device_id,
                TerminalDeviceUpdate(hardware_revision="rev_b"),
                db,
                user,
            )
            assert updated.hardware_revision == "rev_b"
            assert updated.hardware_revision_confirmed_at is not None

            with pytest.raises(HTTPException) as csrf:
                await terminal_admin.update_device(
                    _request(f"/api/terminal/devices/{device_id}", method="PATCH"),
                    device_id,
                    TerminalDeviceUpdate(hardware_revision="rev_a"),
                    db,
                    user,
                )
            assert csrf.value.status_code == 403

            # Restore the qualified revision, create an offer, then prove the
            # snapshotted physical claim cannot change while it is active.
            await terminal_admin.update_device(
                _request(
                    f"/api/terminal/devices/{device_id}", method="PATCH", owner=True
                ),
                device_id,
                TerminalDeviceUpdate(hardware_revision="rev_a"),
                db,
                user,
            )
            await ota_router.create_ota_attempt(
                _request(
                    f"/api/terminal/devices/{device_id}/ota/attempts",
                    method="POST",
                    owner=True,
                ),
                device_id,
                CreateOtaAttemptRequest(
                    client_request_id=uuid4(), release_id=RELEASE_ID
                ),
                Response(),
                db,
                user,
            )
            with pytest.raises(HTTPException) as active:
                await terminal_admin.update_device(
                    _request(
                        f"/api/terminal/devices/{device_id}", method="PATCH", owner=True
                    ),
                    device_id,
                    TerminalDeviceUpdate(hardware_revision="rev_b"),
                    db,
                    user,
                )
            assert active.value.status_code == 409
    finally:
        await engine.dispose()
