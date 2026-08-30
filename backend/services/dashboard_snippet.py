"""Hourly snippet generator for the editorial e-ink calm-state hero.

The renderer reads ``ha_shape['dashboardSnippet']`` to display a rotating
"quote of the hour" or "observation of the hour" when nothing is active.
This service generates one snippet per (local date, local hour) using
Claude Haiku and persists it in ``dashboard_snippets``. The cron worker
in ``backend/workers/tasks.py`` ticks every hour to keep the row fresh
for the upcoming hour; the renderer is a strict reader.

Even hours produce **quotes** (short literary or aphoristic lines with
attribution). Odd hours produce **observations** (a contextual one-liner
that may riff on today's weather, season, or daylight). This keeps the
panel varied across the day without requiring the model to "be creative"
on every call.

If the Claude API key is missing or the AI call fails the service
silently no-ops -- the renderer falls back to ``flavor.fallback_idle_snippet``
so the panel always shows *something*.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import async_session
from backend.models.dashboard import DashboardSnippet
from backend.models.terminal import TerminalSettings

logger = logging.getLogger(__name__)


# ── Time helpers ───────────────────────────────────────────────────────


def _resolve_zone(tz_name: Optional[str]) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown timezone %r; falling back to UTC", tz_name)
        return ZoneInfo("UTC")


def _now_local(tz_name: Optional[str]) -> datetime:
    return datetime.now(tz=_resolve_zone(tz_name))


def _key(now_local: datetime) -> tuple[str, int]:
    return now_local.strftime("%Y-%m-%d"), now_local.hour


# ── Read path (called from the renderer) ───────────────────────────────


async def get_current_snippet_dict(tz_name: Optional[str]) -> Optional[dict[str, str]]:
    """Return the snippet for the current ``(date_local, hour_local)`` or None.

    The renderer treats ``None`` as "no AI snippet yet, fall back to the
    curated pool". DB failures also return ``None`` -- rendering a panel
    must never depend on the snippet table being reachable.
    """
    date_local, hour_local = _key(_now_local(tz_name))
    try:
        async with async_session() as db:
            row = await _fetch_row(db, date_local, hour_local)
    except Exception:
        logger.exception("dashboard_snippet: read failed")
        return None
    if row is None:
        return None
    return {
        "kind": row.kind,
        "text": row.text,
        "byline": row.byline or "",
    }


async def _fetch_row(
    db: AsyncSession, date_local: str, hour_local: int,
) -> Optional[DashboardSnippet]:
    result = await db.execute(
        select(DashboardSnippet).where(
            DashboardSnippet.date_local == date_local,
            DashboardSnippet.hour_local == hour_local,
        )
    )
    return result.scalar_one_or_none()


# ── Write path (called from the cron worker) ───────────────────────────


_QUOTE_SYSTEM = """You curate a single resonant quote for an editorial e-ink dashboard hanging in a home in Cambridge, Massachusetts. The dashboard shows the quote during quiet moments, so the line should reward a second of attention. Respond with ONLY valid JSON in the exact shape:

{"text": "<one quote, 8-22 words, no surrounding quote marks, no emoji>",
 "byline": "<the author's short name as it would appear in a print magazine, e.g. 'Henry David Thoreau', 'Mary Oliver', 'Emily Dickinson'. 'Anonymous' is fine if needed.>"}

The piece is set in Cambridge, MA -- New England, university town, four real seasons, walking distance to Walden, Mt Auburn, the Charles. Favor authors with a connection to the region or the New England literary tradition when the context lets you (Emerson, Thoreau, Dickinson, Frost, Longfellow, William James, Mary Oliver, Annie Dillard, Donald Hall, Robert Lowell, Hawthorne, Alcott, Adrienne Rich, E. B. White, Wendell Berry) -- but a global author whose line genuinely fits the moment is always better than a forced local one.

Use the context you are given (time of day, season, weather, weekday, date). Pick a line that resonates with it -- a quote about morning if it's morning, about rain if it's raining, about winter quiet if it's January. Do NOT mention Cambridge or the weather in the quote text itself. Pick a quote that already speaks to the moment.

Vary the era, vary the tone (sometimes serious, sometimes wry). Avoid the same handful of overused lines ('be the change', 'live every day', etc.).

The text MUST be at most 180 characters. Real quotes only, no invented ones."""


_OBSERVATION_SYSTEM = """You write a single short observation for an editorial e-ink dashboard hanging in a home in Cambridge, Massachusetts. Respond with ONLY valid JSON in the exact shape:

{"text": "<one short line, 8-24 words, lightly poetic, about the present hour in this place>",
 "byline": "<a tiny label like 'house notes', 'by the hour', 'from the porch', 'Cambridge dispatch', 'on the hour'>"}

