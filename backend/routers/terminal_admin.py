"""Cookie-authed admin endpoints for managing per-user terminal settings + devices.

Mounted at /api/terminal/* (so it sits next to the rest of the JSON API and
uses the same session cookie auth as the Svelte UI). Read by the new
"At a Glance" section in `frontend/src/pages/Admin.svelte`.
"""
from __future__ import annotations

import logging
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.terminal import (
    TerminalBatterySample,
    TerminalDevice,
    TerminalSettings,
    TerminalWebDisplay,
)
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.services.eink.ha_client import (
    HAClientError,
    fetch_ha_states,
)
from backend.services.terminal.battery import BatteryReading, estimate_battery_health
from backend.services.terminal.catalog import (
    CatalogError,
    content_type_options,
    design_options,
    display_profile_options,
    resolve_design,
    resolve_profile,
    resolve_view,
    view_options,
    web_display_definitions,
    web_display_options,
)
from backend.services.terminal.renderer import (
    render_dashboard_bmp,
    render_day_ahead_bmp,
)
from backend.services.terminal.variants import VARIANTS
from backend.services.terminal.web_display import render_web_frame
from backend.utils.security import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/terminal", tags=["terminal-admin"])


# Content types the UI can pick. `eink_dashboard` requires Home Assistant
# credentials to be useful but renders the calm/empty design either way.
SUPPORTED_CONTENT_TYPES: list[dict] = content_type_options()
_VALID_CONTENT_KEYS = {c["key"] for c in SUPPORTED_CONTENT_TYPES if c["available"]}


# Available designs for content_type=eink_dashboard. Both ship at 800x480.
DESIGN_OPTIONS: list[dict] = design_options()
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
    display_url_template: str
    timezone: str
    home_assistant_url: Optional[str] = None
    home_assistant_token_set: bool = False
    variants: list[VariantInfo]
    content_types: list[dict]
    designs: list[dict]
    views: list[dict]
    display_profiles: list[dict]
    web_displays: list[dict]
    refresh_interval_presets: list[dict]


class HomeAssistantUpdate(BaseModel):
    home_assistant_url: Optional[str] = Field(default=None, max_length=500)
    home_assistant_token: Optional[str] = Field(default=None, max_length=2000)
    clear: bool = False


class TimezoneUpdate(BaseModel):
    timezone: str = Field(..., min_length=1, max_length=100)


class BatteryHealthResponse(BaseModel):
    status: str
    current_pct: Optional[int] = None
    current_mv: Optional[int] = None
    observed_at: Optional[datetime] = None
    sample_count: int = 0
    trend_days: Optional[float] = None
    drain_pct_per_day: Optional[float] = None
    estimated_days_remaining: Optional[float] = None
    estimated_empty_at: Optional[datetime] = None
    estimated_charge_at: Optional[datetime] = None
    confidence: Optional[str] = None
    notice: Optional[str] = None


class TerminalDeviceResponse(BaseModel):
    id: int
    public_id: str
    mac: str
    name: str
    variant: Optional[str]
    hardware_model: Optional[str] = None
    enrollment_state: str
    enrollment_generation: int
    last_secure_checkin_at: Optional[datetime] = None
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
    battery_health: BatteryHealthResponse
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


class AtAGlanceExperienceResponse(BaseModel):
    """Credential-free data needed by the first-class At a Glance page."""

    views: list[dict]
    designs: list[dict]
    display_profiles: list[dict]
    combinations: list[dict]
    devices: list[TerminalDeviceResponse]


# ── Helpers ─────────────────────────────────────────────────────────


def _generate_code() -> str:
    """11-char URL-safe base62-ish opaque code (token_urlsafe with a fixed length)."""
    # token_urlsafe(8) is ~11 chars from a 64-char alphabet -> ~66 bits of entropy.
    # Plenty for an opaque per-user secret used over HTTPS.
    return secrets.token_urlsafe(8)


def _generate_display_token() -> str:
    """Return a high-entropy credential used by exactly one browser view."""
    return secrets.token_urlsafe(24)


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


