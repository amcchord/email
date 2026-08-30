"""Opt-in disposable-PostgreSQL checks for secure terminal enrollment.

Set TERMINAL_ENROLLMENT_POSTGRES_TEST_URL to a freshly migrated disposable
database. Never point this at development or production data.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.routers.terminal_enrollment as enrollment_router
from backend.models.terminal import (
    TerminalDevice,
    TerminalDeviceCredential,
    TerminalEnrollmentAttempt,
    TerminalSettings,
)
from backend.models.user import User
from backend.routers.terminal_enrollment import (
    EnrollmentCompleteRequest,
    EnrollmentIntentRequest,
    EnrollmentTicketRequest,
)
from backend.routers.terminal import _upsert_device
from backend.services.terminal.enrollment_policy import (
    EnrollmentPolicy,
    QualifiedEnrollmentRelease,
)
from backend.services.terminal.enrollment_protocol import ValidatedHandshake
from backend.services.terminal.variants import parse_variant


DATABASE_URL = os.getenv("TERMINAL_ENROLLMENT_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires TERMINAL_ENROLLMENT_POSTGRES_TEST_URL for disposable PostgreSQL",
    ),
]
VECTOR = json.loads(
    (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "lib"
        / "fixtures"
        / "ret1-v1-vector.json"
    ).read_text()
)


def _sessions():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset(engine):
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


def _policy() -> EnrollmentPolicy:
    release = QualifiedEnrollmentRelease(
        release_id="a" * 64,
        firmware_version="0.2.0-candidate.3",
        git_sha="b" * 40,
        trust_key_id="ret1-postgres-test",
        public_key_sha256="c" * 64,
        models=("E1001", "E1002"),
    )
    return EnrollmentPolicy(
        enabled=True,
        state="ready",
        base_url="https://email.mcchord.net",
        signing_key_id=release.trust_key_id,
        signing_key=ec.generate_private_key(ec.SECP256R1()),
        public_key_sha256=release.public_key_sha256,
        ticket_ttl_seconds=300,
        releases=(release,),
        blockers=(),
    )


def _request(path: str, *, mac: str | None = None) -> Request:
    headers = [
        (b"cookie", b"access_token=session"),
        (b"origin", b"https://email.mcchord.net"),
        (b"sec-fetch-site", b"same-origin"),
    ]
    if mac:
        headers.extend(
            [
                (b"x-device-mac", mac.encode("ascii")),
                (b"x-fw-version", b"0.2.0-candidate.3"),
                (b"x-boot-count", b"1"),
                (b"x-battery-pct", b"75"),
            ]
        )
    return Request(
        {
            "type": "http",
            "method": "POST" if path.startswith("/api/") else "GET",
            "path": path,
            "headers": headers,
            "client": ("192.0.2.20", 12345),
            "scheme": "https",
            "server": ("email.mcchord.net", 443),
        }
    )


def _intent() -> EnrollmentIntentRequest:
    return EnrollmentIntentRequest(
        client_intent_id=uuid4(),
        operation="provision",
        status={
            "v": 2,
            "type": "status",
            "state": "provisioning_required",
            "model": "E1002",
            "firmware_version": "0.2.0-candidate.3",
            "factory_mac": "aa:bb:cc:dd:ee:ff",
            "config_source": "fallback",
            "config_generation": 0,
            "enrollment_available": True,
            "enrollment_key_id": "ret1-postgres-test",
            "partition_layout": "ab-v1",
            "running_partition": "ota_0",
            "boot_state": "stable",
            "partition_identity_valid": True,
            "firmware_build_id": "0123456789abcdef0123456789abcdef01234567",
            "identity_strength": "physical_cable_only",
            "attestation": False,
        },
        hello={
            "v": 1,
            "type": "hello",
            "seq": 0,
            "client_nonce": VECTOR["client_nonce_b64url"],
            "client_public_key": VECTOR["client_public_b64url"],
        },
        hello_ack={
            "v": 1,
            "type": "hello_ack",
            "seq": 0,
            "session_id": VECTOR["session_id"],
            "session_sha256": base64.urlsafe_b64encode(
                bytes.fromhex(VECTOR["transcript_sha256_hex"])
            ).rstrip(b"=").decode("ascii"),
            "device_nonce": VECTOR["device_nonce_b64url"],
            "device_public_key": VECTOR["device_public_b64url"],
            "model": "E1002",
            "firmware_version": "0.2.0-candidate.3",
            "factory_mac": "aa:bb:cc:dd:ee:ff",
            "chip": "ESP32-S3",
            "chip_revision": 0,
            "config_generation": 0,
            "identity_strength": "physical_cable_only",
            "attestation": False,
        },
    )


def _credential(token: str, *, device_id: int, generation: int, state: str):
    now = datetime.now(timezone.utc)
    return TerminalDeviceCredential(
        device_id=device_id,
        token_sha256=hashlib.sha256(token.encode("ascii")).hexdigest(),
        config_sha256=f"{generation:x}" * 64,
        generation=generation,
        state=state,
        activated_at=now if state in {"active", "rollback"} else None,
        revoked_at=now if state == "revoked" else None,
        created_at=now,
        updated_at=now,
    )


def _issued_attempt(
    *,
    user_id: int,
    device: TerminalDevice,
    credential: TerminalDeviceCredential,
    created_at: datetime | None = None,
) -> TerminalEnrollmentAttempt:
    now = datetime.now(timezone.utc)
    created_at = created_at or now
    unique = uuid4().hex
    return TerminalEnrollmentAttempt(
        user_id=user_id,
        device_id=device.id,
        credential_id=credential.id,
        client_intent_id=uuid4(),
        intent_fingerprint=hashlib.sha256(f"intent:{unique}".encode()).hexdigest(),
        transcript_sha256=hashlib.sha256(f"transcript:{unique}".encode()).hexdigest(),
        session_id=unique[:22],
        operation="provision",
        device_model=device.hardware_model,
        device_mac=device.mac,
        firmware_version="0.2.0-candidate.3",
        firmware_release_id="a" * 64,
        enrollment_key_id="ret1-postgres-test",
        observed_generation=credential.generation - 1,
        target_generation=credential.generation,
        client_ticket_id=uuid4(),
        ticket_fingerprint=hashlib.sha256(f"ticket:{unique}".encode()).hexdigest(),
        config_sha256=credential.config_sha256,
        jti_sha256=hashlib.sha256(f"jti:{unique}".encode()).hexdigest(),
        compact_jws="header.payload.signature",
        status="issued",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        created_at=created_at,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def _fixed_policy(monkeypatch):
    policy = _policy()

    async def ready_policy():
        return policy

    async def any_policy():
        return policy

    monkeypatch.setattr(enrollment_router, "_ready_policy", ready_policy)
    monkeypatch.setattr(enrollment_router, "_policy", any_policy)
    return policy


async def test_ticket_is_idempotent_and_activation_requires_device_checkin(_fixed_policy):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            user = User(username="ret1-owner", is_active=True)
            db.add(user)
            await db.flush()
            db.add(TerminalSettings(user_id=user.id, code="ret1-test-code", timezone="UTC"))
            await db.commit()

            intent_payload = _intent()
            intent_result = await enrollment_router.create_enrollment_intent(
                _request("/api/terminal/enrollment/intents"),
                Response(),
                intent_payload,
                db,
                user,
            )
            attempt_id = UUID(intent_result["attempt_id"])
            assert intent_result["state"] == "initialized"
            assert intent_result["terminal"]["target_generation"] == 1
            assert intent_result["schedule_url_template"].endswith(
                "/{credential}/schedule.json"
            )

            raw_credential = "A" * 43
            credential_hash = hashlib.sha256(raw_credential.encode("ascii")).hexdigest()
            ticket_payload = EnrollmentTicketRequest(
                client_ticket_id=uuid4(),
                credential_sha256=credential_hash,
                config_sha256=VECTOR["config_sha256_hex"],
            )
            ticket_one = await enrollment_router.issue_enrollment_ticket(
                _request(f"/api/terminal/enrollment/intents/{attempt_id}/ticket"),
                Response(),
                attempt_id,
                ticket_payload,
                db,
                user,
            )
            ticket_two = await enrollment_router.issue_enrollment_ticket(
                _request(f"/api/terminal/enrollment/intents/{attempt_id}/ticket"),
                Response(),
                attempt_id,
                ticket_payload,
                db,
                user,
            )
            assert ticket_two["ticket"] == ticket_one["ticket"]
            assert ticket_one["state"] == "issued"

            with pytest.raises(HTTPException) as conflict:
                await enrollment_router.issue_enrollment_ticket(
                    _request(f"/api/terminal/enrollment/intents/{attempt_id}/ticket"),
                    Response(),
                    attempt_id,
                    ticket_payload.model_copy(update={"config_sha256": "e" * 64}),
                    db,
                    user,
                )
            assert conflict.value.status_code == 409

            complete = await enrollment_router.complete_enrollment_intent(
                _request(f"/api/terminal/enrollment/intents/{attempt_id}/complete"),
                Response(),
                attempt_id,
                EnrollmentCompleteRequest(
                    client_ticket_id=ticket_payload.client_ticket_id,
                    operation="provision",
                    generation=1,
                    config_sha256=VECTOR["config_sha256_hex"],
                ),
                db,
                user,
            )
            assert complete["state"] == "client_confirmed"
            attempt = await db.scalar(
                select(TerminalEnrollmentAttempt).where(
                    TerminalEnrollmentAttempt.attempt_id == attempt_id
                )
            )
            device = await db.get(TerminalDevice, attempt.device_id)
            credential = await db.get(TerminalDeviceCredential, attempt.credential_id)
            assert device.enrollment_state == "pending"
            assert credential.state == "candidate"
            assert credential.token_sha256 == credential_hash
            assert raw_credential not in repr(credential.__dict__)

            activated_device, _terminal_settings, _variant = (
                await enrollment_router._scoped_device(
                    db,
                    public_id=device.public_id,
                    credential_token=raw_credential,
                    request=_request("/terminal/device/checkin", mac=device.mac),
                    variant_name=None,
                )
            )
            await db.refresh(attempt)
            await db.refresh(credential)
            assert activated_device.enrollment_state == "enrolled"
            assert activated_device.enrollment_generation == 1
            assert activated_device.last_secure_checkin_at is not None
            assert credential.state == "active"
            assert attempt.status == "activated"
    finally:
        await engine.dispose()


async def test_enrolled_device_cannot_fall_back_to_shared_legacy_code(_fixed_policy):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            user = User(username="ret1-legacy-boundary", is_active=True)
            db.add(user)
            await db.flush()
            device = TerminalDevice(
                user_id=user.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Secure terminal",
                enrollment_state="enrolled",
                enrollment_generation=1,
                enrollment_config_sha256="d" * 64,
                enrollment_activated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.commit()
            prior_last_seen = device.last_seen_at

            result = await _upsert_device(
                db,
                user_id=user.id,
                request=_request("/terminal/shared/schedule.json", mac=device.mac),
                variant=parse_variant("spectra6_800x480"),
            )

            assert result is None
            await db.refresh(device)
            assert device.last_seen_at == prior_last_seen
    finally:
        await engine.dispose()


async def test_pending_first_enrollment_keeps_only_owners_legacy_checkin():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            owner = User(username="ret1-pending-owner", is_active=True)
            other = User(username="ret1-pending-other", is_active=True)
            db.add_all((owner, other))
            await db.flush()
            device = TerminalDevice(
                user_id=owner.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Pending terminal",
                hardware_model="E1002",
                enrollment_state="pending",
                enrollment_generation=0,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.commit()

            owner_result = await _upsert_device(
                db,
                user_id=owner.id,
                request=_request("/terminal/owner/schedule.json", mac=device.mac),
                variant=parse_variant("spectra6_800x480"),
            )
            assert owner_result is not None
            owner_last_seen = owner_result.last_seen_at

            other_result = await _upsert_device(
                db,
                user_id=other.id,
                request=_request("/terminal/other/schedule.json", mac=device.mac),
                variant=parse_variant("spectra6_800x480"),
            )
            assert other_result is None
            await db.refresh(device)
            assert device.user_id == owner.id
            assert device.enrollment_state == "pending"
            assert device.last_seen_at == owner_last_seen
    finally:
        await engine.dispose()


async def test_reenrollment_retains_one_rollback_credential_during_grace():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            user = User(username="ret1-reenroll-owner", is_active=True)
            db.add(user)
            await db.flush()
            db.add(TerminalSettings(user_id=user.id, code="ret1-reenroll", timezone="UTC"))
            device = TerminalDevice(
                user_id=user.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Re-enrolling terminal",
                hardware_model="E1002",
                enrollment_state="enrolled",
                enrollment_generation=2,
                enrollment_config_sha256="2" * 64,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_activated_at=datetime.now(timezone.utc),
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.flush()
            oldest_token = "A" * 43
            active_token = "B" * 43
            candidate_token = "C" * 43
            oldest = _credential(
                oldest_token, device_id=device.id, generation=1, state="rollback"
            )
            active = _credential(
                active_token, device_id=device.id, generation=2, state="active"
            )
            candidate = _credential(
                candidate_token, device_id=device.id, generation=3, state="candidate"
            )
            db.add_all((oldest, active, candidate))
            await db.flush()
            attempt = _issued_attempt(
                user_id=user.id,
                device=device,
                credential=candidate,
            )
            db.add(attempt)
            await db.commit()

            old_active, _settings, _variant = await enrollment_router._scoped_device(
                db,
                public_id=device.public_id,
                credential_token=active_token,
                request=_request("/terminal/device/active", mac=device.mac),
                variant_name=None,
            )
            assert old_active.enrollment_generation == 2
            await db.refresh(active)
            assert active.state == "active"

            activated, _settings, _variant = await enrollment_router._scoped_device(
                db,
                public_id=device.public_id,
                credential_token=candidate_token,
                request=_request("/terminal/device/candidate", mac=device.mac),
                variant_name=None,
            )
            assert activated.enrollment_generation == 3
            await db.refresh(oldest)
            await db.refresh(active)
            await db.refresh(candidate)
            assert oldest.state == "revoked"
            assert active.state == "rollback"
            assert candidate.state == "active"

            rollback_device, _settings, _variant = await enrollment_router._scoped_device(
                db,
                public_id=device.public_id,
                credential_token=active_token,
                request=_request("/terminal/device/rollback", mac=device.mac),
                variant_name=None,
            )
            assert rollback_device.enrollment_generation == 3
            await db.refresh(active)
            assert active.state == "rollback"
            assert active.last_used_at is not None

            device.enrollment_activated_at = (
                datetime.now(timezone.utc)
                - enrollment_router.ROLLBACK_LIFETIME
                - timedelta(minutes=1)
            )
            await db.commit()
            with pytest.raises(HTTPException) as grace_expired:
                await enrollment_router._scoped_device(
                    db,
                    public_id=device.public_id,
                    credential_token=active_token,
                    request=_request(
                        "/terminal/device/expired-rollback",
                        mac=device.mac,
                    ),
                    variant_name=None,
                )
            assert grace_expired.value.status_code == 404
    finally:
        await engine.dispose()


async def test_rollback_credential_rejects_a_generation_gap():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            user = User(username="ret1-rollback-gap", is_active=True)
            db.add(user)
            await db.flush()
            db.add(TerminalSettings(user_id=user.id, code="ret1-gap", timezone="UTC"))
            device = TerminalDevice(
                user_id=user.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Generation gap terminal",
                hardware_model="E1002",
                enrollment_state="enrolled",
                enrollment_generation=3,
                enrollment_config_sha256="3" * 64,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_activated_at=datetime.now(timezone.utc),
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.flush()
            gap_token = "H" * 43
            gap = _credential(
                gap_token,
                device_id=device.id,
                generation=1,
                state="rollback",
            )
            active = _credential(
                "I" * 43,
                device_id=device.id,
                generation=3,
                state="active",
            )
            db.add_all((gap, active))
            await db.commit()

            with pytest.raises(HTTPException) as rejected:
                await enrollment_router._scoped_device(
                    db,
                    public_id=device.public_id,
                    credential_token=gap_token,
                    request=_request(
                        "/terminal/device/gapped-rollback",
                        mac=device.mac,
                    ),
                    variant_name=None,
                )
            assert rejected.value.status_code == 404
            await db.refresh(gap)
            assert gap.last_used_at is None
    finally:
        await engine.dispose()


async def test_revoke_is_idempotent_and_invalidates_every_scoped_credential(monkeypatch):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        monkeypatch.setattr(
            enrollment_router.settings,
            "allowed_origins",
            "https://email.mcchord.net",
        )
        async with sessions() as db:
            user = User(username="ret1-revoke-owner", is_active=True)
            db.add(user)
            await db.flush()
            db.add(TerminalSettings(user_id=user.id, code="ret1-revoke", timezone="UTC"))
            device = TerminalDevice(
                user_id=user.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Revoked terminal",
                hardware_model="E1002",
                enrollment_state="enrolled",
                enrollment_generation=2,
                enrollment_config_sha256="2" * 64,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_activated_at=datetime.now(timezone.utc),
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.flush()
            rollback_token = "D" * 43
            active_token = "E" * 43
            candidate_token = "F" * 43
            rollback = _credential(
                rollback_token, device_id=device.id, generation=1, state="rollback"
            )
            active = _credential(
                active_token, device_id=device.id, generation=2, state="active"
            )
            candidate = _credential(
                candidate_token, device_id=device.id, generation=3, state="candidate"
            )
            db.add_all((rollback, active, candidate))
            await db.flush()
            attempt = _issued_attempt(
                user_id=user.id,
                device=device,
                credential=candidate,
            )
            db.add(attempt)
            await db.commit()

            first = await enrollment_router.revoke_terminal_enrollment(
                _request(f"/api/terminal/enrollment/devices/{device.public_id}/revoke"),
                Response(),
                device.public_id,
                db,
                user,
            )
            second = await enrollment_router.revoke_terminal_enrollment(
                _request(f"/api/terminal/enrollment/devices/{device.public_id}/revoke"),
                Response(),
                device.public_id,
                db,
                user,
            )
            assert first == second
            assert first["enrollment_state"] == "revoked"
            assert first["revoked_generations"] == 3

            credentials = list(
                (
                    await db.scalars(
                        select(TerminalDeviceCredential).where(
                            TerminalDeviceCredential.device_id == device.id
                        )
                    )
                ).all()
            )
            assert {credential.state for credential in credentials} == {"revoked"}
            assert all(credential.revoked_at is not None for credential in credentials)
            await db.refresh(attempt)
            assert attempt.status == "superseded"

            for token in (rollback_token, active_token, candidate_token):
                with pytest.raises(HTTPException) as revoked:
                    await enrollment_router._scoped_device(
                        db,
                        public_id=device.public_id,
                        credential_token=token,
                        request=_request("/terminal/device/revoked", mac=device.mac),
                        variant_name=None,
                    )
                assert revoked.value.status_code == 404
    finally:
        await engine.dispose()


async def test_cross_owner_cannot_revoke_a_secure_terminal(monkeypatch):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        monkeypatch.setattr(
            enrollment_router.settings,
            "allowed_origins",
            "https://email.mcchord.net",
        )
        async with sessions() as db:
            owner = User(username="ret1-revoke-owner-only", is_active=True)
            other = User(username="ret1-revoke-cross-owner", is_active=True)
            db.add_all((owner, other))
            await db.flush()
            device = TerminalDevice(
                user_id=owner.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Owner-only terminal",
                hardware_model="E1002",
                enrollment_state="enrolled",
                enrollment_generation=1,
                enrollment_config_sha256="1" * 64,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_activated_at=datetime.now(timezone.utc),
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.flush()
            active = _credential(
                "J" * 43,
                device_id=device.id,
                generation=1,
                state="active",
            )
            db.add(active)
            await db.commit()

            with pytest.raises(HTTPException) as denied:
                await enrollment_router.revoke_terminal_enrollment(
                    _request(
                        f"/api/terminal/enrollment/devices/{device.public_id}/revoke"
                    ),
                    Response(),
                    device.public_id,
                    db,
                    other,
                )
            assert denied.value.status_code == 404
            await db.refresh(device)
            await db.refresh(active)
            assert device.user_id == owner.id
            assert device.enrollment_state == "enrolled"
            assert active.state == "active"
            assert active.revoked_at is None
    finally:
        await engine.dispose()


async def test_revoked_terminal_can_complete_a_fresh_enrollment(monkeypatch):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        monkeypatch.setattr(
            enrollment_router.settings,
            "allowed_origins",
            "https://email.mcchord.net",
        )
        transcript = hashlib.sha256(b"revoked-terminal-reenrollment").hexdigest()

        def generation_one_handshake(_status, _hello, _ack, *, expected_key_id):
            return ValidatedHandshake(
                model="E1002",
                mac="aa:bb:cc:dd:ee:ff",
                firmware_version="0.2.0-candidate.3",
                generation=1,
                transcript_sha256_hex=transcript,
                session_id=base64.urlsafe_b64encode(bytes.fromhex(transcript)[:16])
                .rstrip(b"=")
                .decode("ascii"),
            )

        monkeypatch.setattr(
            enrollment_router,
            "validate_handshake",
            generation_one_handshake,
        )
        async with sessions() as db:
            user = User(username="ret1-reenroll-revoked", is_active=True)
            db.add(user)
            await db.flush()
            db.add(
                TerminalSettings(
                    user_id=user.id,
                    code="ret1-revoked-new",
                    timezone="UTC",
                )
            )
            device = TerminalDevice(
                user_id=user.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Revoked then re-enrolled",
                hardware_model="E1002",
                enrollment_state="enrolled",
                enrollment_generation=1,
                enrollment_config_sha256="1" * 64,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_activated_at=datetime.now(timezone.utc),
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.flush()
            old_active = _credential(
                "K" * 43,
                device_id=device.id,
                generation=1,
                state="active",
            )
            db.add(old_active)
            await db.commit()

            revoked = await enrollment_router.revoke_terminal_enrollment(
                _request(f"/api/terminal/enrollment/devices/{device.public_id}/revoke"),
                Response(),
                device.public_id,
                db,
                user,
            )
            assert revoked["enrollment_state"] == "revoked"

            intent = await enrollment_router.create_enrollment_intent(
                _request("/api/terminal/enrollment/intents"),
                Response(),
                _intent(),
                db,
                user,
            )
            attempt_id = UUID(intent["attempt_id"])
            assert intent["terminal"]["observed_generation"] == 1
            assert intent["terminal"]["target_generation"] == 2
            await db.refresh(device)
            assert device.enrollment_state == "revoked"

            new_token = "L" * 43
            config_hash = "2" * 64
            ticket_payload = EnrollmentTicketRequest(
                client_ticket_id=uuid4(),
                credential_sha256=hashlib.sha256(
                    new_token.encode("ascii")
                ).hexdigest(),
                config_sha256=config_hash,
            )
            ticket = await enrollment_router.issue_enrollment_ticket(
                _request(f"/api/terminal/enrollment/intents/{attempt_id}/ticket"),
                Response(),
                attempt_id,
                ticket_payload,
                db,
                user,
            )
            assert ticket["state"] == "issued"
            completed = await enrollment_router.complete_enrollment_intent(
                _request(f"/api/terminal/enrollment/intents/{attempt_id}/complete"),
                Response(),
                attempt_id,
                EnrollmentCompleteRequest(
                    client_ticket_id=ticket_payload.client_ticket_id,
                    operation="provision",
                    generation=2,
                    config_sha256=config_hash,
                ),
                db,
                user,
            )
            assert completed["state"] == "client_confirmed"
            await db.refresh(device)
            assert device.enrollment_state == "revoked"

            activated, _settings, _variant = await enrollment_router._scoped_device(
                db,
                public_id=device.public_id,
                credential_token=new_token,
                request=_request("/terminal/device/re-enrolled", mac=device.mac),
                variant_name=None,
            )
            assert activated.enrollment_state == "enrolled"
            assert activated.enrollment_generation == 2
            assert activated.enrollment_config_sha256 == config_hash
            credentials = list(
                (
                    await db.scalars(
                        select(TerminalDeviceCredential)
                        .where(TerminalDeviceCredential.device_id == device.id)
                        .order_by(TerminalDeviceCredential.generation)
                    )
                ).all()
            )
            assert [(item.generation, item.state) for item in credentials] == [
                (1, "revoked"),
                (2, "active"),
            ]
    finally:
        await engine.dispose()


async def test_concurrent_same_mac_claim_creates_only_one_owner(monkeypatch):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            first_user = User(username="ret1-race-first", is_active=True)
            second_user = User(username="ret1-race-second", is_active=True)
            db.add_all((first_user, second_user))
            await db.commit()
            first_user_id = first_user.id
            second_user_id = second_user.id

        def distinct_handshake(_status, hello, _ack, *, expected_key_id):
            marker = hello["client_nonce"]
            digest = hashlib.sha256(marker.encode("ascii")).hexdigest()
            return ValidatedHandshake(
                model="E1002",
                mac="aa:bb:cc:dd:ee:ff",
                firmware_version="0.2.0-candidate.3",
                generation=0,
                transcript_sha256_hex=digest,
                session_id=base64.urlsafe_b64encode(bytes.fromhex(digest)[:16])
                .rstrip(b"=")
                .decode("ascii"),
            )

        monkeypatch.setattr(enrollment_router, "validate_handshake", distinct_handshake)
        first_payload = _intent()
        second_payload = _intent()
        second_payload.hello.client_nonce = "Z" * 43
        started = (asyncio.Event(), asyncio.Event())

        async def claim(
            user_id: int,
            payload: EnrollmentIntentRequest,
            ready: asyncio.Event,
        ):
            async with sessions() as db:
                user = await db.get(User, user_id)
                ready.set()
                try:
                    result = await enrollment_router.create_enrollment_intent(
                        _request("/api/terminal/enrollment/intents"),
                        Response(),
                        payload,
                        db,
                        user,
                    )
                    return ("created", result["terminal"]["id"])
                except HTTPException as exc:
                    await db.rollback()
                    return ("rejected", exc.status_code)

        async with sessions() as blocker:
            await enrollment_router._advisory_identity_lock(
                blocker,
                "aa:bb:cc:dd:ee:ff",
            )
            tasks = (
                asyncio.create_task(
                    claim(first_user_id, first_payload, started[0])
                ),
                asyncio.create_task(
                    claim(second_user_id, second_payload, started[1])
                ),
            )
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in started)),
                timeout=1,
            )
            await asyncio.sleep(0.05)
            assert all(not task.done() for task in tasks)
            await blocker.commit()
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
        assert sorted(result[0] for result in results) == ["created", "rejected"]
        assert next(result[1] for result in results if result[0] == "rejected") == 409

        async with sessions() as db:
            devices = list(
                (
                    await db.scalars(
                        select(TerminalDevice).where(
                            TerminalDevice.mac == "aa:bb:cc:dd:ee:ff"
                        )
                    )
                ).all()
            )
            attempts = list((await db.scalars(select(TerminalEnrollmentAttempt))).all())
            assert len(devices) == 1
            assert devices[0].user_id in {first_user_id, second_user_id}
            assert len(attempts) == 1
            assert attempts[0].user_id == devices[0].user_id
    finally:
        await engine.dispose()


async def test_concurrent_identical_intent_replays_one_database_graph():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            user = User(username="ret1-idempotent-race", is_active=True)
            db.add(user)
            await db.commit()
            user_id = user.id

        payload = _intent()
        started = (asyncio.Event(), asyncio.Event())

        async def create(ready: asyncio.Event):
            async with sessions() as db:
                user = await db.get(User, user_id)
                ready.set()
                return await enrollment_router.create_enrollment_intent(
                    _request("/api/terminal/enrollment/intents"),
                    Response(),
                    payload,
                    db,
                    user,
                )

        async with sessions() as blocker:
            await enrollment_router._advisory_identity_lock(
                blocker,
                "aa:bb:cc:dd:ee:ff",
            )
            tasks = (
                asyncio.create_task(create(started[0])),
                asyncio.create_task(create(started[1])),
            )
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in started)),
                timeout=1,
            )
            await asyncio.sleep(0.05)
            assert all(not task.done() for task in tasks)
            await blocker.commit()
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
        assert results[0]["attempt_id"] == results[1]["attempt_id"]
        assert results[0]["terminal"]["id"] == results[1]["terminal"]["id"]

        async with sessions() as db:
            devices = list((await db.scalars(select(TerminalDevice))).all())
            attempts = list((await db.scalars(select(TerminalEnrollmentAttempt))).all())
            credentials = list(
                (await db.scalars(select(TerminalDeviceCredential))).all()
            )
            assert len(devices) == 1
            assert len(attempts) == 1
            assert credentials == []
            assert str(devices[0].public_id) == results[0]["terminal"]["id"]
            assert str(attempts[0].attempt_id) == results[0]["attempt_id"]
            assert attempts[0].device_id == devices[0].id
    finally:
        await engine.dispose()


async def test_activation_and_stale_expiry_commit_only_consistent_terminal_state():
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        async with sessions() as db:
            user = User(username="ret1-expiry-race", is_active=True)
            db.add(user)
            await db.flush()
            db.add(TerminalSettings(user_id=user.id, code="ret1-expiry", timezone="UTC"))
            device = TerminalDevice(
                user_id=user.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Expiry race terminal",
                hardware_model="E1002",
                enrollment_state="pending",
                enrollment_generation=0,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.flush()
            candidate_token = "G" * 43
            candidate = _credential(
                candidate_token, device_id=device.id, generation=1, state="candidate"
            )
            db.add(candidate)
            await db.flush()
            attempt = _issued_attempt(
                user_id=user.id,
                device=device,
                credential=candidate,
                created_at=datetime.now(timezone.utc)
                - enrollment_router.ACTIVE_ATTEMPT_WINDOW
                - timedelta(minutes=1),
            )
            db.add(attempt)
            await db.commit()
            device_id = device.id
            user_id = user.id
            public_id = device.public_id
            attempt_id = attempt.attempt_id
            credential_id = candidate.id

        activation_started = asyncio.Event()
        expiry_started = asyncio.Event()

        async def activate():
            async with sessions() as db:
                activation_started.set()
                try:
                    await enrollment_router._scoped_device(
                        db,
                        public_id=public_id,
                        credential_token=candidate_token,
                        request=_request(
                            "/terminal/device/candidate-race",
                            mac="aa:bb:cc:dd:ee:ff",
                        ),
                        variant_name=None,
                    )
                    return "activated"
                except HTTPException as exc:
                    await db.rollback()
                    assert exc.status_code == 404
                    return "rejected"

        async def expire():
            async with sessions() as db:
                expiry_started.set()
                locked_attempt, locked_device = (
                    await enrollment_router._lock_owned_attempt_graph(
                        db,
                        user_id,
                        attempt_id,
                    )
                )
                expired = await enrollment_router._expire_stale_attempt(
                    db,
                    locked_attempt,
                    locked_device,
                )
                await db.commit()
                return "expired" if expired else "already-terminal"

        async with sessions() as blocker:
            locked_device = await blocker.scalar(
                select(TerminalDevice)
                .where(TerminalDevice.id == device_id)
                .with_for_update()
            )
            assert locked_device is not None
            tasks = (asyncio.create_task(activate()), asyncio.create_task(expire()))
            await asyncio.wait_for(
                asyncio.gather(
                    activation_started.wait(),
                    expiry_started.wait(),
                ),
                timeout=1,
            )
            await asyncio.sleep(0.05)
            assert all(not task.done() for task in tasks)
            await blocker.commit()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

        async with sessions() as db:
            device = await db.get(TerminalDevice, device_id)
            attempt = await db.scalar(
                select(TerminalEnrollmentAttempt).where(
                    TerminalEnrollmentAttempt.attempt_id == attempt_id
                )
            )
            credential = await db.get(TerminalDeviceCredential, credential_id)
            final_state = (
                device.enrollment_state,
                device.enrollment_generation,
                attempt.status,
                credential.state,
            )
            assert final_state in {
                ("enrolled", 1, "activated", "active"),
                ("legacy", 0, "expired", "revoked"),
            }
            if attempt.status == "activated":
                assert device.enrollment_config_sha256 == credential.config_sha256
                assert device.enrollment_activated_at is not None
                assert credential.activated_at is not None
                assert credential.revoked_at is None
            else:
                assert device.enrollment_config_sha256 is None
                assert device.enrollment_activated_at is None
                assert credential.activated_at is None
                assert credential.revoked_at is not None
    finally:
        await engine.dispose()


async def test_activation_and_revoke_serialize_on_the_device_row(monkeypatch):
    engine, sessions = _sessions()
    try:
        await _reset(engine)
        monkeypatch.setattr(
            enrollment_router.settings,
            "allowed_origins",
            "https://email.mcchord.net",
        )
        async with sessions() as db:
            user = User(username="ret1-revoke-race", is_active=True)
            db.add(user)
            await db.flush()
            db.add(
                TerminalSettings(
                    user_id=user.id,
                    code="ret1-revoke-race",
                    timezone="UTC",
                )
            )
            device = TerminalDevice(
                user_id=user.id,
                mac="aa:bb:cc:dd:ee:ff",
                name="Revoke race terminal",
                hardware_model="E1002",
                enrollment_state="pending",
                enrollment_generation=0,
                enrollment_release_id="a" * 64,
                enrollment_key_id="ret1-postgres-test",
                enrollment_updated_at=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.flush()
            candidate_token = "M" * 43
            candidate = _credential(
                candidate_token,
                device_id=device.id,
                generation=1,
                state="candidate",
            )
            db.add(candidate)
            await db.flush()
            attempt = _issued_attempt(
                user_id=user.id,
                device=device,
                credential=candidate,
            )
            db.add(attempt)
            await db.commit()
            user_id = user.id
            device_id = device.id
            public_id = device.public_id
            credential_id = candidate.id
            attempt_id = attempt.attempt_id

        activation_started = asyncio.Event()
        revoke_started = asyncio.Event()

        async def activate():
            async with sessions() as db:
                activation_started.set()
                try:
                    await enrollment_router._scoped_device(
                        db,
                        public_id=public_id,
                        credential_token=candidate_token,
                        request=_request(
                            "/terminal/device/revoke-race",
                            mac="aa:bb:cc:dd:ee:ff",
                        ),
                        variant_name=None,
                    )
                    return "activated"
                except HTTPException as exc:
                    await db.rollback()
                    assert exc.status_code == 404
                    return "rejected"

        async def revoke():
            async with sessions() as db:
                user = await db.get(User, user_id)
                revoke_started.set()
                result = await enrollment_router.revoke_terminal_enrollment(
                    _request(
                        f"/api/terminal/enrollment/devices/{public_id}/revoke"
                    ),
                    Response(),
                    public_id,
                    db,
                    user,
                )
                return result["enrollment_state"]

        async with sessions() as blocker:
            locked_device = await blocker.scalar(
                select(TerminalDevice)
                .where(TerminalDevice.id == device_id)
                .with_for_update()
            )
            assert locked_device is not None
            tasks = (asyncio.create_task(activate()), asyncio.create_task(revoke()))
            await asyncio.wait_for(
                asyncio.gather(
                    activation_started.wait(),
                    revoke_started.wait(),
                ),
                timeout=1,
            )
            await asyncio.sleep(0.05)
            assert all(not task.done() for task in tasks)
            await blocker.commit()
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
        assert results[1] == "revoked"

        async with sessions() as db:
            device = await db.get(TerminalDevice, device_id)
            credential = await db.get(TerminalDeviceCredential, credential_id)
            attempt = await db.scalar(
                select(TerminalEnrollmentAttempt).where(
                    TerminalEnrollmentAttempt.attempt_id == attempt_id
                )
            )
            assert device.enrollment_state == "revoked"
            assert credential.state == "revoked"
            assert credential.revoked_at is not None
            assert attempt.status in {"activated", "superseded"}
            remaining_usable = await db.scalar(
                select(TerminalDeviceCredential.id).where(
                    TerminalDeviceCredential.device_id == device_id,
                    TerminalDeviceCredential.state.in_(
                        ("candidate", "active", "rollback")
                    ),
                )
            )
            assert remaining_usable is None
            if results[0] == "activated":
                assert attempt.status == "activated"
                assert credential.activated_at is not None
            else:
                assert attempt.status == "superseded"
    finally:
        await engine.dispose()