The piece lives in Cambridge, MA. The neighborhood is Harvard / Mid-Cambridge / Cambridgeport -- brick sidewalks, magnolias and dogwoods in spring, the Charles a few blocks south, the T rumbling under the square, undergrads, dog walkers, the smell of someone's woodstove in winter. Real Cambridge texture is great when it lands naturally; never name-drop for its own sake.

Use the context you are given (time, temperature, weather, season, weekday, date). Notice ONE specific thing about this moment in this place. A good observation reads like it was just whispered to you on a porch. Avoid lists of facts, avoid cliches ('embrace the moment', 'breathe it in'), avoid mentioning the e-ink dashboard or the AI.

The text MUST be at most 200 characters. Write in second person ('You can hear...') or in the neutral observational voice ('The rain has stopped...'). Never mention a specific person or 'we'."""


_TOOL_QUOTE = {
    "name": "save_quote",
    "description": "Save a short literary quote with an author byline.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The quote text. 8-20 words, no surrounding quote marks.",
            },
            "byline": {
                "type": "string",
                "description": "Author short name (no titles or dates). 'Anonymous' is fine.",
            },
        },
        "required": ["text", "byline"],
    },
}


_TOOL_OBSERVATION = {
    "name": "save_observation",
    "description": "Save a short contextual observation about today/this hour.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The observation. 8-22 words, lightly poetic, about the present.",
            },
            "byline": {
                "type": "string",
                "description": "Optional small label (not a person name). May be empty.",
            },
        },
        "required": ["text"],
    },
}


def _kind_for_hour(hour: int) -> str:
    if hour % 2 == 0:
        return "quote"
    return "observation"


def _context_summary(now_local: datetime, ha_shape: Optional[dict[str, Any]]) -> str:
    """Build a compact context string passed to the model.

    Used by both the quote prompt (so a January morning gets a January
    morning quote) and the observation prompt (so we can riff on the
    actual weather instead of inventing it).
    """
    weekday = now_local.strftime("%A")
    month = now_local.strftime("%B")
    day = now_local.day
    year = now_local.year
    hour24 = now_local.hour
    hour12 = ((hour24 + 11) % 12) + 1
    if hour24 < 12:
        ampm = "AM"
    else:
        ampm = "PM"

    parts: list[str] = []
    parts.append("Location: Cambridge, Massachusetts (a college city on the Charles River, just across from Boston).")
    parts.append(
        f"Local time: {weekday}, {month} {day} {year}, around {hour12}:00 {ampm}."
    )
    parts.append(f"Season: {_season(now_local)} (Northern Hemisphere).")
    parts.append(f"Time-of-day: {_time_of_day_label(hour24)}.")

    weather = (ha_shape or {}).get("weather") or {}
    state = (weather.get("state") or "").strip()
    temp = weather.get("temperature")
    weather_bits: list[str] = []
    if state:
        weather_bits.append(state.replace("-", " "))
    if temp is not None:
        try:
            f_val = round(float(temp))
            weather_bits.append(f"{f_val}\u00b0F")
        except (TypeError, ValueError):
            pass
    humidity = weather.get("humidity")
    if humidity is not None:
        try:
            weather_bits.append(f"{round(float(humidity))}% humidity")
        except (TypeError, ValueError):
            pass
    wind = weather.get("windSpeed")
    if wind is not None:
        try:
            w_val = round(float(wind))
            if w_val > 0:
                weather_bits.append(f"wind {w_val} mph")
        except (TypeError, ValueError):
            pass
    if weather_bits:
        parts.append("Outside: " + ", ".join(weather_bits) + ".")

    sun = (ha_shape or {}).get("sun") or {}
    sun_state = sun.get("state")
    if sun_state == "above_horizon":
        parts.append("Daylight (sun above horizon).")
    elif sun_state == "below_horizon":
        parts.append("Dark out (sun below horizon).")

    return "\n".join("- " + p for p in parts)


def _time_of_day_label(hour24: int) -> str:
    if hour24 < 5:
        return "deep night"
    if hour24 < 8:
        return "early morning"
    if hour24 < 12:
        return "late morning"
    if hour24 < 14:
        return "midday"
    if hour24 < 17:
        return "afternoon"
    if hour24 < 20:
        return "early evening"
    if hour24 < 23:
        return "evening"
    return "late night"


_SEASON_BOUNDARIES = (
    ("Spring", 3, 20),
    ("Summer", 6, 21),
    ("Autumn", 9, 22),
    ("Winter", 12, 21),
)


def _season(dt: datetime) -> str:
    m = dt.month
    d = dt.day
    if (m == 3 and d >= 20) or m in (4, 5) or (m == 6 and d < 21):
        return "Spring"
    if (m == 6 and d >= 21) or m in (7, 8) or (m == 9 and d < 22):
        return "Summer"
    if (m == 9 and d >= 22) or m in (10, 11) or (m == 12 and d < 21):
        return "Autumn"
    return "Winter"


async def _maybe_call_claude(
    kind: str, now_local: datetime, ha_shape: Optional[dict[str, Any]],
) -> Optional[dict[str, str]]:
    """Invoke the configured low-cost model via the existing AIService.

    Returns ``None`` if no API key is set or if any failure occurs. The
    cron task swallows None silently so a transient AI outage just
    means "no fresh row this hour"; the renderer's fallback kicks in.
    """
    from backend.services.ai import AIService
    from backend.services.ai_models import CHEAP_MODEL, provider_for_model

    settings = get_settings()
    provider = provider_for_model(CHEAP_MODEL)
    if provider == "openai" and not settings.openai_api_key:
        logger.info("dashboard_snippet: openai_api_key not configured, skipping")
        return None
    if provider == "anthropic" and not settings.claude_api_key:
        logger.info("dashboard_snippet: claude_api_key not configured, skipping")
        return None

    context = _context_summary(now_local, ha_shape)
    seed = now_local.strftime("%Y-%m-%dT%H")
    if kind == "quote":
        system = _QUOTE_SYSTEM
        tool = _TOOL_QUOTE
        user_message = (
            "Context for this slot:\n"
            f"{context}\n\n"
            "Pick one quote whose mood, season, or subject matches the moment. "
            "Vary the era and tone from any previous call -- don't always pick a Thoreau or a Dickinson. "
            "Real, attributable quotes only. No invented or embellished lines.\n\n"
            f"Hour seed (use only as a randomizer, do not echo): {seed}."
        )
    else:
        system = _OBSERVATION_SYSTEM
        tool = _TOOL_OBSERVATION
        user_message = (
            "Context for this hour:\n"
            f"{context}\n\n"
            "Notice ONE specific thing about this moment in Cambridge. Don't restate "
            "the context verbatim; let it inform the line. The reader already knows "
            "the temperature -- don't tell them what it is.\n\n"
            f"Hour seed (use only as a randomizer, do not echo): {seed}."
        )

    svc = AIService(model=CHEAP_MODEL)
    try:
        parsed, _tokens = await svc._call_claude_tool(
            model=CHEAP_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": user_message}],
            tool=tool,
            system=system,
        )
    except Exception:
        logger.exception("dashboard_snippet: AI call failed")
        return None

    if not isinstance(parsed, dict):
        return None

    text = (parsed.get("text") or "").strip()
    if not text:
        return None
    byline = (parsed.get("byline") or "").strip()
    return {"text": text, "byline": byline}


# ── Public write entry point ───────────────────────────────────────────


async def generate_snippet_for_now(
    settings: TerminalSettings,
    *,
    ha_shape: Optional[dict[str, Any]] = None,
    force: bool = False,
) -> Optional[DashboardSnippet]:
    """Generate (or fetch existing) snippet for the terminal's local hour.

    Idempotent on ``(date_local, hour_local)`` -- if a row already exists
    we leave it untouched unless ``force=True``. Returns the (existing
    or newly inserted) ``DashboardSnippet`` row, or ``None`` if AI
    generation failed and no prior row was present.
    """
    tz_name = (settings.timezone or "UTC").strip() or "UTC"
    now_local = _now_local(tz_name)
    date_local, hour_local = _key(now_local)

    async with async_session() as db:
        existing = await _fetch_row(db, date_local, hour_local)
        if existing is not None and not force:
            return existing

        kind = _kind_for_hour(hour_local)
        payload = await _maybe_call_claude(kind, now_local, ha_shape)
        if payload is None:
            return existing

        # The truncation here is a defence-in-depth in case the model
        # ignores the character limits in the system prompt. The
        # renderer has its own line-cap, so a too-long string would
        # just be visually clipped, but we'd rather store something
        # the size of a real headline.
        text = payload["text"][:240]
        byline = (payload.get("byline") or "")[:80]

        if existing is None:
            row = DashboardSnippet(
                date_local=date_local,
                hour_local=hour_local,
                tz_name=tz_name,
                kind=kind,
                text=text,
                byline=byline,
            )
            db.add(row)
        else:
            existing.kind = kind
            existing.text = text
            existing.byline = byline
            existing.tz_name = tz_name
            row = existing
        await db.commit()
        await db.refresh(row)
        return row
