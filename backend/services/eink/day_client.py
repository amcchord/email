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
import json
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
from backend.services.eink.pillow.helpers import (
    fmt_clock,
    forecast_day_date,
    resolve_zone,
)
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


# How many needs-reply emails the priorities curator considers, and how many
# we keep in the mail block's recency list.
_NEEDS_REPLY_SHOW = 5
_NEEDS_REPLY_CANDIDATES = 15


async def _build_mail(db, account_ids: list[int], now: datetime) -> tuple[dict, list[Any]]:
    """Return ``(mail_block, needs_reply_rows)``.

    The mail block still powers the calm-edition lead (needs-reply count,
    awaiting, unread); the raw rows feed the priorities curator below. No AI
    call happens here -- ``top`` is plain recency order.
    """
    if not account_ids:
        return _empty_mail(), []
    nr_total, nr_rows = await fetch_needs_reply(db, account_ids, limit=_NEEDS_REPLY_CANDIDATES)
    aw_total, _ = await fetch_awaiting_response(db, account_ids, limit=1)
    unread_total, _ = await fetch_unread_counts(db, account_ids)

    top = [
        {
            "from": (r.from_name or r.from_address or "").strip(),
            "subj": (r.subject or "").strip() or "(no subject)",
            "age": _compact_age(r.date, now),
        }
        for r in nr_rows[:_NEEDS_REPLY_SHOW]
    ]
    mail = {
        "needsReply": {"count": int(nr_total), "top": top},
        "awaiting": int(aw_total),
        "unread": int(unread_total),
    }
    return mail, nr_rows


# ── Priorities ("what matters now") ────────────────────────────────────
#
# The bottom-left rail used to be a raw needs-reply list. It's now a curated
# "most important things for the next few hours" list spanning calendar prep
# and email. A capable model distils it once per local hour; the result is
# cached in Redis so every render within the hour is byte-identical (stable
# ETag) and we make at most one call per user per hour. Falls back to a
# deterministic merge of imminent meetings + recent needs-reply email when
# there's no API key or the call fails.

# Opus is the quality-first agentic choice for the hourly priorities pass;
# Fable is reserved for harder long-horizon work and Luna for bulk processing.
_PRIORITIES_MODEL = "claude-opus-5"
_PRIORITIES_SHOW = 5
_PRIORITIES_WINDOW_MIN = 4 * 60
_PRIORITIES_KINDS = {"prep", "reply", "review", "decision", "personal", "travel"}

_PRIO_CACHE: "dict[tuple[int, str], list[dict]]" = {}
_PRIO_TTL_SEC = 2 * 60 * 60


def _empty_priorities() -> dict:
    return {"items": []}


def _prio_redis_key(user_id: int, hour_key: str) -> str:
    return f"day_ahead:prio:{user_id}:{hour_key}"


async def _prio_cache_get(user_id: int, hour_key: str) -> Optional[list[dict]]:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(get_app_settings().redis_url, decode_responses=True)
        try:
            val = await r.get(_prio_redis_key(user_id, hour_key))
        finally:
            await r.aclose()
        if val:
            data = json.loads(val)
            if isinstance(data, list):
                return data
    except Exception:
        return _PRIO_CACHE.get((user_id, hour_key))
    return None


async def _prio_cache_set(user_id: int, hour_key: str, items: list[dict]) -> None:
    _PRIO_CACHE[(user_id, hour_key)] = items
    if len(_PRIO_CACHE) > 256:
        _PRIO_CACHE.clear()
        _PRIO_CACHE[(user_id, hour_key)] = items
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(get_app_settings().redis_url, decode_responses=True)
        try:
            await r.set(_prio_redis_key(user_id, hour_key), json.dumps(items), ex=_PRIO_TTL_SEC)
        finally:
            await r.aclose()
    except Exception:
        pass