async def _ensure_web_displays(
    db: AsyncSession,
    settings: TerminalSettings,
) -> list[TerminalWebDisplay]:
    result = await db.execute(
        select(TerminalWebDisplay).where(
            TerminalWebDisplay.user_id == settings.user_id
        )
    )
    displays = list(result.scalars().all())
    identities = {
        (display.view_key, display.design_key or None, display.profile_key)
        for display in displays
    }
    created = False
    for definition in web_display_definitions():
        identity = (
            definition["view"],
            definition["design"],
            definition["profile"],
        )
        if identity in identities:
            continue
        db.add(
            TerminalWebDisplay(
                user_id=settings.user_id,
                token=_generate_display_token(),
                view_key=definition["view"],
                design_key=definition["design"] or "",
                profile_key=definition["profile"],
            )
        )
        identities.add(identity)
        created = True
    if created:
        try:
            await db.commit()
        except IntegrityError:
            # Concurrent settings requests may race to provision the same
            # catalog entries. The unique identity wins; reload the result.
            await db.rollback()
        result = await db.execute(
            select(TerminalWebDisplay).where(
                TerminalWebDisplay.user_id == settings.user_id
            )
        )
        displays = list(result.scalars().all())
    return displays


async def _settings_response(
    db: AsyncSession,
    s: TerminalSettings,
) -> TerminalSettingsResponse:
    decoded_url: Optional[str] = s.home_assistant_url or None
    web_displays = await _ensure_web_displays(db, s)
    return TerminalSettingsResponse(
        code=s.code,
        schedule_url_template=f"/terminal/{s.code}/schedule.json",
        image_url_template=f"/terminal/{s.code}/image.bmp",
        display_url_template="/terminal/display/{token}.html",
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
        views=view_options(),
        display_profiles=display_profile_options(),
        web_displays=web_display_options(web_displays),
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


def _serialize_device(
    d: TerminalDevice,
    samples: list[TerminalBatterySample] | tuple = (),
) -> TerminalDeviceResponse:
    now = datetime.now(timezone.utc)
    health = estimate_battery_health(samples, now=now)
    # A deployment starts with no historical rows. Preserve the current
    # device snapshot in the health payload until its first sampled check-in.
    if health.current_pct is None and (d.last_battery_pct is not None or d.last_battery_mv is not None):
        synthetic = BatteryReading(
            observed_at=d.last_seen_at or d.created_at,
            battery_pct=d.last_battery_pct,
            battery_mv=d.last_battery_mv,
            boot_count=d.last_boot_count,
        )
        health = estimate_battery_health([synthetic], now=now)
    return TerminalDeviceResponse(
        id=d.id,
        public_id=str(d.public_id),
        mac=d.mac,
        name=d.name or "",
        variant=d.variant,
        hardware_model=d.hardware_model,
        enrollment_state=d.enrollment_state or "legacy",
        enrollment_generation=d.enrollment_generation or 0,
        last_secure_checkin_at=d.last_secure_checkin_at,
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
        battery_health=BatteryHealthResponse(**health.__dict__),
        created_at=d.created_at,
    )


async def _list_owned_device_summaries(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[TerminalDeviceResponse]:
    """Return owner-scoped terminal summaries with bounded battery history."""
    result = await db.execute(
        select(TerminalDevice)
        .where(TerminalDevice.user_id == user_id)
        .order_by(TerminalDevice.last_seen_at.desc().nullslast(), TerminalDevice.id.desc())
    )
    devices = list(result.scalars().all())
    if not devices:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    samples_result = await db.execute(
        select(TerminalBatterySample)
        .where(
            TerminalBatterySample.device_id.in_([device.id for device in devices]),
            TerminalBatterySample.observed_at >= cutoff,
        )
        .order_by(
            TerminalBatterySample.device_id.asc(),
            TerminalBatterySample.observed_at.asc(),
        )
    )
    samples_by_device: dict[int, list[TerminalBatterySample]] = defaultdict(list)
    for sample in samples_result.scalars().all():
        samples_by_device[sample.device_id].append(sample)
    return [_serialize_device(d, samples_by_device[d.id]) for d in devices]


async def _read_experience_settings(
    db: AsyncSession,
    *,
    user_id: int,
) -> TerminalSettings:
    """Read rendering settings without provisioning terminal credentials.

    Users who have never configured At a Glance can still preview the catalog.
    The transient settings object is deliberately never added or committed.
    """
    result = await db.execute(
        select(TerminalSettings).where(TerminalSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is not None:
        return settings
    return TerminalSettings(
        user_id=user_id,
        code="",
        timezone="UTC",
        home_assistant_url=None,
        home_assistant_token_encrypted=None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/settings", response_model=TerminalSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = await _get_or_create_settings(db, user)
    return await _settings_response(db, settings)


@router.get("/experience", response_model=AtAGlanceExperienceResponse)
async def get_experience(
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the read-only, credential-free At a Glance experience catalog."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    return AtAGlanceExperienceResponse(
        views=view_options(),
        designs=design_options(),
        display_profiles=display_profile_options(),
        combinations=web_display_definitions(),
        devices=await _list_owned_device_summaries(db, user_id=user.id),
    )


@router.get("/experience/preview.png")
async def preview_experience_png(
    view: Optional[str] = None,
    design: Optional[str] = None,
    profile: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Render one authenticated catalog combination as a canonical web PNG."""
    try:
        resolved_profile = resolve_profile(profile)
        resolved_view = resolve_view(view, profile=resolved_profile)
        resolved_design = resolve_design(resolved_view, design)
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = await _read_experience_settings(db, user_id=user.id)
    frame = await render_web_frame(
        settings=settings,
        view=resolved_view,
        design=resolved_design,
        profile=resolved_profile,
    )
    return Response(
        content=frame.body,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
            "ETag": frame.etag,
        },
    )


@router.post("/settings/regenerate", response_model=TerminalSettingsResponse)
async def regenerate_code(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rotate the firmware code without changing scoped browser links."""
    settings = await _get_or_create_settings(db, user)
    settings.code = _generate_code()
    settings.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(settings)
    return await _settings_response(db, settings)


@router.post(
    "/displays/{display_id}/regenerate",
    response_model=TerminalSettingsResponse,
)
async def regenerate_web_display(
    display_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Revoke one leaked browser URL by rotating only its bound token."""
    result = await db.execute(
        select(TerminalWebDisplay).where(
            TerminalWebDisplay.id == display_id,
            TerminalWebDisplay.user_id == user.id,
        )
    )
    display = result.scalar_one_or_none()
    if display is None:
        raise HTTPException(status_code=404, detail="Browser display not found")
    display.token = _generate_display_token()
    display.updated_at = datetime.now(timezone.utc)
    await db.commit()
    settings = await _get_or_create_settings(db, user)
    return await _settings_response(db, settings)


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
    return await _settings_response(db, settings)


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
    return await _settings_response(db, settings)


@router.get("/devices", response_model=list[TerminalDeviceResponse])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _list_owned_device_summaries(db, user_id=user.id)


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
        # Day Ahead is Editorial-only and is an hourly wall display; seed the
        # design and default the cadence to 1h if the device has no override.
        elif ct == "day_ahead":
            cfg = device.content_config or {}
            cfg["design"] = "editorial"
            device.content_config = cfg
            if not device.refresh_interval_sec:
                device.refresh_interval_sec = 3600
    if payload.content_config is not None:
        cfg = dict(payload.content_config)
        target_ct = (payload.content_type or device.content_type or "clock").lower()
        if target_ct == "day_ahead":
            # Editorial-only; ignore any other requested design.
            cfg["design"] = "editorial"
        elif target_ct == "eink_dashboard":
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
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    samples_result = await db.execute(
        select(TerminalBatterySample)
        .where(
            TerminalBatterySample.device_id == device.id,
            TerminalBatterySample.observed_at >= cutoff,
        )
        .order_by(TerminalBatterySample.observed_at.asc())
    )
    return _serialize_device(device, list(samples_result.scalars().all()))


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    device_result = await db.execute(
        select(TerminalDevice).where(
            TerminalDevice.id == device_id,
            TerminalDevice.user_id == user.id,
        )
    )
    device = device_result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.enrollment_state != "legacy":
        raise HTTPException(
            status_code=409,
            detail=(
                "Securely enrolled terminals cannot be forgotten while their "
                "credential history exists. Revoke secure access instead."
            ),
        )
    result = await db.execute(
        delete(TerminalDevice).where(TerminalDevice.id == device.id)
    )
    await db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Device changed while being forgotten")
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

    # The Day Ahead design is portrait-native (1200x1600); everything else
    # previews at the landscape 800x480 panel. Honor the ?palette= override
    # (the UI's "show as B&W" toggle) without waiting for a real BW check-in.
    is_day_ahead = (device.content_type or "") == "day_ahead"
    bw = bool(palette and palette.lower() == "bw")
    if is_day_ahead:
        variant = VARIANTS.get("bw") if bw else VARIANTS.get("spectra6_1200x1600")
        variant = variant or next(iter(VARIANTS.values()))
        body, _etag = await render_day_ahead_bmp(
            variant, device=device, settings=settings
        )
    else:
        variant = VARIANTS.get(device.variant or "") if device.variant else None
        if bw:
            variant = VARIANTS.get("bw") or variant
        elif palette and palette.lower() == "six":
            variant = VARIANTS.get("spectra6_800x480") or variant
        if variant is None:
            variant = VARIANTS.get("spectra6_800x480") or next(iter(VARIANTS.values()))

        # Force eink_dashboard rendering even if the device is currently
        # configured for the clock placeholder, so the preview always shows
        # the designs the user is choosing between.
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
