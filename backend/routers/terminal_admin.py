"""Cookie-authed admin endpoints for managing per-user terminal settings + devices.

Mounted at /api/terminal/* (so it sits next to the rest of the JSON API and
uses the same session cookie auth as the Svelte UI). Read by the new
"E-Ink Terminals" section in `frontend/src/pages/Admin.svelte`.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.terminal import TerminalDevice, TerminalSettings
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.services.eink.ha_client import (
    HAClientError,
    fetch_ha_states,
)
from backend.services.terminal.renderer import (
    _palette_for_variant,
    render_dashboard_bmp,
)
from backend.services.terminal.variants import VARIANTS, parse_variant
from backend.utils.security import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/terminal", tags=["terminal-admin"])


# Content types the UI can pick. `eink_dashboard` requires Home Assistant
# credentials to be useful but renders the calm/empty design either way.
SUPPORTED_CONTENT_TYPES: list[dict] = [
    {"key": "clock", "label": "Clock", "available": True},
    {"key": "eink_dashboard", "label": "E-Ink Dashboard (HA)", "available": True},
    {"key": "calendar", "label": "Calendar (coming soon)", "available": False},
]
_VALID_CONTENT_KEYS = {c["key"] for c in SUPPORTED_CONTENT_TYPES if c["available"]}


# Available designs for content_type=eink_dashboard. Both ship at 800x480.
DESIGN_OPTIONS: list[dict] = [
    {"key": "editorial", "label": "Editorial (newspaper / serif)"},
    {"key": "swiss", "label": "Swiss (modular / mono)"},
]
_VALID_DESIGN_KEYS = {d["key"] for d in DESIGN_OPTIONS}


# Refresh-rate presets surfaced as a dropdown in the admin UI. The "default"
# entry (value=None) maps the device back to its variant's baseline cadence.
# Server-side floor is 30s (firmware sanity floor in docs/terminal/), ceiling
# is 6h; any value outside that range is rejected.
REFRESH_INTERVAL_FLOOR = 30
REFRESH_INTERVAL_CEILING = 6 * 60 * 60

REFRESH_INTERVAL_PRESETS: list[dict] = [
    {"value": None, "label": "Variant default"},
    {"value": 30, "label": "30 seconds"},
    {"value": 60, "label": "1 minute"},
    {"value": 120, "label": "2 minutes"},
    {"value": 300, "label": "5 minutes"},
    {"value": 600, "label": "10 minutes"},
    {"value": 900, "label": "15 minutes"},
    {"value": 1800, "label": "30 minutes"},
    {"value": 3600, "label": "1 hour"},
    {"value": 7200, "label": "2 hours"},
    {"value": 14400, "label": "4 hours"},
    {"value": 21600, "label": "6 hours"},
]


# ── Schemas ─────────────────────────────────────────────────────────


class VariantInfo(BaseModel):
    key: str
    query: str
    image_format: str
    width: int
    height: int
    next_checkin_sec: int


class TerminalSettingsResponse(BaseModel):
    code: str
    schedule_url_template: str  # for UI display, e.g. /terminal/CODE/schedule.json[?variant=...]
    image_url_template: str
    timezone: str
    home_assistant_url: Optional[str] = None
    home_assistant_token_set: bool = False
    variants: list[VariantInfo]
    content_types: list[dict]
    designs: list[dict]
    refresh_interval_presets: list[dict]


class HomeAssistantUpdate(BaseModel):
    home_assistant_url: Optional[str] = Field(default=None, max_length=500)
    home_assistant_token: Optional[str] = Field(default=None, max_length=2000)
    clear: bool = False


class TimezoneUpdate(BaseModel):
    timezone: str = Field(..., min_length=1, max_length=100)


class TerminalDeviceResponse(BaseModel):
    id: int
    mac: str
    name: str
    variant: Optional[str]
    content_type: str
    content_config: Optional[dict] = None
    refresh_interval_sec: Optional[int] = None
    effective_refresh_interval_sec: int
    last_seen_at: Optional[datetime]
    last_wake_reason: Optional[str]
    last_battery_mv: Optional[int]
    last_battery_pct: Optional[int]
    last_rssi_dbm: Optional[int]
    last_uptime_sec: Optional[int]
    last_boot_count: Optional[int]
    last_fw_version: Optional[str]
    last_image_etag: Optional[str]
    created_at: datetime


class TerminalDeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    content_type: Optional[str] = Field(default=None, max_length=32)
    content_config: Optional[dict] = None
    # `refresh_interval_sec` is tri-state on the wire:
    #   - omitted entirely    -> leave alone
    #   - explicit `null`     -> clear override, fall back to variant default
    #   - integer in [30, 21600] -> set override
    refresh_interval_sec: Optional[int] = Field(default=None)
    refresh_interval_clear: bool = False


# ── Helpers ─────────────────────────────────────────────────────────


def _generate_code() -> str:
    """11-char URL-safe base62-ish opaque code (token_urlsafe with a fixed length)."""
    # token_urlsafe(8) is ~11 chars from a 64-char alphabet -> ~66 bits of entropy.
    # Plenty for an opaque per-user secret used over HTTPS.
    return secrets.token_urlsafe(8)


async def _get_or_create_settings(db: AsyncSession, user: User) -> TerminalSettings:
    result = await db.execute(
        select(TerminalSettings).where(TerminalSettings.user_id == user.id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = TerminalSettings(user_id=user.id, code=_generate_code())
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


def _settings_response(s: TerminalSettings) -> TerminalSettingsResponse:
    decoded_url: Optional[str] = s.home_assistant_url or None
    return TerminalSettingsResponse(
        code=s.code,
        schedule_url_template=f"/terminal/{s.code}/schedule.json",
        image_url_template=f"/terminal/{s.code}/image.bmp",
        timezone=s.timezone or "UTC",
        home_assistant_url=decoded_url,
        home_assistant_token_set=bool(s.home_assistant_token_encrypted),
        variants=[
            VariantInfo(
                key=v.key,
                query=v.query,
                image_format=v.image_format,
                width=v.width,
                height=v.height,
                next_checkin_sec=v.next_checkin_sec,
            )
            for v in VARIANTS.values()
        ],
        content_types=SUPPORTED_CONTENT_TYPES,
        designs=DESIGN_OPTIONS,
        refresh_interval_presets=REFRESH_INTERVAL_PRESETS,
    )


def _effective_interval(d: TerminalDevice) -> int:
    """What schedule.json would actually return for this device right now."""
    if d.refresh_interval_sec:
        return max(REFRESH_INTERVAL_FLOOR, min(int(d.refresh_interval_sec), REFRESH_INTERVAL_CEILING))
    v = VARIANTS.get(d.variant or "") if d.variant else None
    if v:
        return v.next_checkin_sec
    # Unknown variant -> fall back to the Spectra-6 7.3" default cadence.
    return next(iter(VARIANTS.values())).next_checkin_sec


def _serialize_device(d: TerminalDevice) -> TerminalDeviceResponse:
    return TerminalDeviceResponse(
        id=d.id,
        mac=d.mac,
        name=d.name or "",
        variant=d.variant,
        content_type=d.content_type or "clock",
        content_config=d.content_config,
        refresh_interval_sec=d.refresh_interval_sec,
        effective_refresh_interval_sec=_effective_interval(d),
        last_seen_at=d.last_seen_at,
        last_wake_reason=d.last_wake_reason,
        last_battery_mv=d.last_battery_mv,
        last_battery_pct=d.last_battery_pct,
        last_rssi_dbm=d.last_rssi_dbm,
        last_uptime_sec=d.last_uptime_sec,
        last_boot_count=d.last_boot_count,
        last_fw_version=d.last_fw_version,
        last_image_etag=d.last_image_etag,
        created_at=d.created_at,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/settings", response_model=TerminalSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = await _get_or_create_settings(db, user)
    return _settings_response(settings)


@router.post("/settings/regenerate", response_model=TerminalSettingsResponse)
async def regenerate_code(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Roll the per-user short code. Existing devices will start 404'ing until
    their firmware config is updated to the new URL."""
    settings = await _get_or_create_settings(db, user)
    settings.code = _generate_code()
    settings.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(settings)
    return _settings_response(settings)


