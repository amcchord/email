"""Assemble the ``DayShape`` for the portrait "Day Ahead" e-ink display.

Parallels ``ha_client.fetch_and_shape`` but for the calendar/mail side: it
pulls today's calendar events, the three mail queues (needs-reply /
awaiting / unread), and the slow Home-Assistant house+weather state, then
shapes them into the dict the ``dayahead_editorial`` renderer consumes
(mirrors ``docs`` mockup ``data.js``).

Design notes
------------
* ``now`` is **bucketed to the top of the local hour** so two check-ins
  within the same hour produce byte-identical renders (stable ETag). All
  relative strings (mail age, hero "in 30m") are computed against this
  bucketed instant for the same reason.
* **Never raises.** Each block (events / mail / house) is wrapped so a DB
  or HA hiccup degrades to an empty block instead of failing the render;
  ``terminal.py`` additionally falls back to the clock on any exception.
* Todos are intentionally omitted -- the ``TodoItem`` model has no
  due-date, so the design's "due today / overdue" block can't be built.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, or_, select

from backend.config import get_settings as get_app_settings
from backend.database import async_session
from backend.models.account import GoogleAccount
from backend.models.calendar import CalendarEvent
from backend.models.terminal import TerminalSettings
from backend.services.eink.ha_client import empty_ha_shape, fetch_and_shape
from backend.services.eink.pillow.helpers import fmt_clock, parse_iso, resolve_zone
from backend.services.mail_queues import (
    fetch_awaiting_response,
    fetch_needs_reply,
    fetch_unread_counts,
)

logger = logging.getLogger(__name__)


# ── Time helpers ───────────────────────────────────────────────────────


def _bucketed_now(now_utc: Optional[datetime] = None, *, bucket_sec: int = 3600) -> datetime:
    """Floor `now` (UTC) to the top of the hour for a deterministic render."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    bucket = max(bucket_sec, 1)
    floored = (int(now.timestamp()) // bucket) * bucket
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _minutes(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _ampm(dt: datetime) -> str:
    """12h label with no leading zero, dropping ':00' -> '8', '8:30', '1'."""
    h = ((dt.hour + 11) % 12) + 1
    if dt.minute == 0:
        return str(h)
    return f"{h}:{dt.minute:02d}"


def _compact_age(dt: Optional[datetime], now: datetime) -> str:
    """Short recency badge for the needs-reply rail: '5h', '2d', 'now'."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (now - dt).total_seconds()
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{max(1, round(secs / 60))}m"
    if secs < 86400:
        return f"{round(secs / 3600)}h"
    return f"{round(secs / 86400)}d"


# ── Weather condition mapping ──────────────────────────────────────────

# Map Home Assistant `weather.*` condition strings -> the 5 glyph codes the
# Editorial design draws (sunny / clear / partly / cloudy / rain).
_CONDITION_CODE = {
    "sunny": "sunny",
    "clear": "clear",
    "clear-night": "clear",
    "partlycloudy": "partly",
    "partly-cloudy": "partly",
    "partly-cloudy-day": "partly",
    "partly-cloudy-night": "partly",
    "cloudy": "cloudy",
    "overcast": "cloudy",
    "fog": "cloudy",
    "hazy": "cloudy",
    "windy": "cloudy",
    "windy-variant": "cloudy",
    "rainy": "rain",
    "pouring": "rain",
    "lightning": "rain",
    "lightning-rainy": "rain",
    "hail": "rain",
    "snowy": "rain",
    "snowy-rainy": "rain",
    "exceptional": "cloudy",
}


def _condition_to_code(state: Optional[str]) -> str:
    if not state:
        return "cloudy"
    key = str(state).strip().lower()
    return _CONDITION_CODE.get(key, "cloudy")


def _condition_label(state: Optional[str], code: str) -> str:
    if state:
        return str(state).replace("-", " ").replace("_", " ").strip().upper()
    return code.upper()


def _safe_round(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


# ── Event classification ───────────────────────────────────────────────

_TRAVEL_RE = re.compile(r"flight|train|drive|commute|airport|trip|terminal|gate", re.I)
_FOCUS_RE = re.compile(r"focus|review|deep work|block|writing|1:1|one[- ]on[- ]one", re.I)


def _classify_event(summary: str, location: str, n_attendees: int,
                    has_conf: bool, organizer_self: bool, all_day: bool) -> str:
    """Approximate kind: meeting / personal / focus / travel."""
    hay = f"{summary} {location}"
    if _TRAVEL_RE.search(hay):
        return "travel"
    if n_attendees > 1 or has_conf:
        return "meeting"
    if _FOCUS_RE.search(summary):
        return "focus"
    if organizer_self and n_attendees == 0 and not all_day:
        return "personal"
    return "meeting" if n_attendees >= 1 else "personal"


def _attendee_count(attendees: Any) -> int:
    if isinstance(attendees, list):
        return len(attendees)
    return 0


# ── Account resolution ─────────────────────────────────────────────────


async def _active_account_ids(db, user_id: int) -> list[int]:
    """Active Google account IDs for the terminal owner (strict, like the
    calendar/public paths -- not the AI router's admin-sees-all variant)."""
    result = await db.execute(
        select(GoogleAccount.id).where(
            GoogleAccount.user_id == user_id,
            GoogleAccount.is_active == True,
        )
    )
    return [r[0] for r in result.all()]


# ── Calendar ───────────────────────────────────────────────────────────


def _empty_events() -> list[dict]:
    return []


async def _build_events(db, account_ids: list[int], zone, now_local: datetime) -> list[dict]:
    """Today's events (in `zone`), mapped to the renderer's event dicts."""
    if not account_ids:
        return []
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    today_str = start_local.strftime("%Y-%m-%d")

    timed = and_(
        CalendarEvent.is_all_day == False,
        CalendarEvent.start_time <= end_utc,
        CalendarEvent.end_time >= start_utc,
    )
    allday = and_(
        CalendarEvent.is_all_day == True,
        CalendarEvent.start_date <= today_str,
        CalendarEvent.end_date >= today_str,
    )
    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.account_id.in_(account_ids),
            CalendarEvent.status != "cancelled",
            or_(timed, allday),
        )
        .order_by(
            CalendarEvent.is_all_day.desc(),
            CalendarEvent.start_time.asc().nullslast(),
            CalendarEvent.start_date.asc().nullslast(),
        )
    )
    out: list[dict] = []
    for e in result.scalars().all():
        title = (e.summary or "").strip() or "(no title)"
        loc = (e.location or "").strip()
        n_att = _attendee_count(e.attendees)
        kind = _classify_event(
            e.summary or "", loc, n_att, bool(e.hangout_link),
            bool(e.organizer_self), bool(e.is_all_day),
        )
        if e.is_all_day:
            out.append({
                "start": "00:00", "end": "23:59",
                "startMin": 0, "endMin": 24 * 60,
                "allDay": True, "title": title, "loc": loc,
                "kind": kind, "people": n_att,
            })
            continue
        if e.start_time is None or e.end_time is None:
            continue
        s_local = e.start_time.astimezone(zone)
        en_local = e.end_time.astimezone(zone)
        out.append({
            "start": _hhmm(s_local), "end": _hhmm(en_local),
            "startMin": _minutes(s_local), "endMin": _minutes(en_local),
            "allDay": False, "title": title, "loc": loc,
            "kind": kind, "people": n_att,
        })
    return out


async def _build_tomorrow_first(db, account_ids: list[int], zone, now_local: datetime) -> Optional[dict]:
    """First timed, non-cancelled event after end-of-today (in `zone`)."""
    if not account_ids:
        return None
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start_utc = (start_local + timedelta(days=1)).astimezone(timezone.utc)
    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.account_id.in_(account_ids),
            CalendarEvent.status != "cancelled",
            CalendarEvent.is_all_day == False,
            CalendarEvent.start_time >= tomorrow_start_utc,
        )
        .order_by(CalendarEvent.start_time.asc())
        .limit(1)
    )
    e = result.scalars().first()
    if e is None or e.start_time is None:
        return None
    s_local = e.start_time.astimezone(zone)
    return {
        "start": _ampm(s_local),
        "title": (e.summary or "").strip() or "(no title)",
        "loc": (e.location or "").strip(),
    }


