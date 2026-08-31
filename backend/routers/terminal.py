"""Public e-ink terminal endpoints.

Implements the wire protocol from `docs/terminal/`:
- `GET /terminal/{code}/schedule.json` -- check-in metadata
- `GET /terminal/{code}/image.bmp`     -- pre-dithered BMP for the device's panel

Firmware auth = the per-user short `code` in the path. Browser displays use a
separate credential bound to one catalog view. Devices auto-register on first
check-in via `X-Device-MAC`. Per the docs, missing `X-*` headers are treated as
'unknown' rather than 4xx'd.
"""
from __future__ import annotations

import logging
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.config import get_settings
from backend.models.terminal import (
    TerminalBatterySample,
    TerminalDevice,
    TerminalSettings,
    TerminalWebDisplay,
)
from backend.services.terminal.battery import (
    BATTERY_RETENTION,
    normalize_battery_telemetry,
    should_record_sample,
)
from backend.services.terminal.catalog import (
    CatalogError,
    resolve_design,
    resolve_profile,
    resolve_view,
    validate_catalog_content_implementations,
)
from backend.services.terminal.renderer import (
    render_bmp,
    render_dashboard_bmp,
    render_day_ahead_bmp,
)
from backend.services.terminal.legacy_ota import (
    LegacyOtaUnavailable,
    artifact_bytes as legacy_ota_artifact_bytes,
    load_current_release as load_current_legacy_ota_release,
    load_release as load_legacy_ota_release,
    offer_record as legacy_ota_offer_record,
    record_event as record_legacy_ota_event,
)
from backend.services.terminal.ota_control import (
    OtaControlError,
    apply_ota_telemetry,
    parse_ota_telemetry,
)
from backend.services.terminal.variants import (
    Variant,
    aligned_next_checkin_sec,
    parse_variant,
)
from backend.services.terminal.web_display import build_display_html, render_web_frame

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])
app_settings = get_settings()


# ── Header parsing helpers ──────────────────────────────────────────


