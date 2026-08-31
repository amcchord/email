"""Default-locked owner and active-device terminal OTA control plane."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.terminal import (
    TerminalDevice,
    TerminalDeviceCredential,
    TerminalOtaAttempt,
    TerminalOtaEvent,
)
from backend.models.user import User
from backend.routers.auth import get_current_user, limiter
from backend.routers.terminal import _normalize_mac
from backend.routers.terminal_enrollment import (
    TOKEN_RE,
    _hash_token,
    _require_owner_mutation,
)
from backend.services.terminal.ota_control import (
    ACTIVE_ATTEMPT_STATES,
    OtaControlError,
    OtaReleaseUnavailable,
    apply_ota_telemetry,
    artifact_bytes,
    attempt_expiry,
    attempt_matches_release,
    build_offer,
    load_ota_release,
    offer_record,
    parse_ota_telemetry,
    request_fingerprint,
    require_fresh_power_reserve,
    require_rollout,
    transition_kind,
    validate_event_runtime,
)
from backend.services.terminal.ota_policy import OtaPolicyError, evaluate_ota_policy
from backend.services.terminal.ota_protocol import (
    AttemptState,
    OtaProtocolError,
    TransitionDecision,
    classify_transition,
    event_fingerprint,
    parse_event,
)

router = APIRouter(tags=["terminal-ota"])
settings = get_settings()

DEVICE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}
ACTIVE_STATES = tuple(ACTIVE_ATTEMPT_STATES)
TERMINAL_PROTOCOL_STATES = {
    AttemptState.SUCCEEDED,
    AttemptState.FAILED,
    AttemptState.ROLLED_BACK,
    AttemptState.RECOVERY_REQUIRED,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateOtaAttemptRequest(StrictModel):
    client_request_id: UUID
    release_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class CancelOtaAttemptRequest(StrictModel):
    reason: Literal["owner_cancelled"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _release_args(release_id: str) -> tuple[str, str, int, str]:
    return (
        settings.terminal_firmware_storage_path,
        settings.terminal_firmware_trusted_signing_keys,
        settings.terminal_firmware_minimum_catalog_generation,
        release_id,
    )


async def _loaded_release(release_id: str):
    try:
        return await run_in_threadpool(load_ota_release, *_release_args(release_id))
    except OtaReleaseUnavailable as exc:
        raise HTTPException(
            status_code=404, detail="Terminal OTA release not found"
        ) from exc


def _require_release_policy(loaded) -> None:
    policy = evaluate_ota_policy(
        settings,
        releases=(loaded.release,),
        event_persistence_ready=True,
    )
    try:
        policy.require_ready()
    except OtaPolicyError as exc:
        raise HTTPException(status_code=409, detail="Terminal OTA is locked") from exc


async def _lock_active_device(
    db: AsyncSession,
    *,
    public_id: UUID,
    credential_token: str,
    request: Request,
) -> tuple[TerminalDevice, TerminalDeviceCredential]:
    """Reuse the enrolled path secret, but accept only its active generation."""

    if TOKEN_RE.fullmatch(credential_token) is None:
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    header_mac = _normalize_mac(request.headers.get("x-device-mac"))
    if header_mac is None:
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    token_hash = _hash_token(credential_token)
    located = (
        await db.execute(
            select(TerminalDevice.id, TerminalDeviceCredential.id)
            .join(
                TerminalDeviceCredential,
                TerminalDeviceCredential.device_id == TerminalDevice.id,
            )
            .where(
                TerminalDevice.public_id == public_id,
                TerminalDevice.mac == header_mac,
                TerminalDevice.enrollment_state == "enrolled",
                TerminalDeviceCredential.token_sha256 == token_hash,
                TerminalDeviceCredential.state == "active",
            )
        )
    ).one_or_none()
    if located is None:
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    device = await db.scalar(
        select(TerminalDevice).where(TerminalDevice.id == located[0]).with_for_update()
    )
    if (
        device is None
        or device.mac != header_mac
        or device.enrollment_state != "enrolled"
    ):
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    credential = await db.scalar(
        select(TerminalDeviceCredential)
        .where(
            TerminalDeviceCredential.id == located[1],
            TerminalDeviceCredential.device_id == device.id,
            TerminalDeviceCredential.token_sha256 == token_hash,
            TerminalDeviceCredential.state == "active",
        )
        .with_for_update()
    )
    if (
        credential is None
        or credential.generation != device.enrollment_generation
        or credential.config_sha256 != device.enrollment_config_sha256
    ):
        raise HTTPException(status_code=404, detail="Unknown terminal device")
    return device, credential


async def _current_attempt(
    db: AsyncSession,
    *,
    device_id: int,
    credential_id: int,
    lock: bool = False,
) -> TerminalOtaAttempt | None:
    statement = select(TerminalOtaAttempt).where(
        TerminalOtaAttempt.device_id == device_id,
        TerminalOtaAttempt.credential_id == credential_id,
        TerminalOtaAttempt.state.in_(ACTIVE_STATES),
    )
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


def _expire_unstarted(attempt: TerminalOtaAttempt, now: datetime) -> bool:
    if attempt.state == AttemptState.OFFERED.value and attempt.expires_at <= now:
        attempt.state = "expired"
        attempt.terminal_at = now
        attempt.updated_at = now
        return True
    return False


async def schedule_offer(
    db: AsyncSession,
    *,
    public_id: UUID,
    credential_token: str,
    request: Request,
) -> dict[str, Any] | None:
    """Capture a coherent poll and return an optional already-accepted offer.

    Candidate/rollback credentials and old firmware still receive the ordinary
    schedule from the caller, but never an OTA object.
    """

    try:
        device, credential = await _lock_active_device(
            db,
            public_id=public_id,
            credential_token=credential_token,
            request=request,
        )
    except HTTPException:
        await db.rollback()
        return None
    now = _utcnow()
    try:
        telemetry = parse_ota_telemetry(request.headers, now=now)
    except OtaControlError:
        for field in (
            "last_ota_fw_version",
            "last_ota_build_id",
            "last_ota_partition",
            "last_ota_boot_count",
            "last_ota_battery_mv",
            "last_ota_battery_pct",
            "last_ota_external_power",
            "last_ota_telemetry_at",
        ):
            setattr(device, field, None)
    else:
        apply_ota_telemetry(device, telemetry)
    credential.last_used_at = now
    credential.updated_at = now
    attempt = await _current_attempt(
        db, device_id=device.id, credential_id=credential.id, lock=True
    )
    if attempt is None:
        await db.commit()
        return None
    if _expire_unstarted(attempt, now):
        await db.commit()
        return None
    attempt_id = attempt.id
    await db.commit()
    try:
        loaded = await _loaded_release(attempt.descriptor_release_id)
        _require_release_policy(loaded)
    except HTTPException:
        return None
    # Re-authenticate and re-lock after filesystem verification. A concurrent
    # owner cancel or credential revocation must make this poll omit the offer
    # rather than returning one stale schedule.
    try:
        device, credential = await _lock_active_device(
            db,
            public_id=public_id,
            credential_token=credential_token,
            request=request,
        )
    except HTTPException:
        await db.rollback()
        return None
    attempt = await db.scalar(
        select(TerminalOtaAttempt)
        .where(
            TerminalOtaAttempt.id == attempt_id,
            TerminalOtaAttempt.device_id == device.id,
            TerminalOtaAttempt.credential_id == credential.id,
            TerminalOtaAttempt.state.in_(ACTIVE_STATES),
        )
        .with_for_update()
    )
    if attempt is None or not attempt_matches_release(attempt, loaded):
        await db.rollback()
        return None
    record = offer_record(
        build_offer(
            attempt,
            public_id=public_id,
            credential_token=credential_token,
        )
    )
    await db.commit()
    return record


def _attempt_record(attempt: TerminalOtaAttempt) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "attempt_id": str(attempt.attempt_id),
        "offer_id": str(attempt.offer_id),
        "device_id": attempt.device_id,
        "state": attempt.state,
        "last_sequence": attempt.last_sequence,
        "has_event_gap": attempt.has_event_gap,
        "release_id": attempt.descriptor_release_id,
        "parent_release_id": attempt.parent_release_id,
        "signing_key_id": attempt.signing_key_id,
        "catalog_generation": attempt.catalog_generation,
        "device_model": attempt.device_model,
        "hardware_revision": attempt.hardware_revision,
        "layout": attempt.partition_layout,
        "target_version": attempt.target_version,
        "target_build_id": attempt.target_build_id,
        "source_version": attempt.source_version,
        "source_build_id": attempt.source_build_id,
        "source_partition": attempt.source_partition,
        "rollout_percentage": attempt.rollout_percentage,
        "cohort_bucket": attempt.cohort_bucket,
        "expires_at": attempt.expires_at,
        "terminal_at": attempt.terminal_at,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
    }


@router.post("/api/terminal/devices/{device_id}/ota/attempts", status_code=201)
@limiter.limit("12/minute")
async def create_ota_attempt(
    request: Request,
    device_id: int,
    payload: CreateOtaAttemptRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_mutation(request)
    fingerprint = request_fingerprint(
        device_id=device_id,
        release_id=payload.release_id,
        client_request_id=payload.client_request_id,
    )
    existing = await db.scalar(
        select(TerminalOtaAttempt).where(
            TerminalOtaAttempt.user_id == user.id,
            TerminalOtaAttempt.client_request_id == payload.client_request_id,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409, detail="Terminal OTA request conflicts"
            )
        response.status_code = 200
        response.headers.update(DEVICE_HEADERS)
        return _attempt_record(existing)

    loaded = await _loaded_release(payload.release_id)
    _require_release_policy(loaded)

    device = await db.scalar(
        select(TerminalDevice)
        .where(TerminalDevice.id == device_id, TerminalDevice.user_id == user.id)
        .with_for_update()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Terminal device not found")
    existing = await db.scalar(
        select(TerminalOtaAttempt)
        .where(
            TerminalOtaAttempt.user_id == user.id,
            TerminalOtaAttempt.client_request_id == payload.client_request_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409, detail="Terminal OTA request conflicts"
            )
        response.status_code = 200
        response.headers.update(DEVICE_HEADERS)
        return _attempt_record(existing)
    now = _utcnow()
    active = await db.scalar(
        select(TerminalOtaAttempt)
        .where(
            TerminalOtaAttempt.device_id == device.id,
            TerminalOtaAttempt.state.in_(ACTIVE_STATES),
        )
        .with_for_update()
    )
    if active is not None and not _expire_unstarted(active, now):
        raise HTTPException(
            status_code=409, detail="Terminal already has an active OTA attempt"
        )
    credential = await db.scalar(
        select(TerminalDeviceCredential)
        .where(
            TerminalDeviceCredential.device_id == device.id,
            TerminalDeviceCredential.state == "active",
            TerminalDeviceCredential.generation == device.enrollment_generation,
            TerminalDeviceCredential.config_sha256 == device.enrollment_config_sha256,
        )
        .with_for_update()
    )
    release = loaded.release
    if (
        device.enrollment_state != "enrolled"
        or credential is None
        or device.hardware_model != release.model
        or device.hardware_revision is None
        or device.hardware_revision_confirmed_at is None
        or device.hardware_revision not in release.parent.hardware_revisions
    ):
        raise HTTPException(
            status_code=409, detail="Terminal identity is not OTA qualified"
        )
    try:
        telemetry = require_fresh_power_reserve(device, settings, now=now)
        rollout_percentage, cohort_bucket = require_rollout(
            device.public_id, release.release_id, settings
        )
        expires_at = attempt_expiry(settings, now=now)
    except OtaControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if telemetry.build_id == release.parent.source_build_id:
        raise HTTPException(
            status_code=409, detail="Terminal already runs this OTA build"
        )

    attempt = TerminalOtaAttempt(
        user_id=user.id,
        device_id=device.id,
        credential_id=credential.id,
        client_request_id=payload.client_request_id,
        request_fingerprint=fingerprint,
        state=AttemptState.OFFERED.value,
        last_sequence=0,
        has_event_gap=False,
        descriptor_release_id=release.release_id,
        parent_release_id=release.parent.release_id,
        signing_key_id=release.signing_key_id,
        catalog_generation=loaded.catalog_generation,
        device_model=release.model,
        hardware_revision=device.hardware_revision,
        partition_layout=release.layout,
        target_version=release.version,
        target_build_id=release.parent.source_build_id,
        firmware_size=release.firmware_size,
        firmware_sha256=release.firmware_sha256,
        descriptor_signature_sha256=loaded.descriptor_signature_sha256,
        source_version=telemetry.firmware_version,
        source_build_id=telemetry.build_id,
        source_partition=telemetry.running_partition,
        source_boot_count=telemetry.boot_count,
        offered_battery_mv=telemetry.battery_mv,
        offered_battery_pct=telemetry.battery_pct,
        offered_external_power=telemetry.external_power,
        rollout_percentage=rollout_percentage,
        cohort_bucket=cohort_bucket,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    db.add(attempt)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        winner = await db.scalar(
            select(TerminalOtaAttempt).where(
                TerminalOtaAttempt.user_id == user.id,
                TerminalOtaAttempt.client_request_id == payload.client_request_id,
            )
        )
        if winner is not None and winner.request_fingerprint == fingerprint:
            response.status_code = 200
            response.headers.update(DEVICE_HEADERS)
            return _attempt_record(winner)
        raise HTTPException(
            status_code=409, detail="Terminal OTA attempt conflicts"
        ) from exc
    await db.refresh(attempt)
    response.headers.update(DEVICE_HEADERS)
    return _attempt_record(attempt)


@router.get("/api/terminal/devices/{device_id}/ota/attempts")
async def list_ota_attempts(
    device_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    device = await db.scalar(
        select(TerminalDevice).where(
            TerminalDevice.id == device_id, TerminalDevice.user_id == user.id
        )
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Terminal device not found")
    attempts = list(
        (
            await db.scalars(
                select(TerminalOtaAttempt)
                .where(TerminalOtaAttempt.device_id == device.id)
                .order_by(TerminalOtaAttempt.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    response.headers.update(DEVICE_HEADERS)
    return [_attempt_record(attempt) for attempt in attempts]


@router.get("/api/terminal/ota/attempts/{attempt_id}")
async def get_ota_attempt(
    attempt_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    attempt = await db.scalar(
        select(TerminalOtaAttempt).where(
            TerminalOtaAttempt.attempt_id == attempt_id,
            TerminalOtaAttempt.user_id == user.id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Terminal OTA attempt not found")
    response.headers.update(DEVICE_HEADERS)
    return _attempt_record(attempt)


@router.post("/api/terminal/ota/attempts/{attempt_id}/cancel")
@limiter.limit("12/minute")
async def cancel_ota_attempt(
    request: Request,
    attempt_id: UUID,
    payload: CancelOtaAttemptRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner_mutation(request)
    device_id = await db.scalar(
        select(TerminalOtaAttempt.device_id).where(
            TerminalOtaAttempt.attempt_id == attempt_id,
            TerminalOtaAttempt.user_id == user.id,
        )
    )
    if device_id is None:
        raise HTTPException(status_code=404, detail="Terminal OTA attempt not found")
    device = await db.scalar(
        select(TerminalDevice)
        .where(TerminalDevice.id == device_id, TerminalDevice.user_id == user.id)
        .with_for_update()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Terminal OTA attempt not found")
    attempt = await db.scalar(
        select(TerminalOtaAttempt)
        .where(
            TerminalOtaAttempt.attempt_id == attempt_id,
            TerminalOtaAttempt.user_id == user.id,
        )
        .with_for_update()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Terminal OTA attempt not found")
    if attempt.state == "cancelled":
        response.headers.update(DEVICE_HEADERS)
        return _attempt_record(attempt)
    if attempt.state != AttemptState.OFFERED.value or attempt.last_sequence != 0:
        raise HTTPException(
            status_code=409, detail="Started OTA attempts cannot be cancelled"
        )
    now = _utcnow()
    attempt.state = "cancelled"
    attempt.terminal_at = now
    attempt.updated_at = now
    await db.commit()
    response.headers.update(DEVICE_HEADERS)
    return _attempt_record(attempt)


async def _attempt_for_artifact(
    db: AsyncSession,
    *,
    device: TerminalDevice,
    credential: TerminalDeviceCredential,
    release_id: str,
) -> TerminalOtaAttempt:
    attempt = await db.scalar(
        select(TerminalOtaAttempt)
        .where(
            TerminalOtaAttempt.device_id == device.id,
            TerminalOtaAttempt.credential_id == credential.id,
            TerminalOtaAttempt.descriptor_release_id == release_id,
            TerminalOtaAttempt.state.in_(ACTIVE_STATES),
        )
        .with_for_update()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Terminal OTA artifact not found")
    if _expire_unstarted(attempt, _utcnow()):
        await db.commit()
        raise HTTPException(status_code=404, detail="Terminal OTA artifact not found")
    return attempt


@router.get(
    "/terminal/device/{public_id}/{credential_token}/firmware/{release_id}/{kind}"
)
@limiter.limit("120/minute")
async def terminal_ota_artifact(
    request: Request,
    public_id: UUID,
    credential_token: str,
    release_id: str,
    kind: Literal["manifest.json", "manifest.sig", "application.bin"],
    db: AsyncSession = Depends(get_db),
):
    device, credential = await _lock_active_device(
        db,
        public_id=public_id,
        credential_token=credential_token,
        request=request,
    )
    attempt = await _attempt_for_artifact(
        db,
        device=device,
        credential=credential,
        release_id=release_id,
    )
    loaded = await _loaded_release(release_id)
    _require_release_policy(loaded)
    if not attempt_matches_release(attempt, loaded):
        raise HTTPException(status_code=404, detail="Terminal OTA artifact not found")
    raw, media_type = artifact_bytes(loaded, kind)
    credential.last_used_at = _utcnow()
    credential.updated_at = credential.last_used_at
    await db.commit()
    return Response(
        content=raw,
        media_type=media_type,
        headers={
            **DEVICE_HEADERS,
            "Content-Length": str(len(raw)),
            "ETag": f'"sha256:{hashlib.sha256(raw).hexdigest()}"',
        },
    )


async def _bounded_body(request: Request, maximum: int = 2048) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > maximum:
            raise HTTPException(
                status_code=413, detail="Terminal OTA event is too large"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/terminal/device/{public_id}/{credential_token}/firmware/events")
@limiter.limit("120/minute")
async def terminal_ota_event(
    request: Request,
    public_id: UUID,
    credential_token: str,
    db: AsyncSession = Depends(get_db),
):
    raw = await _bounded_body(request)
    try:
        event = parse_event(raw)
    except OtaProtocolError as exc:
        raise HTTPException(
            status_code=400, detail="Terminal OTA event is invalid"
        ) from exc
    device, credential = await _lock_active_device(
        db,
        public_id=public_id,
        credential_token=credential_token,
        request=request,
    )
    attempt = await db.scalar(
        select(TerminalOtaAttempt)
        .where(
            TerminalOtaAttempt.attempt_id == UUID(event.attempt_id),
            TerminalOtaAttempt.device_id == device.id,
            TerminalOtaAttempt.credential_id == credential.id,
        )
        .with_for_update()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Terminal OTA attempt not found")
    fingerprint = event_fingerprint(event)
    existing = await db.scalar(
        select(TerminalOtaEvent).where(
            TerminalOtaEvent.event_id == UUID(event.event_id)
        )
    )
    if existing is not None:
        if (
            existing.attempt_row_id != attempt.id
            or existing.payload_sha256 != fingerprint
        ):
            raise HTTPException(status_code=409, detail="Terminal OTA event conflicts")
        return Response(
            content=(
                f'{{"schema_version":1,"event_id":"{event.event_id}",'
                f'"state":"{attempt.state}","idempotent":true}}'
            ),
            media_type="application/json",
            headers=DEVICE_HEADERS,
        )
    if (
        attempt.state == AttemptState.OFFERED.value
        and attempt.last_sequence == 0
        and attempt.expires_at <= _utcnow()
    ):
        now = _utcnow()
        attempt.state = "expired"
        attempt.terminal_at = now
        attempt.updated_at = now
        await db.commit()
        raise HTTPException(status_code=409, detail="Terminal OTA offer has expired")
    if (
        str(attempt.offer_id) != event.offer_id
        or attempt.descriptor_release_id != event.release_id
        or attempt.state not in ACTIVE_ATTEMPT_STATES
    ):
        raise HTTPException(
            status_code=409, detail="Terminal OTA event binding is invalid"
        )
    decision = classify_transition(
        AttemptState(attempt.state),
        attempt.last_sequence,
        event.state,
        event.sequence,
    )
    if decision is TransitionDecision.REJECT:
        raise HTTPException(
            status_code=409, detail="Terminal OTA event transition is invalid"
        )
    try:
        validate_event_runtime(attempt, event)
        kind = transition_kind(decision)
    except OtaControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    now = _utcnow()
    db.add(
        TerminalOtaEvent(
            event_id=UUID(event.event_id),
            attempt_row_id=attempt.id,
            sequence=event.sequence,
            schema_version=event.schema_version,
            payload_sha256=fingerprint,
            transition_kind=kind,
            state=event.state.value,
            running_version=event.running_version,
            running_build_id=event.running_build_id,
            running_partition=event.running_partition,
            boot_count=event.boot_count,
            reset_reason=event.reset_reason,
            error_code=event.error_code,
            received_at=now,
        )
    )
    attempt.state = event.state.value
    attempt.last_sequence = event.sequence
    attempt.has_event_gap = attempt.has_event_gap or (
        decision is TransitionDecision.ADVANCE_WITH_GAP
    )
    attempt.updated_at = now
    if event.state in TERMINAL_PROTOCOL_STATES:
        attempt.terminal_at = now
    credential.last_used_at = now
    credential.updated_at = now
    try:
        await db.commit()
    except IntegrityError as exc:
        attempt_row_id = attempt.id
        await db.rollback()
        winner = await db.scalar(
            select(TerminalOtaEvent).where(
                TerminalOtaEvent.event_id == UUID(event.event_id)
            )
        )
        if (
            winner is not None
            and winner.attempt_row_id == attempt_row_id
            and winner.payload_sha256 == fingerprint
        ):
            projected = await db.get(TerminalOtaAttempt, attempt_row_id)
            return Response(
                content=(
                    f'{{"schema_version":1,"event_id":"{event.event_id}",'
                    f'"state":"{projected.state}","idempotent":true}}'
                ),
                media_type="application/json",
                headers=DEVICE_HEADERS,
            )
        raise HTTPException(
            status_code=409, detail="Terminal OTA event conflicts"
        ) from exc
    return Response(
        status_code=201,
        content=(
            f'{{"schema_version":1,"event_id":"{event.event_id}",'
            f'"state":"{attempt.state}","idempotent":false}}'
        ),
        media_type="application/json",
        headers=DEVICE_HEADERS,
    )