# ── Mail ───────────────────────────────────────────────────────────────


def _empty_mail() -> dict:
    return {"needsReply": {"count": 0, "top": []}, "awaiting": 0, "unread": 0}


# How many emails the wall display surfaces in the needs-reply rail, and how
# many recent candidates the ranker considers.
_NEEDS_REPLY_SHOW = 5
_NEEDS_REPLY_CANDIDATES = 15

# Cache the AI ranking per (user, local hour) so the display is stable within
# the hour (stable ETag) and we make at most one ranking call per hour. Stored
# in Redis so all uvicorn workers agree (an in-process dict would let two
# workers serve different rankings for schedule.json vs image.bmp). A tiny
# in-process map backs it up when Redis is unreachable.
_RANK_CACHE: "dict[tuple[int, str], list[int]]" = {}
_RANK_TTL_SEC = 2 * 60 * 60


def _rank_redis_key(user_id: int, hour_key: str) -> str:
    return f"day_ahead:rank:{user_id}:{hour_key}"


async def _rank_cache_get(user_id: int, hour_key: str) -> Optional[list[int]]:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(get_app_settings().redis_url, decode_responses=True)
        try:
            val = await r.get(_rank_redis_key(user_id, hour_key))
        finally:
            await r.aclose()
        if val:
            return [int(x) for x in val.split(",") if x]
    except Exception:
        return _RANK_CACHE.get((user_id, hour_key))
    return None