@router.put("/settings/timezone", response_model=TerminalSettingsResponse)
async def set_timezone(
    payload: TimezoneUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Set the IANA timezone the e-ink clock uses to render the displayed time.

    Validated against the system zoneinfo db so we never persist a value the
    renderer would silently fall back to UTC on.
    """
    tz_name = payload.timezone.strip()
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown IANA timezone: {tz_name!r}. Try e.g. 'America/New_York'.",
        )

    settings = await _get_or_create_settings(db, user)
    settings.timezone = tz_name
    settings.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(settings)
    return _settings_response(settings)


@router.put("/settings/home-assistant", response_model=TerminalSettingsResponse)
async def set_home_assistant(
    payload: HomeAssistantUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save (or clear) the Home Assistant URL + long-lived access token.

    The token is encrypted at rest with the existing app encryption key. The
    endpoint never returns the plaintext token; the UI only shows whether one
    is set. Pass `clear: true` to wipe both fields.
    """
    settings = await _get_or_create_settings(db, user)

    if payload.clear:
        settings.home_assistant_url = None
        settings.home_assistant_token_encrypted = None
    else:
        if payload.home_assistant_url is not None:
            url = payload.home_assistant_url.strip()
            settings.home_assistant_url = url or None
        if payload.home_assistant_token is not None:
            token = payload.home_assistant_token.strip()
            if token:
                try:
                    settings.home_assistant_token_encrypted = encrypt_value(token)
                except Exception as exc:
                    logger.exception("Failed to encrypt HA token")
                    raise HTTPException(status_code=500, detail=f"Encryption error: {exc}")
            else:
                settings.home_assistant_token_encrypted = None

    settings.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(settings)
    return _settings_response(settings)


@router.get("/devices", response_model=list[TerminalDeviceResponse])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TerminalDevice)
        .where(TerminalDevice.user_id == user.id)
        .order_by(TerminalDevice.last_seen_at.desc().nullslast(), TerminalDevice.id.desc())
    )
    return [_serialize_device(d) for d in result.scalars().all()]