def _clock_label(minute: int) -> str:
    """'2 PM' / '2:30 PM' from minutes-since-local-midnight."""
    h24 = (minute // 60) % 24
    m = minute % 60
    h = ((h24 + 11) % 12) + 1
    mer = "AM" if h24 < 12 else "PM"
    return f"{h} {mer}" if m == 0 else f"{h}:{m:02d} {mer}"


def _upcoming_in_window(events: list[dict], now_min: int, window_min: int) -> list[dict]:
    """Timed events happening now or starting within ``window_min``, in order."""
    out = [
        e for e in (events or [])
        if not e.get("allDay")
        and int(e.get("endMin", 0)) > now_min
        and int(e.get("startMin", 0)) <= now_min + window_min
    ]
    out.sort(key=lambda e: int(e.get("startMin", 0)))
    return out


def _fallback_priorities(upcoming: list[dict], nr_rows: list[Any]) -> list[dict]:
    """Deterministic priorities: imminent meetings (prep) then recent replies."""
    items: list[dict] = []
    for e in upcoming:
        kind = e.get("kind")
        title = (e.get("title") or "").strip() or "Untitled event"
        loc = (e.get("loc") or "").strip()
        people = int(e.get("people") or 0)
        when = _clock_label(int(e.get("startMin", 0)))
        if kind == "travel":
            pkind, ptitle = "travel", title
        elif kind == "personal":
            pkind, ptitle = "personal", title
        else:
            pkind, ptitle = "prep", f"Prep: {title}"
        if loc:
            detail = f"{when} \u00b7 {loc}"
        elif people:
            detail = f"{when} \u00b7 {people} on invite"
        else:
            detail = when
        items.append({"title": ptitle, "detail": detail, "kind": pkind})
        if len(items) >= _PRIORITIES_SHOW:
            return items
    for r in nr_rows:
        sender = (getattr(r, "from_name", None) or getattr(r, "from_address", None) or "").strip()
        subj = (getattr(r, "subject", None) or "").strip() or "(no subject)"
        items.append({
            "title": f"Reply: {sender}" if sender else "Reply needed",
            "detail": subj,
            "kind": "reply",
        })
        if len(items) >= _PRIORITIES_SHOW:
            break
    return items[:_PRIORITIES_SHOW]


def _sanitize_priorities(parsed: Optional[dict]) -> list[dict]:
    """Coerce the model's tool output into clean item dicts (defensive)."""
    if not parsed or not isinstance(parsed.get("items"), list):
        return []
    out: list[dict] = []
    for it in parsed["items"]:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        kind = (it.get("kind") or "").strip().lower()
        if kind not in _PRIORITIES_KINDS:
            kind = "review"
        out.append({
            "title": title[:80],
            "detail": (it.get("detail") or "").strip()[:90],
            "kind": kind,
        })
        if len(out) >= _PRIORITIES_SHOW:
            break
    return out


_PRIORITIES_TOOL = {
    "name": "pick_priorities",
    "description": "Choose the few most important things to focus on in the next few hours.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": f"Up to {_PRIORITIES_SHOW} items, most important first.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "One concrete action, scannable, ~36 chars max. e.g. 'Prep for the board review'.",
                        },
                        "detail": {
                            "type": "string",
                            "description": "Short supporting context, ~44 chars max. e.g. '2 PM \u00b7 6 on invite' or 'from Dana Wu'.",
                        },
                        "kind": {
                            "type": "string",
                            "enum": sorted(_PRIORITIES_KINDS),
                            "description": "prep=meeting prep, reply=email reply, review/decision=think or decide, personal, travel.",
                        },
                    },
                    "required": ["title", "kind"],
                },
            },
        },
        "required": ["items"],
    },
}

_PRIORITIES_SYSTEM = (
    "You are a sharp chief of staff curating a glanceable e-ink wall display. "
    "From the person's upcoming calendar events and the emails awaiting their "
    "reply, choose the few things they should actually be thinking about or "
    "acting on in the next few hours, most important first. Distil hard: each "
    "item is one concrete, specific action -- 'Prep for the 2 PM board review', "
    "'Decide on Dana's contract deadline' -- never a vague restatement. Favour "
    "prep for imminent meetings, time-sensitive decisions, commitments to real "
    "people, and money matters. Ignore newsletters, automated notifications, "
    "and FYIs. Keep titles short and scannable; put times, names, or places in "
    "the detail."
)