async def _rank_cache_set(user_id: int, hour_key: str, ids: list[int]) -> None:
    _RANK_CACHE[(user_id, hour_key)] = ids
    if len(_RANK_CACHE) > 256:
        _RANK_CACHE.clear()
        _RANK_CACHE[(user_id, hour_key)] = ids
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(get_app_settings().redis_url, decode_responses=True)
        try:
            await r.set(_rank_redis_key(user_id, hour_key),
                        ",".join(str(i) for i in ids), ex=_RANK_TTL_SEC)
        finally:
            await r.aclose()
    except Exception:
        pass

_RANK_TOOL = {
    "name": "rank_emails",
    "description": "Pick the emails that most deserve a reply now, in priority order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Chosen email ids, most important first (up to 5).",
            },
        },
        "required": ["ids"],
    },
}

_RANK_SYSTEM = (
    "You triage a busy person's inbox for a glanceable e-ink wall display. "
    "Given emails that are already flagged as needing a reply, choose the ones "
    "that most deserve a reply now. Prioritise real people awaiting a decision "
    "or answer, time-sensitive items, money/commitments, and direct personal or "
    "work threads. Deprioritise newsletters, automated notifications, mass "
    "invitations, and FYIs. Return only the chosen email ids, most important first."
)


async def _rank_needs_reply(rows: list[Any], user_id: int, hour_key: str) -> list[int]:
    """Return up to 5 email ids in importance order.

    Uses the cheap Claude model, cached per (user, hour). Falls back to the
    existing recency order if there's no API key, the call fails, or there
    are already <= 5 candidates.
    """
    ids_all = [r.id for r in rows]
    if len(ids_all) <= _NEEDS_REPLY_SHOW:
        return ids_all[:_NEEDS_REPLY_SHOW]

    id_set = set(ids_all)
    cached = await _rank_cache_get(user_id, hour_key)
    if cached is not None:
        ordered = [i for i in cached if i in id_set]
        return (ordered or ids_all)[:_NEEDS_REPLY_SHOW]

    app = get_app_settings()
    if not getattr(app, "claude_api_key", None):
        return ids_all[:_NEEDS_REPLY_SHOW]

    lines = []
    for r in rows:
        sender = (r.from_name or r.from_address or "").strip()
        subj = (r.subject or "").strip()
        snip = (r.snippet or "").strip().replace("\n", " ")[:140]
        lines.append(f"[{r.id}] from {sender} | {subj} | {snip}")
    user_message = (
        "Emails needing a reply:\n" + "\n".join(lines)
        + f"\n\nReturn the {_NEEDS_REPLY_SHOW} most important ids, most important first."
    )

    try:
        from backend.services.ai import AIService
        from backend.services.ai_models import CHEAP_MODEL

        svc = AIService(model=CHEAP_MODEL)
        parsed, _tokens = await asyncio.wait_for(
            svc._call_claude_tool(
                model=CHEAP_MODEL,
                max_tokens=120,
                messages=[{"role": "user", "content": user_message}],
                tool=_RANK_TOOL,
                system=_RANK_SYSTEM,
            ),
            timeout=8.0,
        )
    except Exception:
        logger.exception("day_ahead: needs-reply ranking failed; using recency order")
        return ids_all[:_NEEDS_REPLY_SHOW]

    chosen: list[int] = []
    if parsed and isinstance(parsed.get("ids"), list):
        for i in parsed["ids"]:
            if isinstance(i, int) and i in id_set and i not in chosen:
                chosen.append(i)
    # Backfill with recency order if the model returned fewer than we show.
    for i in ids_all:
        if i not in chosen:
            chosen.append(i)
    result = chosen[:_NEEDS_REPLY_SHOW]
    await _rank_cache_set(user_id, hour_key, result)
    return result