@router.patch("/devices/{device_id}", response_model=TerminalDeviceResponse)
async def update_device(
    device_id: int,
    payload: TerminalDeviceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TerminalDevice).where(
            TerminalDevice.id == device_id,
            TerminalDevice.user_id == user.id,
        )
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if payload.name is not None:
        device.name = payload.name.strip()[:200]
    if payload.content_type is not None:
        ct = payload.content_type.strip().lower()
        if ct not in _VALID_CONTENT_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported content_type '{ct}'. Available: {sorted(_VALID_CONTENT_KEYS)}",
            )
        device.content_type = ct
        # When switching INTO eink_dashboard, seed a default design so the
        # next render doesn't have to guess.
        if ct == "eink_dashboard":
            cfg = device.content_config or {}
            if not cfg.get("design"):
                cfg["design"] = "editorial"
                device.content_config = cfg
    if payload.content_config is not None:
        cfg = dict(payload.content_config)
        target_ct = (payload.content_type or device.content_type or "clock").lower()
        if target_ct == "eink_dashboard":
            design = str(cfg.get("design") or "editorial").lower()
            if design not in _VALID_DESIGN_KEYS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported design '{design}'. Available: {sorted(_VALID_DESIGN_KEYS)}",
                )
            cfg["design"] = design
        device.content_config = cfg
    if payload.refresh_interval_clear:
        device.refresh_interval_sec = None
    elif payload.refresh_interval_sec is not None:
        if (
            payload.refresh_interval_sec < REFRESH_INTERVAL_FLOOR
            or payload.refresh_interval_sec > REFRESH_INTERVAL_CEILING
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"refresh_interval_sec must be between {REFRESH_INTERVAL_FLOOR} and "
                    f"{REFRESH_INTERVAL_CEILING} seconds (or pass refresh_interval_clear=true to reset)."
                ),
            )
        device.refresh_interval_sec = int(payload.refresh_interval_sec)

    await db.commit()
    await db.refresh(device)
    return _serialize_device(device)


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        delete(TerminalDevice).where(
            TerminalDevice.id == device_id,
            TerminalDevice.user_id == user.id,
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    return None


# ── Home Assistant connection test ─────────────────────────────────


class HomeAssistantTestResponse(BaseModel):
    ok: bool
    entity_count: int = 0
    error: Optional[str] = None


@router.post("/ha/test", response_model=HomeAssistantTestResponse)
async def test_home_assistant(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Live-test the saved HA URL + token by calling /api/states.

    Returns ok=True with the entity count on success, or ok=False with a
    short human-readable error string. Never raises -- the UI uses the
    payload directly.
    """
    settings = await _get_or_create_settings(db, user)
    url = (settings.home_assistant_url or "").strip()
    if not url or not settings.home_assistant_token_encrypted:
        return HomeAssistantTestResponse(ok=False, error="Home Assistant URL or token not configured")
    try:
        token = decrypt_value(settings.home_assistant_token_encrypted)
    except Exception:
        return HomeAssistantTestResponse(ok=False, error="Failed to decrypt stored token")
    try:
        states = await fetch_ha_states(url, token)
    except HAClientError as e:
        return HomeAssistantTestResponse(ok=False, error=str(e))
    return HomeAssistantTestResponse(ok=True, entity_count=len(states))


# ── Per-device preview (post-quantize PNG of the Pillow render) ────


@router.get("/devices/{device_id}/preview.png")
async def preview_device_png(
    device_id: int,
    palette: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Render the device's current dashboard, run it through the BMP
    quantizer, and return the result decoded back to PNG so the UI can
    show exactly what the panel is going to display."""
    result = await db.execute(
        select(TerminalDevice).where(
            TerminalDevice.id == device_id,
            TerminalDevice.user_id == user.id,
        )
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    settings = await _get_or_create_settings(db, user)

    # Pin the variant we render for: respect the device's last-seen variant,
    # honoring the optional ?palette= override (for the UI's "show as B&W"
    # toggle without making the user wait for a real BW device check-in).
    variant = VARIANTS.get(device.variant or "") if device.variant else None
    if palette and palette.lower() == "bw":
        variant = VARIANTS.get("bw") or variant
    elif palette and palette.lower() == "six":
        variant = VARIANTS.get("spectra6_800x480") or variant
    if variant is None:
        variant = VARIANTS.get("spectra6_800x480") or next(iter(VARIANTS.values()))

    # Force eink_dashboard rendering even if the device is currently
    # configured for the clock placeholder, so the preview always shows the
    # designs the user is choosing between.
    saved_ct = device.content_type
    device.content_type = "eink_dashboard"
    try:
        body, _etag = await render_dashboard_bmp(
            variant, device=device, settings=settings
        )
    finally:
        device.content_type = saved_ct

    # Decode the BMP back to a PNG so browsers can show it.
    img = Image.open(BytesIO(body)).convert("RGB")
    out = BytesIO()
    img.save(out, format="PNG", optimize=False)
    return Response(
        content=out.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )
