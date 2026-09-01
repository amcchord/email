"""Browser-display adapter for the existing At a Glance renderers."""
from __future__ import annotations

import hashlib
import html
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from backend.models.terminal import TerminalSettings
from backend.services.terminal.catalog import (
    DesignDefinition,
    DisplayProfile,
    ViewDefinition,
    validate_catalog_content_implementations,
)
from backend.services.terminal.renderer import (
    render_clock_image,
    render_dashboard_bmp,
    render_day_ahead_bmp,
)
from backend.services.terminal.variants import SPECTRA6_800, SPECTRA6_1200, Variant


@dataclass(frozen=True)
class WebFrame:
    body: bytes
    etag: str
    width: int
    height: int


WebRenderer = Callable[
    [TerminalSettings, ViewDefinition, DesignDefinition | None, DisplayProfile],
    Awaitable[Image.Image],
]


async def _render_day_ahead(
    settings: TerminalSettings,
    _view: ViewDefinition,
    _design: DesignDefinition | None,
    profile: DisplayProfile,
) -> Image.Image:
    variant = SPECTRA6_1200 if profile.orientation == "portrait" else SPECTRA6_800
    body, _ = await render_day_ahead_bmp(
        variant,
        device=None,
        settings=settings,
    )
    return Image.open(BytesIO(body)).convert("RGB")


async def _render_dashboard(
    settings: TerminalSettings,
    _view: ViewDefinition,
    design: DesignDefinition | None,
    _profile: DisplayProfile,
) -> Image.Image:
    body, _ = await render_dashboard_bmp(
        SPECTRA6_800,
        device=None,
        settings=settings,
        design_override=design.key if design else None,
    )
    return Image.open(BytesIO(body)).convert("RGB")


async def _render_clock(
    settings: TerminalSettings,
    view: ViewDefinition,
    _design: DesignDefinition | None,
    profile: DisplayProfile,
) -> Image.Image:
    target_size = (720, 1280) if profile.orientation == "portrait" else (1280, 720)
    web_variant = Variant(
        key=f"web_{profile.key}",
        query="",
        image_format=f"rgb-web-{target_size[0]}x{target_size[1]}",
        width=target_size[0],
        height=target_size[1],
        bytes_total=0,
        next_checkin_sec=60,
        render_bucket_sec=60,
    )
    return render_clock_image(
        web_variant,
        device_name=view.label,
        tz_name=settings.timezone,
    )


WEB_RENDERERS: dict[str, WebRenderer] = {
    "day_ahead": _render_day_ahead,
    "eink_dashboard": _render_dashboard,
    "clock": _render_clock,
}

validate_catalog_content_implementations(WEB_RENDERERS, surface="web")


async def render_web_frame(
    *,
    settings: TerminalSettings,
    view: ViewDefinition,
    design: DesignDefinition | None,
    profile: DisplayProfile,
) -> WebFrame:
    """Render a browser PNG through the same pipeline used for panel BMPs.

    Decoding the canonical BMP back to PNG deliberately keeps browser and
    e-ink output visually identical while making the frame universally
    displayable by browsers. A future native-DOM design can be introduced as
    another adapter without changing the URL/catalog contract.
    """
    target_size = (720, 1280) if profile.orientation == "portrait" else (1280, 720)
    renderer = WEB_RENDERERS.get(view.content_type)
    if renderer is None:
        raise ValueError(f"No web renderer registered for {view.content_type!r}")
    image = await renderer(settings, view, design, profile)

    if image.size != target_size:
        fitted = ImageOps.contain(image, target_size, method=Image.Resampling.LANCZOS)
        background = image.getpixel((0, 0))
        canvas = Image.new("RGB", target_size, color=background)
        offset = (
            (target_size[0] - fitted.width) // 2,
            (target_size[1] - fitted.height) // 2,
        )
        canvas.paste(fitted, offset)
        image = canvas

    out = BytesIO()
    image.save(out, format="PNG", optimize=False)
    png = out.getvalue()
    return WebFrame(
        body=png,
        etag='"web-' + hashlib.sha256(png).hexdigest()[:20] + '"',
        width=image.width,
        height=image.height,
    )


def build_display_html(
    *,
    token: str,
    view: ViewDefinition,
    design: DesignDefinition | None,
    profile: DisplayProfile,
    refresh_sec: int,
) -> str:
    frame_url = f"/terminal/display/{token}/frame.png"
    title = view.label if design is None else f"{view.label} · {design.label}"
    safe_title = html.escape(title)
    ratio = f"{profile.aspect_width} / {profile.aspect_height}"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="color-scheme" content="light">
  <meta http-equiv="refresh" content="{refresh_sec}">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: light; --display-ratio: {ratio}; }}
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; }}
    body {{
      display: grid;
      place-items: center;
      background: #dedbd2;
      color: #111;
      font-family: system-ui, sans-serif;
    }}
    .display {{
      width: min(100vw, calc(100vh * {profile.aspect_width} / {profile.aspect_height}));
      height: min(100vh, calc(100vw * {profile.aspect_height} / {profile.aspect_width}));
      aspect-ratio: var(--display-ratio);
      display: grid;
      place-items: center;
      overflow: hidden;
      background: #f5f2e9;
    }}
    .display img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
    }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
  </style>
</head>
<body data-view="{html.escape(view.key)}" data-profile="{html.escape(profile.key)}">
  <main class="display" aria-label="{safe_title}">
    <h1 class="sr-only">{safe_title}</h1>
    <img src="{html.escape(frame_url, quote=True)}" alt="{safe_title}">
  </main>
</body>
</html>"""