async def _build_mail(db, account_ids: list[int], now: datetime, *,
                     user_id: int, hour_key: str) -> dict:
    if not account_ids:
        return _empty_mail()
    nr_total, nr_rows = await fetch_needs_reply(db, account_ids, limit=_NEEDS_REPLY_CANDIDATES)
    aw_total, _ = await fetch_awaiting_response(db, account_ids, limit=1)
    unread_total, _ = await fetch_unread_counts(db, account_ids)

    order = await _rank_needs_reply(nr_rows, user_id, hour_key)
    by_id = {r.id: r for r in nr_rows}
    chosen = [by_id[i] for i in order if i in by_id]
    top = [
        {
            "from": (r.from_name or r.from_address or "").strip(),
            "subj": (r.subject or "").strip() or "(no subject)",
            "age": _compact_age(r.date, now),
        }
        for r in chosen[:_NEEDS_REPLY_SHOW]
    ]
    return {
        "needsReply": {"count": int(nr_total), "top": top},
        "awaiting": int(aw_total),
        "unread": int(unread_total),
    }


# ── House + weather (Home Assistant) ───────────────────────────────────


def _empty_weather() -> dict:
    return {"now": {"temp": None, "code": "cloudy", "label": ""},
            "hi": None, "lo": None, "sunrise": None, "sunset": None, "forecast": []}


def _empty_house() -> dict:
    return {"temps": {}, "people": [], "advisory": ""}


