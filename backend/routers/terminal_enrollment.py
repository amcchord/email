"""Fail-closed RET1 enrollment APIs and per-device schedule routes.

Authenticated browser APIs may create one owner-scoped intent and obtain one
short-lived ES256 enrollment ticket. Browser completion is advisory. A device
becomes enrolled only when its candidate credential is observed on the scoped
HTTPS route with the expected factory MAC.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.config import get_settings
from backend.database import get_db
from backend.models.terminal import (
    TerminalDevice,
    TerminalDeviceCredential,
    TerminalEnrollmentAttempt,
    TerminalSettings,
)
from backend.models.user import User
from backend.routers.auth import get_current_user, limiter
from backend.routers.terminal import (
    _apply_device_telemetry,
    _normalize_mac,
    _render_for_device,
)
from backend.services.terminal.enrollment_policy import (
    EnrollmentPolicy,
    EnrollmentPolicyError,
    evaluate_enrollment_policy,
)
from backend.services.terminal.enrollment_protocol import (
    EnrollmentProtocolError,
    sign_enrollment_ticket,
    validate_handshake,
)
from backend.services.terminal.variants import aligned_next_checkin_sec, parse_variant


logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(tags=["terminal-enrollment"])

HASH_RE = re.compile(r"[0-9a-f]{64}")
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
MODEL_VARIANT_QUERY = {"E1001": "bw", "E1002": ""}
MAX_ACTIVE_ATTEMPTS = 8
ACTIVE_ATTEMPT_WINDOW = timedelta(hours=24)
CANDIDATE_LIFETIME = timedelta(hours=24)
ROLLBACK_LIFETIME = timedelta(hours=24)
PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}
DEVICE_HEADERS = {
    "Cache-Control": "private, no-cache",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Ret1Status(StrictModel):
    v: Literal[1]
    type: Literal["status"]
    state: Literal["storage_error", "config_ready", "provisioning_required"]
    model: Literal["E1001", "E1002", "E1004"]
    firmware_version: str = Field(min_length=1, max_length=128)
    factory_mac: str = Field(min_length=17, max_length=17)
    config_source: Literal["nvs", "file", "fallback"]
    config_generation: int = Field(ge=0, le=4_294_967_295)
    enrollment_available: bool
    enrollment_key_id: str = Field(max_length=64)
    identity_strength: Literal["physical_cable_only"]
    attestation: Literal[False]


class Ret1Hello(StrictModel):
    v: Literal[1]
    type: Literal["hello"]
    seq: Literal[0]
    client_nonce: str = Field(min_length=43, max_length=43)
    client_public_key: str = Field(min_length=87, max_length=87)


class Ret1HelloAck(StrictModel):
    v: Literal[1]
    type: Literal["hello_ack"]
    seq: Literal[0]
    session_id: str = Field(min_length=22, max_length=22)
    session_sha256: str = Field(min_length=43, max_length=43)
    device_nonce: str = Field(min_length=43, max_length=43)
    device_public_key: str = Field(min_length=87, max_length=87)
    model: Literal["E1001", "E1002", "E1004"]
    firmware_version: str = Field(min_length=1, max_length=128)
    factory_mac: str = Field(min_length=17, max_length=17)
    chip: Literal["ESP32-S3"]
    chip_revision: int = Field(ge=0, le=4_294_967_295)
    config_generation: int = Field(ge=0, le=4_294_967_295)
    identity_strength: Literal["physical_cable_only"]
    attestation: Literal[False]


class EnrollmentIntentRequest(StrictModel):
    client_intent_id: UUID
    operation: Literal["provision"]
    status: Ret1Status
    hello: Ret1Hello
    hello_ack: Ret1HelloAck


class EnrollmentTicketRequest(StrictModel):
    client_ticket_id: UUID
    credential_sha256: str = Field(min_length=64, max_length=64)
    config_sha256: str = Field(min_length=64, max_length=64)


class EnrollmentCompleteRequest(StrictModel):
    client_ticket_id: UUID
    operation: Literal["provision"]
    generation: int = Field(ge=1, lt=4_294_967_295)
    config_sha256: str = Field(min_length=64, max_length=64)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _valid_hash(value: str) -> bool:
    return HASH_RE.fullmatch(value) is not None


def _require_same_origin_session(request: Request, policy: EnrollmentPolicy) -> None:
    _require_owner_mutation(request, exact_origin=policy.base_url)


def _require_owner_mutation(
    request: Request,
    *,
    exact_origin: str | None = None,
) -> None:
    if not request.cookies.get("access_token"):
        raise HTTPException(status_code=403, detail="Browser session required")
    origin = (request.headers.get("origin") or "").rstrip("/")
    allowed_origins = {
        value.strip().rstrip("/")
        for value in settings.allowed_origins.split(",")
        if value.strip()
    }
    if (
        not origin
        or (exact_origin is not None and origin != exact_origin)
        or (exact_origin is None and origin not in allowed_origins)
    ):
        raise HTTPException(status_code=403, detail="Same-origin browser request required")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site != "same-origin":
        raise HTTPException(status_code=403, detail="Same-origin browser request required")


async def _policy() -> EnrollmentPolicy:
    return await run_in_threadpool(evaluate_enrollment_policy, settings)


async def _ready_policy() -> EnrollmentPolicy:
    policy = await _policy()
    try:
        return policy.require_ready()
    except EnrollmentPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _attempt_response(attempt: TerminalEnrollmentAttempt, device: TerminalDevice, policy: EnrollmentPolicy) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "attempt_id": str(attempt.attempt_id),
        "state": attempt.status,
        "operation": attempt.operation,
        "session_id": attempt.session_id,
        "terminal": {
            "id": str(device.public_id),
            "model": attempt.device_model,
            "factory_mac": attempt.device_mac,
            "firmware_version": attempt.firmware_version,
            "observed_generation": attempt.observed_generation,
            "target_generation": attempt.target_generation,
        },
        "firmware_release": {
            "release_id": attempt.firmware_release_id,
            "enrollment_key_id": attempt.enrollment_key_id,
        },
        "schedule_url_template": (
            f"{policy.base_url}/terminal/device/{device.public_id}/"
            "{credential}/schedule.json"
            if policy.base_url
            else None
        ),
        "expires_at": attempt.expires_at,
        "client_completed_at": attempt.client_completed_at,
        "activated_at": attempt.activated_at,
    }


def _ticket_response(attempt: TerminalEnrollmentAttempt) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "attempt_id": str(attempt.attempt_id),
        "state": attempt.status,
        "operation": attempt.operation,
        "generation": attempt.target_generation,
        "config_sha256": attempt.config_sha256,
        "ticket": attempt.compact_jws,
        "issued_at": attempt.issued_at,
        "expires_at": attempt.expires_at,
        "activation": "first_scoped_https_checkin",
    }


async def _lock_owned_attempt_graph(
    db: AsyncSession,
    user_id: int,
    attempt_id: UUID,
) -> tuple[TerminalEnrollmentAttempt, TerminalDevice]:
    """Lock one enrollment graph in canonical device -> attempt order."""
    device_id = await db.scalar(
        select(TerminalEnrollmentAttempt.device_id).where(
            TerminalEnrollmentAttempt.attempt_id == attempt_id,
            TerminalEnrollmentAttempt.user_id == user_id,
        )
    )
    if device_id is None:
        raise HTTPException(status_code=404, detail="Enrollment attempt not found")
    device = await db.scalar(
        select(TerminalDevice)
        .where(TerminalDevice.id == device_id, TerminalDevice.user_id == user_id)
        .with_for_update()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Enrollment attempt not found")
    attempt = await db.scalar(
        select(TerminalEnrollmentAttempt).where(
            TerminalEnrollmentAttempt.attempt_id == attempt_id,
            TerminalEnrollmentAttempt.user_id == user_id,
        ).with_for_update()
    )
    if attempt is None or attempt.device_id != device.id:
        raise HTTPException(status_code=404, detail="Enrollment attempt not found")
    return attempt, device


async def _advisory_identity_lock(db: AsyncSession, mac: str) -> None:
    """Serialize ownership claims even when no device row exists to lock."""
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:terminal_identity, 0))"
        ),
        {"terminal_identity": f"terminal-enrollment:{mac}"},
    )


async def _expire_stale_attempt(
    db: AsyncSession,
    attempt: TerminalEnrollmentAttempt,
    device: TerminalDevice,
    *,
    now: datetime | None = None,
) -> bool:
    """Expire an abandoned browser flow and safely release a pending device.

    The signed ticket itself is intentionally short-lived, but an accepted
    config may need time to reboot and reach Wi-Fi. Candidate server state is
    therefore retained for a bounded 24-hour reconciliation window.
    """
    now = now or _utcnow()
    if attempt.status not in {"initialized", "issued", "client_confirmed"}:
        return False
    if attempt.created_at >= now - ACTIVE_ATTEMPT_WINDOW:
        return False
    attempt.status = "expired"
    attempt.updated_at = now
    if attempt.credential_id is not None:
        credential = await db.scalar(
            select(TerminalDeviceCredential)
            .where(TerminalDeviceCredential.id == attempt.credential_id)
            .with_for_update()
        )
        if credential is not None and credential.state == "candidate":
            credential.state = "revoked"
            credential.revoked_at = now
            credential.updated_at = now
    if device.enrollment_state == "pending":
        active_id = await db.scalar(
            select(TerminalDeviceCredential.id)
            .where(
                TerminalDeviceCredential.device_id == device.id,
                TerminalDeviceCredential.state == "active",
            )
            .with_for_update()
        )
        if active_id is None:
            device.enrollment_state = "legacy"
            device.enrollment_release_id = None
            device.enrollment_key_id = None
            device.enrollment_config_sha256 = None
            device.enrollment_updated_at = now
    return True


async def _existing_intent_response(
    db: AsyncSession,
    *,
    user_id: int,
    client_intent_id: UUID,
    fingerprint: str,
    policy: EnrollmentPolicy,
    response: Response,
) -> dict[str, Any] | None:
    attempt_id = await db.scalar(
        select(TerminalEnrollmentAttempt.attempt_id).where(
            TerminalEnrollmentAttempt.user_id == user_id,
            TerminalEnrollmentAttempt.client_intent_id == client_intent_id,
        )
    )
    if attempt_id is None:
        return None
    attempt, device = await _lock_owned_attempt_graph(db, user_id, attempt_id)
    if attempt.intent_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Enrollment intent conflicts with its prior use",
        )
    await _expire_stale_attempt(db, attempt, device)
    await db.commit()
    await db.refresh(attempt)
    await db.refresh(device)
    response.headers.update(PRIVATE_HEADERS)
    return _attempt_response(attempt, device, policy)


@router.get("/api/terminal/enrollment/capabilities")
@limiter.limit("12/minute")
async def enrollment_capabilities(
    request: Request,
    response: Response,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    policy = await _policy()
    response.headers.update(PRIVATE_HEADERS)
    return policy.as_capabilities()


@router.post("/api/terminal/enrollment/intents", status_code=201)
@limiter.limit("6/minute")
async def create_enrollment_intent(
    request: Request,
    response: Response,
    payload: EnrollmentIntentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    policy = await _ready_policy()
    _require_same_origin_session(request, policy)
    raw_payload = payload.model_dump(mode="json")
    fingerprint = _canonical_hash(raw_payload)
    existing_response = await _existing_intent_response(
        db,
        user_id=user.id,
        client_intent_id=payload.client_intent_id,
        fingerprint=fingerprint,
        policy=policy,
        response=response,
    )
    if existing_response is not None:
        return existing_response

    try:
        handshake = validate_handshake(
            raw_payload["status"],
            raw_payload["hello"],
            raw_payload["hello_ack"],
            expected_key_id=policy.signing_key_id,
        )
    except EnrollmentProtocolError as exc:
        raise HTTPException(status_code=400, detail=exc.safe_message) from exc
    if handshake.model == "E1004":
        raise HTTPException(status_code=409, detail="Terminal is not enrollment-qualified")
    try:
        release = policy.release_for(
            firmware_version=handshake.firmware_version,
            model=handshake.model,
        )
    except EnrollmentPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if handshake.generation >= 4_294_967_294:
        raise HTTPException(status_code=409, detail="Terminal configuration generation is exhausted")

    await _advisory_identity_lock(db, handshake.mac)
    existing_response = await _existing_intent_response(
        db,
        user_id=user.id,
        client_intent_id=payload.client_intent_id,
        fingerprint=fingerprint,
        policy=policy,
        response=response,
    )
    if existing_response is not None:
        return existing_response

    transcript_result = await db.execute(
        select(TerminalEnrollmentAttempt).where(
            TerminalEnrollmentAttempt.transcript_sha256 == handshake.transcript_sha256_hex
        )
    )
    if transcript_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Enrollment transcript has already been used")

    active_count = await db.scalar(
        select(func.count(TerminalEnrollmentAttempt.id)).where(
            TerminalEnrollmentAttempt.user_id == user.id,
            TerminalEnrollmentAttempt.status.in_(("initialized", "issued", "client_confirmed")),
            TerminalEnrollmentAttempt.created_at >= _utcnow() - ACTIVE_ATTEMPT_WINDOW,
        )
    )
    if int(active_count or 0) >= MAX_ACTIVE_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many active terminal enrollment attempts")

    devices_result = await db.execute(
        select(TerminalDevice)
        .where(TerminalDevice.mac == handshake.mac)
        .with_for_update()
    )
    devices = list(devices_result.scalars().all())
    if len(devices) > 1 or (devices and devices[0].user_id != user.id):
        raise HTTPException(status_code=409, detail="Terminal identity requires operator review")
    if devices:
        device = devices[0]
        if device.enrollment_state == "review":
            raise HTTPException(status_code=409, detail="Terminal identity requires operator review")
        if (
            device.enrollment_state in {"enrolled", "revoked"}
            and device.hardware_model is not None
            and device.hardware_model != handshake.model
        ):
            raise HTTPException(status_code=409, detail="Terminal identity requires operator review")
        if device.enrollment_generation != handshake.generation:
            raise HTTPException(status_code=409, detail="Terminal generation does not match server state")
        pending_result = await db.execute(
            select(TerminalEnrollmentAttempt).where(
                TerminalEnrollmentAttempt.device_id == device.id,
                TerminalEnrollmentAttempt.status.in_(("initialized", "issued", "client_confirmed")),
            ).with_for_update()
        )
        pending_attempts = list(pending_result.scalars().all())
        for pending_attempt in pending_attempts:
            await _expire_stale_attempt(
                db,
                pending_attempt,
                device,
                now=_utcnow(),
            )
        if any(
            pending_attempt.status in {"initialized", "issued", "client_confirmed"}
            for pending_attempt in pending_attempts
        ):
            raise HTTPException(status_code=409, detail="Terminal already has an active enrollment attempt")
    else:
        if handshake.generation != 0:
            raise HTTPException(status_code=409, detail="Terminal identity requires operator review")
        now = _utcnow()
        device = TerminalDevice(
            user_id=user.id,
            mac=handshake.mac,
            name=f"Terminal {handshake.mac[-5:].replace(':', '')}",
            hardware_model=handshake.model,
            variant=None,
            content_type="clock",
            enrollment_state="pending",
            enrollment_generation=0,
            enrollment_updated_at=now,
            created_at=now,
        )
        db.add(device)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            replay = await _existing_intent_response(
                db,
                user_id=user.id,
                client_intent_id=payload.client_intent_id,
                fingerprint=fingerprint,
                policy=policy,
                response=response,
            )
            if replay is not None:
                return replay
            raise HTTPException(
                status_code=409,
                detail="Terminal identity conflicts with existing state",
            ) from exc

    now = _utcnow()
    retained_secure_isolation = device.enrollment_state in {"enrolled", "revoked"}
    device.hardware_model = handshake.model
    device.last_fw_version = handshake.firmware_version[:64]
    if not retained_secure_isolation:
        device.enrollment_state = "pending"
        device.enrollment_release_id = release.release_id
        device.enrollment_key_id = release.trust_key_id
    device.enrollment_updated_at = now
    attempt = TerminalEnrollmentAttempt(
        user_id=user.id,
        device_id=device.id,
        client_intent_id=payload.client_intent_id,
        intent_fingerprint=fingerprint,
        transcript_sha256=handshake.transcript_sha256_hex,
        session_id=handshake.session_id,
        operation="provision",
        device_model=handshake.model,
        device_mac=handshake.mac,
        firmware_version=handshake.firmware_version,
        firmware_release_id=release.release_id,
        enrollment_key_id=release.trust_key_id,
        observed_generation=handshake.generation,
        target_generation=handshake.generation + 1,
        status="initialized",
        created_at=now,
        updated_at=now,
    )
    db.add(attempt)
    try:
        await db.commit()
        await db.refresh(attempt)
        await db.refresh(device)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Enrollment intent conflicts with existing state") from exc
    response.headers.update(PRIVATE_HEADERS)
    return _attempt_response(attempt, device, policy)


@router.post("/api/terminal/enrollment/intents/{attempt_id}/ticket")
@limiter.limit("6/minute")
async def issue_enrollment_ticket(
    request: Request,
    response: Response,
    attempt_id: UUID,
    payload: EnrollmentTicketRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    policy = await _ready_policy()
    _require_same_origin_session(request, policy)
    if not _valid_hash(payload.credential_sha256) or not _valid_hash(payload.config_sha256):
        raise HTTPException(status_code=400, detail="Enrollment hashes are invalid")
    fingerprint = _canonical_hash(payload.model_dump(mode="json"))
    attempt, device = await _lock_owned_attempt_graph(db, user.id, attempt_id)
    now = _utcnow()
    expired_now = await _expire_stale_attempt(db, attempt, device, now=now)
    if expired_now:
        await db.commit()
        raise HTTPException(status_code=409, detail="Enrollment attempt expired")
    if attempt.status != "initialized":
        if (
            attempt.status in {"issued", "client_confirmed", "activated"}
            and attempt.ticket_fingerprint == fingerprint
        ):
            await db.commit()
            response.headers.update(PRIVATE_HEADERS)
            return _ticket_response(attempt)
        raise HTTPException(status_code=409, detail="Enrollment ticket conflicts with its prior use")
    try:
        release = policy.release_for(
            firmware_version=attempt.firmware_version,
            model=attempt.device_model,
        )
    except EnrollmentPolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if release.release_id != attempt.firmware_release_id:
        raise HTTPException(status_code=409, detail="Enrollment firmware approval changed")

    existing_credential = await db.scalar(
        select(TerminalDeviceCredential.id).where(
            TerminalDeviceCredential.device_id == attempt.device_id,
            TerminalDeviceCredential.generation == attempt.target_generation,
        )
    )
    if existing_credential is not None:
        raise HTTPException(status_code=409, detail="Terminal generation already has a credential")

    credential = TerminalDeviceCredential(
        device_id=attempt.device_id,
        token_sha256=payload.credential_sha256,
        config_sha256=payload.config_sha256,
        generation=attempt.target_generation,
        state="candidate",
        created_at=now,
        updated_at=now,
    )
    db.add(credential)
    await db.flush()
    jti = secrets.token_urlsafe(24)
    expires_at = now + timedelta(seconds=policy.ticket_ttl_seconds)
    try:
        compact_jws = await run_in_threadpool(
            sign_enrollment_ticket,
            policy.signing_key,
            kid=policy.signing_key_id,
            operation="provision",
            session_sha256_hex=attempt.transcript_sha256,
            model=attempt.device_model,
            mac=attempt.device_mac,
            terminal_id=str(device.public_id),
            config_sha256_hex=payload.config_sha256,
            generation=attempt.target_generation,
            jti=jti,
            issued_at=int(now.timestamp()),
            expires_at=int(expires_at.timestamp()),
        )
    except EnrollmentProtocolError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail="Enrollment ticket could not be issued") from exc
    attempt.credential_id = credential.id
    attempt.client_ticket_id = payload.client_ticket_id
    attempt.ticket_fingerprint = fingerprint
    attempt.config_sha256 = payload.config_sha256
    attempt.jti_sha256 = _hash_token(jti)
    attempt.compact_jws = compact_jws
    attempt.status = "issued"
    attempt.issued_at = now
    attempt.expires_at = expires_at
    attempt.updated_at = now
    device.enrollment_updated_at = now
    try:
        await db.commit()
        await db.refresh(attempt)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Enrollment ticket conflicts with existing state") from exc
    response.headers.update(PRIVATE_HEADERS)
    return _ticket_response(attempt)


@router.post("/api/terminal/enrollment/intents/{attempt_id}/complete")
@limiter.limit("6/minute")
async def complete_enrollment_intent(
    request: Request,
    response: Response,
    attempt_id: UUID,
    payload: EnrollmentCompleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    policy = await _policy()
    _require_same_origin_session(request, policy)
    if not _valid_hash(payload.config_sha256):
        raise HTTPException(status_code=400, detail="Enrollment config hash is invalid")
    attempt, device = await _lock_owned_attempt_graph(db, user.id, attempt_id)
    expired_now = await _expire_stale_attempt(db, attempt, device)
    if expired_now:
        await db.commit()
        raise HTTPException(status_code=409, detail="Enrollment attempt expired")
    if (
        attempt.client_ticket_id != payload.client_ticket_id
        or attempt.operation != payload.operation
        or attempt.target_generation != payload.generation
        or attempt.config_sha256 != payload.config_sha256
    ):
        raise HTTPException(status_code=409, detail="Enrollment result does not match its ticket")
    if attempt.status == "activated":
        response.headers.update(PRIVATE_HEADERS)
        await db.commit()
        return _attempt_response(attempt, device, policy)
    if attempt.status not in {"issued", "client_confirmed"}:
        raise HTTPException(status_code=409, detail="Enrollment attempt is not awaiting a result")
    now = _utcnow()
    attempt.status = "client_confirmed"
    attempt.client_completed_at = attempt.client_completed_at or now
    attempt.result_generation = payload.generation
    attempt.result_config_sha256 = payload.config_sha256
    attempt.updated_at = now
    await db.commit()
    await db.refresh(attempt)
    response.headers.update(PRIVATE_HEADERS)
    return _attempt_response(attempt, device, policy)


@router.get("/api/terminal/enrollment/intents/{attempt_id}")
@limiter.limit("12/minute")
async def get_enrollment_intent(
    request: Request,
    response: Response,
    attempt_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    policy = await _policy()
    attempt, device = await _lock_owned_attempt_graph(db, user.id, attempt_id)
    await _expire_stale_attempt(db, attempt, device)
    await db.commit()
    await db.refresh(attempt)
    await db.refresh(device)
    response.headers.update(PRIVATE_HEADERS)
    return _attempt_response(attempt, device, policy)


@router.post("/api/terminal/enrollment/devices/{public_id}/revoke")
@limiter.limit("6/minute")
async def revoke_terminal_enrollment(
    request: Request,
    response: Response,
    public_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Idempotently revoke every scoped credential for one owned terminal."""
    _require_owner_mutation(request)
    device = await db.scalar(
        select(TerminalDevice)
        .where(
            TerminalDevice.public_id == public_id,
            TerminalDevice.user_id == user.id,
        )
        .with_for_update()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Terminal device not found")
    if device.enrollment_state == "legacy":
        raise HTTPException(status_code=409, detail="Terminal is not securely enrolled")
    if device.enrollment_state == "review":
        raise HTTPException(status_code=409, detail="Terminal identity requires operator review")

    attempts = list(
        (
            await db.scalars(
                select(TerminalEnrollmentAttempt)
                .where(TerminalEnrollmentAttempt.device_id == device.id)
                .order_by(TerminalEnrollmentAttempt.id)
                .with_for_update()
            )
        ).all()
    )
    credentials = list(
        (
            await db.scalars(
                select(TerminalDeviceCredential)
                .where(TerminalDeviceCredential.device_id == device.id)
                .order_by(TerminalDeviceCredential.id)
                .with_for_update()
            )
        ).all()
    )
    now = _utcnow()
    for attempt in attempts:
        if attempt.status in {"initialized", "issued", "client_confirmed"}:
            attempt.status = "superseded"
            attempt.updated_at = now
    for credential in credentials:
        if credential.state != "revoked":
            credential.state = "revoked"
            credential.revoked_at = now
            credential.updated_at = now
    device.enrollment_state = "revoked"
    device.enrollment_updated_at = now
    await db.commit()
    response.headers.update(PRIVATE_HEADERS)
    return {
        "schema_version": 1,
        "terminal_id": str(device.public_id),
        "enrollment_state": "revoked",
        "revoked_generations": len(credentials),
    }


async def _scoped_device(
    db: AsyncSession,
    *,
    public_id: UUID,
    credential_token: str,
    request: Request,
    variant_name: str | None,
) -> tuple[TerminalDevice, TerminalSettings, Any]:
    if TOKEN_RE.fullmatch(credential_token) is None:
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    token_hash = _hash_token(credential_token)
    locator = await db.execute(
        select(
            TerminalDevice.id,
            TerminalDevice.mac,
            TerminalDeviceCredential.id,
            TerminalDeviceCredential.state,
        )
        .join(TerminalDeviceCredential, TerminalDeviceCredential.device_id == TerminalDevice.id)
        .where(
            TerminalDevice.public_id == public_id,
            TerminalDeviceCredential.token_sha256 == token_hash,
            TerminalDeviceCredential.state.in_(("candidate", "active", "rollback")),
        )
    )
    located = locator.one_or_none()
    header_mac = _normalize_mac(request.headers.get("x-device-mac"))
    if located is None or header_mac is None or header_mac != located[1]:
        raise HTTPException(status_code=404, detail="Unknown terminal device")

    device = await db.scalar(
        select(TerminalDevice)
        .where(
            TerminalDevice.id == located[0],
            TerminalDevice.public_id == public_id,
        )
        .with_for_update()
    )
    if device is None or device.mac != header_mac:
        raise HTTPException(status_code=404, detail="Unknown terminal device")

    attempt = None
    if located[3] == "candidate":
        attempt = await db.scalar(
            select(TerminalEnrollmentAttempt)
            .where(
                TerminalEnrollmentAttempt.credential_id == located[2],
                TerminalEnrollmentAttempt.device_id == device.id,
                TerminalEnrollmentAttempt.status.in_(("issued", "client_confirmed")),
            )
            .with_for_update()
        )
    credentials = list(
        (
            await db.scalars(
                select(TerminalDeviceCredential)
                .where(TerminalDeviceCredential.device_id == device.id)
                .order_by(TerminalDeviceCredential.id)
                .with_for_update()
            )
        ).all()
    )
    credential = next(
        (
            item
            for item in credentials
            if item.id == located[2]
            and item.token_sha256 == token_hash
            and item.state in {"candidate", "active", "rollback"}
        ),
        None,
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Unknown terminal device")

    expected_variant = MODEL_VARIANT_QUERY.get(device.hardware_model or "")
    normalized_variant = (variant_name or "").strip().lower()
    if expected_variant is None or normalized_variant != expected_variant:
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    variant = parse_variant(normalized_variant)
    now = _utcnow()
    if credential.state == "candidate":
        if credential.created_at < now - CANDIDATE_LIFETIME:
            raise HTTPException(status_code=404, detail="Unknown terminal device")
        if (
            attempt is None
            or attempt.target_generation != credential.generation
            or attempt.config_sha256 != credential.config_sha256
        ):
            raise HTTPException(status_code=404, detail="Unknown terminal device")
        for prior in credentials:
            if prior.id == credential.id:
                continue
            if prior.state == "active":
                prior.state = "rollback"
                prior.updated_at = now
            elif prior.state in {"rollback", "candidate"}:
                prior.state = "revoked"
                prior.revoked_at = now
                prior.updated_at = now
        credential.state = "active"
        credential.activated_at = now
        credential.updated_at = now
        attempt.status = "activated"
        attempt.activated_at = now
        attempt.updated_at = now
        device.enrollment_state = "enrolled"
        device.enrollment_generation = credential.generation
        device.enrollment_config_sha256 = credential.config_sha256
        device.enrollment_release_id = attempt.firmware_release_id
        device.enrollment_key_id = attempt.enrollment_key_id
        device.enrollment_activated_at = now
        device.enrollment_updated_at = now
    elif credential.state == "active":
        if (
            device.enrollment_state != "enrolled"
            or device.enrollment_generation != credential.generation
            or device.enrollment_config_sha256 != credential.config_sha256
        ):
            raise HTTPException(status_code=404, detail="Unknown terminal device")
    else:
        active = next((item for item in credentials if item.state == "active"), None)
        if (
            device.enrollment_state != "enrolled"
            or device.enrollment_activated_at is None
            or device.enrollment_activated_at < now - ROLLBACK_LIFETIME
            or active is None
            or active.generation != device.enrollment_generation
            or active.config_sha256 != device.enrollment_config_sha256
            or credential.generation + 1 != active.generation
        ):
            raise HTTPException(status_code=404, detail="Unknown terminal device")

    device.last_secure_checkin_at = now
    credential.last_used_at = now
    credential.updated_at = now
    await _apply_device_telemetry(
        db,
        device=device,
        request=request,
        variant=variant,
        now=now,
    )
    settings_result = await db.execute(
        select(TerminalSettings).where(TerminalSettings.user_id == device.user_id)
    )
    terminal_settings = settings_result.scalar_one_or_none()
    if terminal_settings is None:
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    await db.commit()
    return device, terminal_settings, variant


@router.get("/terminal/device/{public_id}/{credential_token}/schedule.json")
@limiter.limit("60/minute")
async def scoped_terminal_schedule(
    request: Request,
    public_id: UUID,
    credential_token: str,
    variant: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    device, terminal_settings, resolved_variant = await _scoped_device(
        db,
        public_id=public_id,
        credential_token=credential_token,
        request=request,
        variant_name=variant,
    )
    body, image_etag = await _render_for_device(
        resolved_variant,
        device=device,
        settings=terminal_settings,
    )
    schedule_etag = '"sched-' + image_etag.strip('"').removeprefix("img-") + '"'
    headers = {**DEVICE_HEADERS, "ETag": schedule_etag}
    if (request.headers.get("if-none-match") or "").strip() == schedule_etag:
        return Response(status_code=304, headers=headers)
    now = _utcnow()
    interval = (
        max(30, min(int(device.refresh_interval_sec), 21_600))
        if device.refresh_interval_sec
        else max(30, int(resolved_variant.next_checkin_sec))
    )
    next_checkin_sec = aligned_next_checkin_sec(now, interval)
    image_url = f"/terminal/device/{public_id}/{credential_token}/image.bmp"
    if resolved_variant.query:
        image_url += f"?variant={resolved_variant.query}"
    return Response(
        content=json.dumps(
            {
                "schema_version": 1,
                "server_time_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "next_checkin_sec": next_checkin_sec,
                "next_checkin_utc": (now + timedelta(seconds=next_checkin_sec)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "variant": resolved_variant.query or "spectra6_800x480",
                "image": {
                    "url": image_url,
                    "etag": image_etag,
                    "format": resolved_variant.image_format,
                    "bytes": len(body),
                },
                "message": f"Hello {device.name}" if device.name else "Terminal ready",
            },
            separators=(",", ":"),
        ),
        media_type="application/json",
        headers=headers,
    )


@router.get("/terminal/device/{public_id}/{credential_token}/image.bmp")
@limiter.limit("60/minute")
async def scoped_terminal_image(
    request: Request,
    public_id: UUID,
    credential_token: str,
    variant: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    device, terminal_settings, resolved_variant = await _scoped_device(
        db,
        public_id=public_id,
        credential_token=credential_token,
        request=request,
        variant_name=variant,
    )
    body, etag = await _render_for_device(
        resolved_variant,
        device=device,
        settings=terminal_settings,
    )
    headers = {**DEVICE_HEADERS, "ETag": etag}
    if (request.headers.get("if-none-match") or "").strip() == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="image/bmp", headers=headers)
