"""Placeholder dashboard renderer.

For now every device gets a centered clock + its name. The render-time bucket
is rounded down to the variant's `render_bucket_sec`, so back-to-back
check-ins within one bucket produce byte-identical BMPs (and therefore the
same ETag). That's what makes `If-None-Match -> 304` actually skip the
~192 KB / ~960 KB transfer per docs/terminal/server-protocol.md Â§5.5.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageDraw, ImageFont

from backend.models.terminal import TerminalDevice, TerminalSettings
from backend.services.eink.ha_client import empty_ha_shape, fetch_and_shape
from backend.services.eink.pillow import render_eink_image
from backend.services.terminal.bmp import (
    encode_bw,
    encode_gray16,
    encode_spectra6,
)
from backend.services.terminal.variants import Variant

logger = logging.getLogger(__name__)


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, IOError):
            continue
    logger.warning("No TrueType font found; falling back to PIL default")
    return ImageFont.load_default()


def _bucketed_now(variant: Variant) -> datetime:
    now = datetime.now(timezone.utc)
    bucket = max(variant.render_bucket_sec, 1)
    epoch = int(now.timestamp())
    floored = (epoch // bucket) * bucket
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _resolve_zone(tz_name: Optional[str]) -> ZoneInfo:
    """Best-effort IANA tz lookup. Falls back to UTC on unknown/empty values
    so a misconfigured setting can never 500 the device check-in."""
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown terminal timezone %r; falling back to UTC", tz_name)
        return ZoneInfo("UTC")


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = xy[0] - w // 2 - bbox[0]
    y = xy[1] - h // 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill)


def _render_canvas(
    variant: Variant,
    *,
    device_name: str,
    rendered_at: datetime,
    accent_rgb: tuple[int, int, int],
    tz_name: Optional[str] = None,
) -> Image.Image:
    """Render the placeholder dashboard at the variant's native resolution."""
    width, height = variant.width, variant.height
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Cheap layout: huge HH:MM in the middle, smaller date above, device name and
    # variant footer below. Sizes scale with panel height so the 13.3" panel
    # gets bigger glyphs.
    big_size = max(80, height // 4)
    medium_size = max(28, height // 14)
    small_size = max(18, height // 24)

    big_font = _load_font(big_size)
    medium_font = _load_font(medium_size)
    small_font = _load_font(small_size)

    local_now = rendered_at.astimezone(_resolve_zone(tz_name))
    time_text = local_now.strftime("%H:%M")
    date_text = local_now.strftime("%A, %B %-d %Y")
    footer_text = f"{device_name or 'unnamed'}  ·  {variant.image_format}"

    cx = width // 2
    cy = height // 2

    _draw_centered(draw, (cx, cy - big_size // 2 - medium_size), date_text, medium_font, (0, 0, 0))
    _draw_centered(draw, (cx, cy), time_text, big_font, accent_rgb)
    _draw_centered(draw, (cx, height - small_size * 2), footer_text, small_font, (0, 0, 0))

    # Top/bottom borders for a bit of e-ink-friendly visual structure.
    border = max(2, height // 240)
    draw.rectangle([(0, 0), (width - 1, border - 1)], fill=accent_rgb)
    draw.rectangle([(0, height - border), (width - 1, height - 1)], fill=accent_rgb)

    return img


def render_bmp(
    variant: Variant,
    *,
    device_name: str = "",
    tz_name: Optional[str] = None,
) -> tuple[bytes, str]:
    """Render the placeholder dashboard for `variant`.

    `tz_name` is an IANA timezone name used to localize the displayed time
    (defaults to UTC if missing/unknown). It also feeds into the ETag via the
    rendered pixel bytes, so back-to-back check-ins from devices in different
    timezones don't collide on the cache.

    Returns (bmp_bytes, etag). The ETag is sha1 over the BMP body so it's
    stable while the bucketed render input is stable.
    """
    rendered_at = _bucketed_now(variant)

    # Pick an accent color the panel can actually display. BW + Gray panels
    # only do black; Spectra-6 has red, which reads well as a clock accent.
    if variant.image_format.startswith("bmp4-spectra6"):
        accent = (255, 0, 0)
    else:
        accent = (0, 0, 0)

    canvas = _render_canvas(
        variant,
        device_name=device_name,
        rendered_at=rendered_at,
        accent_rgb=accent,
        tz_name=tz_name,
    )

    if variant.image_format == "bmp1-bw-800x480":
        body = encode_bw(canvas)
    elif variant.image_format == "bmp4-gray16-800x480":
        body = encode_gray16(canvas)
    elif variant.image_format == "bmp4-spectra6-800x480":
        body = encode_spectra6(canvas, width=800, height=480)
    elif variant.image_format == "bmp4-spectra6-1200x1600":
        body = encode_spectra6(canvas, width=1200, height=1600)
    else:
        raise ValueError(f"unsupported variant {variant.image_format}")

    etag = '"img-' + hashlib.sha1(body).hexdigest()[:16] + '"'
    return body, etag


# ── E-ink dashboard renderer (Editorial / Swiss + HA) ──────────────────


_VALID_DESIGNS = {"editorial", "swiss"}


def _resolve_design(device: Optional[TerminalDevice]) -> str:
    if not device:
        return "editorial"
    cfg = device.content_config or {}
    design = str(cfg.get("design") or "editorial").lower()
    return design if design in _VALID_DESIGNS else "editorial"


def _palette_for_variant(variant: Variant) -> str:
    """Map the wire variant to a design palette.

    BW panel -> the design's `bw` palette (everything collapses to ink).
    Anything else (Spectra-6 6-color, Gray16) -> the `six` palette.
    """
    if variant.key == "bw":
        return "bw"
    return "six"


async def render_dashboard_bmp(
    variant: Variant,
    *,
    device: Optional[TerminalDevice],
    settings: TerminalSettings,
) -> tuple[bytes, str]:
    """Render the e-ink dashboard for `device` and encode it as a panel BMP.

    On any failure fetching HA, falls back to an empty/calm-state shape so
    the panel still receives a valid frame instead of stalling on the
    previous one.
    """
    ha_shape: Optional[dict[str, Any]]
    try:
        ha_shape = await fetch_and_shape(settings)
    except Exception:
        logger.exception("HA fetch unexpectedly raised; falling back to calm state")
        ha_shape = None
    if ha_shape is None:
        ha_shape = empty_ha_shape()

    design = _resolve_design(device)
    palette = _palette_for_variant(variant)
    tz_name = (settings.timezone or "UTC").strip() or "UTC"

    # Pillow renderer is CPU-bound; keep the event loop free while it paints.
    img = await asyncio.to_thread(
        render_eink_image, design, palette, ha_shape, tz_name=tz_name
    )
    if img.size != (variant.width, variant.height):
        img = img.resize((variant.width, variant.height), Image.NEAREST)

    # Dithering is OFF for the dashboard. The Pillow renderer already paints
    # every rule at 1-px integer positions and uses pixel fonts at their
    # native bitmap sizes, so only the larger serif/sans display type has
    # AA-grey edges that the quantizer has to snap. Floyd-Steinberg WRECKS
    # the pixel fonts because it shuffles individual on/off pixels of the
    # glyphs (flips the middle stem of an "M" into a neighboring column,
    # turning it into an "N"). Snap-to-nearest gives a slightly chunkier
    # serif edge but preserves every pixel-font glyph byte-exactly.
    if variant.image_format == "bmp1-bw-800x480":
        body = encode_bw(img, dither=False)
    elif variant.image_format == "bmp4-spectra6-800x480":
        body = encode_spectra6(img, width=800, height=480, dither=False)
    elif variant.image_format == "bmp4-spectra6-1200x1600":
        body = encode_spectra6(img, width=1200, height=1600, dither=False)
    elif variant.image_format == "bmp4-gray16-800x480":
        body = encode_gray16(img)
    else:
        raise ValueError(f"unsupported variant for dashboard: {variant.image_format}")

    etag = '"img-' + hashlib.sha1(body).hexdigest()[:16] + '"'
    return body, etag