def _safe_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def _normalize_mac(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip().lower()
    # Accept colon-separated; reject anything obviously wrong but don't 4xx.
    if len(raw) != 17 or raw.count(":") != 5:
        return None
    return raw


async def _resolve_settings(db: AsyncSession, code: str) -> TerminalSettings:
    if not code or len(code) > 32:
        raise HTTPException(status_code=404, detail="Unknown terminal code")
    result = await db.execute(
        select(TerminalSettings).where(TerminalSettings.code == code)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        raise HTTPException(status_code=404, detail="Unknown terminal code")
    return settings


def _resolve_bound_web_request(display: TerminalWebDisplay):
    try:
        resolved_profile = resolve_profile(display.profile_key)
        resolved_view = resolve_view(display.view_key, profile=resolved_profile)
        resolved_design = resolve_design(
            resolved_view,
            display.design_key or None,
        )
    except CatalogError as exc:
        logger.warning(
            "Invalid catalog binding for terminal_web_display id=%s: %s",
            display.id,
            exc,
        )
        raise HTTPException(status_code=404, detail="Unknown browser display") from exc
    return resolved_view, resolved_design, resolved_profile


async def _resolve_web_display(
    db: AsyncSession,
    token: str,
) -> tuple[TerminalSettings, TerminalWebDisplay]:
    if not token or len(token) < 20 or len(token) > 64:
        raise HTTPException(status_code=404, detail="Unknown browser display")
    result = await db.execute(
        select(TerminalWebDisplay).where(TerminalWebDisplay.token == token)
    )
    display = result.scalar_one_or_none()
    if display is None:
        raise HTTPException(status_code=404, detail="Unknown browser display")
    settings_result = await db.execute(
        select(TerminalSettings).where(TerminalSettings.user_id == display.user_id)
    )
    settings = settings_result.scalar_one_or_none()
    if settings is None:
        raise HTTPException(status_code=404, detail="Unknown browser display")
    return settings, display


async def _upsert_device(
    db: AsyncSession,
    *,
    user_id: int,
    request: Request,
    variant: Variant,
    image_etag: Optional[str] = None,
) -> Optional[TerminalDevice]:
    """Best-effort legacy-device upsert. Returns ``None`` when MAC is unusable.

    An enrolled, revoked, or review-held MAC is never resolved through the
    shared per-user code again. During an owner-scoped pending enrollment, the
    same owner's legacy URL remains usable so an interrupted serial write does
    not strand the terminal. Another user's shared code still cannot claim it.
    """
    h = request.headers
    mac = _normalize_mac(h.get("x-device-mac"))
    if not mac:
        return None

    result = await db.execute(
        select(TerminalDevice).where(TerminalDevice.mac == mac)
    )
    devices = list(result.scalars().all())
    if any(
        device.enrollment_state in {"enrolled", "revoked", "review"}
        or (device.enrollment_state == "pending" and device.user_id != user_id)
        for device in devices
    ):
        return None
    device = next((device for device in devices if device.user_id == user_id), None)
    now = datetime.now(timezone.utc)

    if device is None:
        device = TerminalDevice(
            user_id=user_id,
            mac=mac,
            name=f"Terminal {mac[-5:].replace(':', '')}",
            variant=variant.key,
            content_type="clock",
            last_seen_at=now,
            created_at=now,
        )
        db.add(device)

    if variant.key == "bw":
        device.hardware_model = "E1001"
    elif variant.key == "spectra6_800x480":
        device.hardware_model = "E1002"

    await _apply_device_telemetry(
        db,
        device=device,
        request=request,
        variant=variant,
        now=now,
        image_etag=image_etag,
    )

    try:
        await db.commit()
        await db.refresh(device)
    except Exception:
        logger.exception("Failed to upsert terminal device telemetry")
        await db.rollback()
        return None
    return device


async def _apply_device_telemetry(
    db: AsyncSession,
    *,
    device: TerminalDevice,
    request: Request,
    variant: Variant,
    now: datetime | None = None,
    image_etag: Optional[str] = None,
) -> None:
    """Apply one terminal request's bounded telemetry without committing.

    Secure enrollment needs telemetry and credential activation to share one
    database transaction. Legacy callers retain their previous behavior by
    committing immediately after this helper returns.
    """
    h = request.headers
    now = now or datetime.now(timezone.utc)
    device.variant = variant.key
    device.last_seen_at = now
    device.last_wake_reason = (h.get("x-wake-reason") or "").strip()[:32] or device.last_wake_reason
    battery_mv, battery_pct = normalize_battery_telemetry(
        battery_mv=_safe_int(h.get("x-battery-mv")),
        battery_pct=_safe_int(h.get("x-battery-pct")),
        measurement_valid=_safe_int(h.get("x-battery-valid")),
    )
    rssi_dbm = _safe_int(h.get("x-rssi-dbm"))
    uptime_sec = _safe_int(h.get("x-uptime-sec"))
    boot_count = _safe_int(h.get("x-boot-count"))
    if battery_mv is not None:
        device.last_battery_mv = battery_mv
    if battery_pct is not None:
        device.last_battery_pct = battery_pct
    if rssi_dbm is not None:
        device.last_rssi_dbm = rssi_dbm
    if uptime_sec is not None:
        device.last_uptime_sec = uptime_sec
    if boot_count is not None:
        device.last_boot_count = boot_count
    fw = (h.get("x-fw-version") or "").strip()
    if fw:
        device.last_fw_version = fw[:64]
    if h.get("x-firmware-build-id"):
        try:
            apply_ota_telemetry(device, parse_ota_telemetry(h, now=now))
        except OtaControlError:
            logger.warning("Ignoring invalid legacy OTA telemetry for device_id=%s", device.id)
    if image_etag:
        device.last_image_etag = image_etag[:128]

    # Flush first so a newly auto-registered device has an id. Battery
    # sampling is deliberately sparse: meaningful changes plus a six-hour
    # heartbeat, never duplicate schedule/image requests seconds apart.
    await db.flush()
    if battery_pct is not None or battery_mv is not None:
        sample_result = await db.execute(
            select(TerminalBatterySample)
            .where(TerminalBatterySample.device_id == device.id)
            .order_by(TerminalBatterySample.observed_at.desc())
            .limit(1)
        )
        latest_sample = sample_result.scalar_one_or_none()
        if should_record_sample(
            latest_sample,
            observed_at=now,
            battery_pct=battery_pct,
            battery_mv=battery_mv,
        ):
            db.add(
                TerminalBatterySample(
                    device_id=device.id,
                    observed_at=now,
                    battery_pct=battery_pct,
                    battery_mv=battery_mv,
                    boot_count=boot_count,
                )
            )
            # The five-minute ingestion floor bounds short-term growth;
            # this per-device cleanup bounds it over the long term.
            await db.execute(
                delete(TerminalBatterySample).where(
                    TerminalBatterySample.device_id == device.id,
                    TerminalBatterySample.observed_at < now - BATTERY_RETENTION,
                )
            )


# ── Endpoints ───────────────────────────────────────────────────────


DeviceRenderer = Callable[
    [Variant, Optional[TerminalDevice], TerminalSettings],
    Awaitable[tuple[bytes, str]],
]


async def _render_dashboard_for_device(
    variant: Variant,
    device: Optional[TerminalDevice],
    settings: TerminalSettings,
) -> tuple[bytes, str]:
    return await render_dashboard_bmp(variant, device=device, settings=settings)


async def _render_day_ahead_for_device(
    variant: Variant,
    device: Optional[TerminalDevice],
    settings: TerminalSettings,
) -> tuple[bytes, str]:
    return await render_day_ahead_bmp(variant, device=device, settings=settings)


async def _render_clock_for_device(
    variant: Variant,
    device: Optional[TerminalDevice],
    settings: TerminalSettings,
) -> tuple[bytes, str]:
    device_name = (device.name if device else "") or ""
    return render_bmp(
        variant,
        device_name=device_name,
        tz_name=settings.timezone or "UTC",
    )


DEVICE_RENDERERS: dict[str, DeviceRenderer] = {
    "eink_dashboard": _render_dashboard_for_device,
    "day_ahead": _render_day_ahead_for_device,
    "clock": _render_clock_for_device,
}

validate_catalog_content_implementations(DEVICE_RENDERERS, surface="device")


async def _render_for_device(
    variant: Variant,
    *,
    device: Optional[TerminalDevice],
    settings: TerminalSettings,
) -> tuple[bytes, str]:
    """Dispatch to the right renderer based on device.content_type.

    Defaults to the placeholder clock when no device is known yet (first
    check-in with no MAC) or when the content type isn't recognised.
    """
    content_type = (device.content_type if device else None) or "clock"
    renderer = DEVICE_RENDERERS.get(content_type, _render_clock_for_device)
    try:
        return await renderer(variant, device, settings)
    except Exception:
        logger.exception(
            "%s render failed; falling back to clock for device_id=%s",
            content_type,
            getattr(device, "id", None),
        )
        return await _render_clock_for_device(variant, device, settings)


@router.get("/{code}/schedule.json")
async def schedule(
    code: str,
    request: Request,
    response: Response,
    variant: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Check-in metadata. See docs/terminal/server-protocol.md Â§4."""
    settings = await _resolve_settings(db, code)
    v = parse_variant(variant)

    device = await _upsert_device(
        db, user_id=settings.user_id, request=request, variant=v
    )

    # Render the canonical frame (its hash is the ETag the firmware compares).
    body, image_etag = await _render_for_device(v, device=device, settings=settings)
    bytes_total = len(body)

    firmware_offer = None
    model = (
        "E1001"
        if v.key == "bw"
        else "E1002"
        if v.key == "spectra6_800x480"
        else None
    )
    if device is not None and model is not None:
        try:
            release = await run_in_threadpool(
                load_current_legacy_ota_release,
                app_settings.terminal_firmware_storage_path,
                model,
                str(device.public_id),
            )
            if (
                release is not None
                and device.last_ota_telemetry_at is not None
                and device.last_ota_telemetry_at
                >= datetime.now(timezone.utc) - timedelta(minutes=5)
                and (device.last_ota_battery_mv or 0) >= 4000
                and (device.last_ota_battery_pct or 0) >= 80
            ):
                firmware_offer = legacy_ota_offer_record(
                    release,
                    schedule_code=code,
                    device_public_id=str(device.public_id),
                    running_version=(request.headers.get("x-fw-version") or "").strip(),
                )
        except LegacyOtaUnavailable:
            logger.exception("Ignoring invalid legacy OTA channel for model=%s", model)

    schedule_identity = image_etag.strip('"').removeprefix("img-")
    if firmware_offer is not None:
        schedule_identity += "-ota-" + hashlib.sha256(
            json.dumps(firmware_offer, separators=(",", ":")).encode("ascii")
        ).hexdigest()
    schedule_etag = '"sched-' + schedule_identity + '"'

    inm = (request.headers.get("if-none-match") or "").strip()
    if inm and inm == schedule_etag:
        response.headers["ETag"] = schedule_etag
        response.headers["Cache-Control"] = "private, no-cache"
        return Response(status_code=304, headers=response.headers)

    now = datetime.now(timezone.utc)
    # Per-device cadence override beats the variant baseline. Clamp to
    # [30s, 6h] so a buggy/old override never wedges or wakes the device.
    if device and device.refresh_interval_sec:
        interval = max(30, min(int(device.refresh_interval_sec), 21600))
    else:
        interval = max(30, int(v.next_checkin_sec))
    # Align the next wake to the wall clock (UTC) so e.g. hourly lands on :00
    # and 15-min lands on :00/:15/:30/:45 instead of drifting off boot time.
    # The first value after boot is therefore a partial interval.
    next_checkin_sec = aligned_next_checkin_sec(now, interval)
    next_at = now + timedelta(seconds=next_checkin_sec)

    image_url = f"/terminal/{code}/image.bmp"
    if v.query:
        image_url = f"{image_url}?variant={v.query}"

    payload = {
        "schema_version": 1,
        "server_time_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "next_checkin_sec": next_checkin_sec,
        "next_checkin_utc": next_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variant": v.query or "spectra6_800x480",
        "image": {
            "url": image_url,
            "etag": image_etag,
            "format": v.image_format,
            "bytes": bytes_total,
        },
        "message": (
            f"Hello {device.name}" if device and device.name else "Welcome new device"
        ),
    }
    if firmware_offer is not None:
        payload["firmware"] = firmware_offer

    response.headers["ETag"] = schedule_etag
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return payload


def _legacy_ota_model(request: Request) -> str | None:
    agent = (request.headers.get("user-agent") or "").lower()
    if agent.startswith("reterminale1001/"):
        return "E1001"
    if agent.startswith("reterminale1002/"):
        return "E1002"
    return None


async def _resolve_legacy_ota_device(
    db: AsyncSession,
    *,
    settings: TerminalSettings,
    request: Request,
    model: str,
) -> TerminalDevice:
    mac = _normalize_mac(request.headers.get("x-device-mac"))
    if mac is None:
        raise HTTPException(status_code=404, detail="Terminal firmware not found")
    device = await db.scalar(
        select(TerminalDevice).where(
            TerminalDevice.user_id == settings.user_id,
            TerminalDevice.mac == mac,
            TerminalDevice.enrollment_state == "legacy",
            TerminalDevice.hardware_model == model,
        )
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Terminal firmware not found")
    return device


@router.get("/{code}/firmware/{release_id}/{kind}")
async def legacy_ota_artifact(
    code: str,
    release_id: str,
    kind: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    settings = await _resolve_settings(db, code)
    model = _legacy_ota_model(request)
    if model is None:
        raise HTTPException(status_code=404, detail="Terminal firmware not found")
    device = await _resolve_legacy_ota_device(
        db, settings=settings, request=request, model=model
    )
    try:
        current = await run_in_threadpool(
            load_current_legacy_ota_release,
            app_settings.terminal_firmware_storage_path,
            model,
            str(device.public_id),
        )
        if current is None or current.release_id != release_id:
            raise LegacyOtaUnavailable("release is not active for this terminal")
        release = await run_in_threadpool(
            load_legacy_ota_release,
            app_settings.terminal_firmware_storage_path,
            model,
            release_id,
        )
        raw, media_type = legacy_ota_artifact_bytes(release, kind)
    except LegacyOtaUnavailable as exc:
        raise HTTPException(status_code=404, detail="Terminal firmware not found") from exc
    return Response(
        content=raw,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Length": str(len(raw)),
            "ETag": f'"sha256:{hashlib.sha256(raw).hexdigest()}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{code}/firmware/events")
async def legacy_ota_event_sink(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    settings = await _resolve_settings(db, code)
    model = _legacy_ota_model(request)
    if model is None:
        raise HTTPException(status_code=404, detail="Terminal OTA attempt not found")
    device = await _resolve_legacy_ota_device(
        db, settings=settings, request=request, model=model
    )
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > 2048:
            raise HTTPException(status_code=413, detail="Terminal OTA event is too large")
        chunks.append(chunk)
    try:
        release = await run_in_threadpool(
            load_current_legacy_ota_release,
            app_settings.terminal_firmware_storage_path,
            model,
            str(device.public_id),
        )
        if release is None:
            raise LegacyOtaUnavailable("no release is active for this terminal")
        state, idempotent = await run_in_threadpool(
            record_legacy_ota_event,
            app_settings.terminal_firmware_storage_path,
            release,
            schedule_code=code,
            device_public_id=str(device.public_id),
            raw=b"".join(chunks),
        )
    except LegacyOtaUnavailable as exc:
        raise HTTPException(status_code=409, detail="Terminal OTA event rejected") from exc
    return Response(
        content=json.dumps(
            {"schema_version": 1, "state": state, "idempotent": idempotent},
            separators=(",", ":"),
        ),
        media_type="application/json",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{code}/image.bmp")
async def image_bmp(
    code: str,
    request: Request,
    variant: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """The pre-dithered BMP for the device's panel."""
    settings = await _resolve_settings(db, code)
    v = parse_variant(variant)

    device = await _upsert_device(
        db, user_id=settings.user_id, request=request, variant=v
    )
    body, etag = await _render_for_device(v, device=device, settings=settings)
    if device and etag != device.last_image_etag:
        device.last_image_etag = etag[:128]
        try:
            await db.commit()
        except Exception:
            logger.exception("Failed to persist last_image_etag")
            await db.rollback()

    inm = (request.headers.get("if-none-match") or "").strip()
    if inm and inm == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "private, no-cache",
            },
        )

    headers = {
        "Content-Type": "image/bmp",
        "Content-Length": str(len(body)),
        "ETag": etag,
        "Cache-Control": "private, no-cache",
    }
    return Response(content=body, status_code=200, headers=headers, media_type="image/bmp")


@router.get("/display/{token}.html", response_class=HTMLResponse)
async def display_html(
    token: str,
    refresh: int = 300,
    db: AsyncSession = Depends(get_db),
):
    """Fullscreen At a Glance page for browser-powered 16:9/9:16 displays."""
    _settings, display = await _resolve_web_display(db, token)
    resolved_view, resolved_design, resolved_profile = _resolve_bound_web_request(
        display
    )
    refresh_sec = max(30, min(int(refresh), 3600))
    body = build_display_html(
        token=token,
        view=resolved_view,
        design=resolved_design,
        profile=resolved_profile,
        refresh_sec=refresh_sec,
    )
    return HTMLResponse(
        content=body,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'"
            ),
        },
    )


@router.get("/display/{token}/frame.png")
async def display_frame_png(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """PNG frame used by browser displays, generated by the panel renderer."""
    settings, display = await _resolve_web_display(db, token)
    resolved_view, resolved_design, resolved_profile = _resolve_bound_web_request(
        display
    )
    frame = await render_web_frame(
        settings=settings,
        view=resolved_view,
        design=resolved_design,
        profile=resolved_profile,
    )
    headers = {
        "ETag": frame.etag,
        "Cache-Control": "private, no-cache",
        "X-Frame-Width": str(frame.width),
        "X-Frame-Height": str(frame.height),
    }
    if (request.headers.get("if-none-match") or "").strip() == frame.etag:
        return Response(status_code=304, headers=headers)
    return Response(content=frame.body, media_type="image/png", headers=headers)