async def _build_priorities(
    events: list[dict],
    nr_rows: list[Any],
    now_local: datetime,
    *,
    user_id: int,
    hour_key: str,
) -> dict:
    """Curate up to five priorities for the next few hours. Never raises."""
    now_min = _minutes(now_local)
    upcoming = _upcoming_in_window(events, now_min, _PRIORITIES_WINDOW_MIN)
    if not upcoming and not nr_rows:
        return _empty_priorities()

    cached = await _prio_cache_get(user_id, hour_key)
    if cached is not None:
        return {"items": cached}

    fallback = _fallback_priorities(upcoming, nr_rows)
    if not getattr(get_app_settings(), "claude_api_key", None):
        return {"items": fallback}

    ev_lines = [
        f"- {_clock_label(int(e.get('startMin', 0)))} | {(e.get('title') or '').strip()} | "
        f"loc={(e.get('loc') or '').strip() or '-'} | attendees={int(e.get('people') or 0)} | "
        f"kind={e.get('kind')}"
        for e in upcoming
    ]
    em_lines = []
    for r in nr_rows:
        sender = (getattr(r, "from_name", None) or getattr(r, "from_address", None) or "").strip()
        subj = (getattr(r, "subject", None) or "").strip()
        snip = (getattr(r, "snippet", None) or "").strip().replace("\n", " ")[:160]
        em_lines.append(f"- from {sender or '(unknown)'} | {subj} | {snip}")

    user_message = (
        f"Local time: {now_local.strftime('%A %-I:%M %p')}. "
        f"Horizon: the next {_PRIORITIES_WINDOW_MIN // 60} hours.\n\n"
        "Upcoming calendar events:\n"
        + ("\n".join(ev_lines) if ev_lines else "(none)")
        + "\n\nEmails awaiting a reply:\n"
        + ("\n".join(em_lines) if em_lines else "(none)")
        + f"\n\nReturn the {_PRIORITIES_SHOW} most important things, most important first."
    )

    try:
        from backend.services.ai import AIService

        svc = AIService(model=_PRIORITIES_MODEL)
        parsed, _tokens = await asyncio.wait_for(
            svc._call_claude_tool(
                model=_PRIORITIES_MODEL,
                max_tokens=700,
                messages=[{"role": "user", "content": user_message}],
                tool=_PRIORITIES_TOOL,
                system=_PRIORITIES_SYSTEM,
            ),
            timeout=20.0,
        )
    except Exception:
        logger.exception("day_ahead: priorities generation failed; using fallback")
        return {"items": fallback}

    items = _sanitize_priorities(parsed) or fallback
    await _prio_cache_set(user_id, hour_key, items)
    return {"items": items}


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
        # forecast_day_date treats daily slots as day markers so a UTC- or
        # local-midnight datetime can't tz-shift into the previous weekday.
        slot_date = forecast_day_date(slot.get("datetime"), zone)
        dow = slot_date.strftime("%a").upper()[:3] if slot_date else ""
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
    nr_rows: list[Any] = []
    try:
        async with async_session() as db:
            account_ids = await _active_account_ids(db, settings.user_id)
            try:
                events = await _build_events(db, account_ids, zone, now_local)
                tomorrow_first = await _build_tomorrow_first(db, account_ids, zone, now_local)
            except Exception:
                logger.exception("day_ahead: calendar assembly failed")
            try:
                mail, nr_rows = await _build_mail(db, account_ids, bnow)
            except Exception:
                logger.exception("day_ahead: mail assembly failed")
    except Exception:
        logger.exception("day_ahead: DB session failed; events/mail empty")

    # Priorities ("what matters now") -- AI curation over events + mail. Runs
    # outside the DB session (no DB needed) so the up-to-20s call never holds a
    # connection open. Cached per local hour for a stable ETag.
    priorities = _empty_priorities()
    try:
        priorities = await _build_priorities(
            events, nr_rows, now_local,
            user_id=settings.user_id, hour_key=hour_key,
        )
    except Exception:
        logger.exception("day_ahead: priorities assembly failed")

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
        "priorities": priorities,
        "house": house,
        "tomorrow": {"first": tomorrow_first},
    }
