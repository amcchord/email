"""Public e-ink terminal endpoints.

Implements the wire protocol from `docs/terminal/`:
- `GET /terminal/{code}/schedule.json` -- check-in metadata
- `GET /terminal/{code}/image.bmp`     -- pre-dithered BMP for the device's panel

Auth = the per-user short `code` in the path. Devices auto-register on first
check-in via `X-Device-MAC`. Per the docs, missing `X-*` headers are treated
as 'unknown' rather than 4xx'd.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.terminal import TerminalDevice, TerminalSettings
from backend.services.terminal.renderer import render_bmp, render_dashboard_bmp
from backend.services.terminal.variants import Variant, parse_variant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])


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


async def _upsert_device(
    db: AsyncSession,
    *,
    user_id: int,
    request: Request,
    variant: Variant,
    image_etag: Optional[str] = None,
) -> Optional[TerminalDevice]:
    """Best-effort upsert of telemetry. Returns None when no usable MAC."""
    h = request.headers
    mac = _normalize_mac(h.get("x-device-mac"))
    if not mac:
        return None

    result = await db.execute(
        select(TerminalDevice).where(
            TerminalDevice.user_id == user_id,
            TerminalDevice.mac == mac,
        )
    )
    device = result.scalar_one_or_none()
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

    device.variant = variant.key
    device.last_seen_at = now
    device.last_wake_reason = (h.get("x-wake-reason") or "").strip()[:32] or device.last_wake_reason
    device.last_battery_mv = _safe_int(h.get("x-battery-mv")) or device.last_battery_mv
    device.last_battery_pct = _safe_int(h.get("x-battery-pct")) or device.last_battery_pct
    device.last_rssi_dbm = _safe_int(h.get("x-rssi-dbm")) or device.last_rssi_dbm
    device.last_uptime_sec = _safe_int(h.get("x-uptime-sec")) or device.last_uptime_sec
    device.last_boot_count = _safe_int(h.get("x-boot-count")) or device.last_boot_count
    fw = (h.get("x-fw-version") or "").strip()
    if fw:
        device.last_fw_version = fw[:64]
    if image_etag:
        device.last_image_etag = image_etag[:128]

    try:
        await db.commit()
        await db.refresh(device)
    except Exception:
        logger.exception("Failed to upsert terminal device telemetry")
        await db.rollback()
        return None
    return device


# ── Endpoints ───────────────────────────────────────────────────────


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
    tz_name = settings.timezone or "UTC"
    content_type = (device.content_type if device else None) or "clock"
    device_name = (device.name if device else "") or ""
    if content_type == "eink_dashboard":
        try:
            return await render_dashboard_bmp(variant, device=device, settings=settings)
        except Exception:
            logger.exception(
                "eink_dashboard render failed; falling back to clock for device_id=%s",
                getattr(device, "id", None),
            )
            return render_bmp(variant, device_name=device_name, tz_name=tz_name)
    return render_bmp(variant, device_name=device_name, tz_name=tz_name)


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

    schedule_etag = '"sched-' + image_etag.strip('"').removeprefix("img-") + '"'

    inm = (request.headers.get("if-none-match") or "").strip()
    if inm and inm == schedule_etag:
        response.headers["ETag"] = schedule_etag
        response.headers["Cache-Control"] = "no-cache"
        return Response(status_code=304, headers=response.headers)

    now = datetime.now(timezone.utc)
    # Per-device cadence override beats the variant baseline. Clamp to
    # [30s, 6h] so a buggy/old override never wedges or wakes the device.
    if device and device.refresh_interval_sec:
        next_checkin_sec = max(30, min(int(device.refresh_interval_sec), 21600))
    else:
        next_checkin_sec = max(30, int(v.next_checkin_sec))
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

    response.headers["ETag"] = schedule_etag
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return payload


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
                "Cache-Control": "no-cache",
            },
        )

    headers = {
        "Content-Type": "image/bmp",
        "Content-Length": str(len(body)),
        "ETag": etag,
        "Cache-Control": "no-cache",
    }
    return Response(content=body, status_code=200, headers=headers, media_type="image/bmp")