def _build_weather(ha: dict, zone) -> dict:
    w = ha.get("weather") or {}
    temps = ha.get("temps") or {}
    daily = ((w.get("forecast") or {}).get("daily")) or []

    code = _condition_to_code(w.get("state"))
    now_temp = _safe_round(temps.get("outdoor"))
    if now_temp is None:
        now_temp = _safe_round(w.get("temperature"))

    today = daily[0] if daily else {}
    hi = _safe_round(today.get("temperature")) if today else None
    lo = _safe_round(today.get("templow")) if today else None

    forecast: list[dict] = []
    for slot in daily[1:4]:
        dt = parse_iso(slot.get("datetime"))
        dow = dt.astimezone(zone).strftime("%a").upper()[:3] if dt else ""
        forecast.append({
            "dow": dow,
            "code": _condition_to_code(slot.get("condition")),
            "hi": _safe_round(slot.get("temperature")),
            "lo": _safe_round(slot.get("templow")),
        })

    sun = ha.get("sun") or {}
    sunrise = sun.get("nextRising")
    sunset = sun.get("nextSetting")
    return {
        "now": {"temp": now_temp, "code": code,
                "label": _condition_label(w.get("state"), code)},
        "hi": hi, "lo": lo,
        "sunrise": fmt_clock(sunrise, tz=zone) if sunrise else None,
        "sunset": fmt_clock(sunset, tz=zone) if sunset else None,
        "forecast": forecast,
    }


def _build_house(ha: dict) -> dict:
    temps = ha.get("temps") or {}
    people = [
        {"name": (p.get("name") or "").strip(), "home": (p.get("state") == "home")}
        for p in (ha.get("people") or [])
        if p.get("name")
    ]
    advisory = ""
    if (ha.get("garage") or {}).get("state") == "open":
        advisory = "Garage open"
    elif ha.get("openWindows"):
        advisory = "Windows open"
    return {
        "temps": {
            "outdoor": _safe_round(temps.get("outdoor")),
            "first": _safe_round(temps.get("first")),
            "second": _safe_round(temps.get("second")),
            "third": _safe_round(temps.get("third")),
            "basement": _safe_round(temps.get("basement")),
        },
        "people": people,
        "advisory": advisory,
    }


# ── Public entry point ─────────────────────────────────────────────────


async def assemble_day_shape(
    settings: TerminalSettings,
    *,
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the DayShape dict for `settings`. Never raises."""
    tz_name = (settings.timezone or "UTC").strip() or "UTC"
    zone = resolve_zone(tz_name)
    bnow = _bucketed_now(now_utc)
    now_local = bnow.astimezone(zone)
    hour_key = now_local.strftime("%Y-%m-%dT%H")

    date_block = {
        "weekday": now_local.strftime("%A").upper(),
        "monthDay": now_local.strftime("%B %-d").upper(),
        "year": now_local.strftime("%Y"),
        "dow3": now_local.strftime("%a").upper()[:3],
    }

    # Calendar + mail (DB).
    events: list[dict] = _empty_events()
    tomorrow_first: Optional[dict] = None
    mail = _empty_mail()
    try:
        async with async_session() as db:
            account_ids = await _active_account_ids(db, settings.user_id)
            try:
                events = await _build_events(db, account_ids, zone, now_local)
                tomorrow_first = await _build_tomorrow_first(db, account_ids, zone, now_local)
            except Exception:
                logger.exception("day_ahead: calendar assembly failed")
            try:
                mail = await _build_mail(db, account_ids, bnow,
                                         user_id=settings.user_id, hour_key=hour_key)
            except Exception:
                logger.exception("day_ahead: mail assembly failed")
    except Exception:
        logger.exception("day_ahead: DB session failed; events/mail empty")

    # House + weather (Home Assistant).
    weather = _empty_weather()
    house = _empty_house()
    try:
        ha = await fetch_and_shape(settings)
        if ha is None:
            ha = empty_ha_shape()
        weather = _build_weather(ha, zone)
        house = _build_house(ha)
    except Exception:
        logger.exception("day_ahead: HA assembly failed; weather/house empty")

    return {
        "tz": tz_name,
        "now_utc": bnow.isoformat(),
        "nowMin": _minutes(now_local),
        "asOf": fmt_clock(now_local),
        "date": date_block,
        "weather": weather,
        "events": events,
        "mail": mail,
        "house": house,
        "tomorrow": {"first": tomorrow_first},
    }
