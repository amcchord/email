"""Sauna heat-up forecast for the e-ink dashboard.

Python port of the model in the Home Assistant Sauna panel
(``www/sauna-room-panel.js`` in the HomeAssistant project; accuracy and refit
steps are in its ``SAUNA_CONTROLS_RUNBOOK.md``). That forecast runs only in the
browser and publishes no sensor, so the panel and this module each compute it.
Refit the panel first, then copy the same coefficients into ``_MODEL``.

"Ready" means the room sensor reaches 165°F. "185°F" means the controller's
thermostat reaches it: the thermostat runs about 35°F above the room during
heat-up, and without a fan run the room levels off near 176°F. All times are
epoch seconds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

READY_F = 165
TARGET_F = 185

_MINUTE = 60.0
_THERMOSTAT_RATE = (1.7909, 1.007, 0.001, -0.011, 0, 0.2652)
_ROOM_RATE = (0.473, 0.3909, 0.0393, -0.0456, 0.0047, 0.0971)
# During a fan run the room drifts toward `r` at rate `k`, and the thermostat
# settles at `t` + 0.6 x room within a few minutes.
_FAN = {
    "low": {"k": 0.0125, "r": 165, "t": 86},
    "medium": {"k": 0.0125, "r": 142, "t": 72},
    "high": {"k": 0.02, "r": 100, "t": 58},
}
_STORED_HEAT_MINUTES = 12
_WARMUP_MINUTES = 5
FAN_RUN_MINUTES = 10
_FAN_ROOM_LIMIT = 160
_DEFAULT_OUTDOOR = 45
_HORIZON_MINUTES = 240
# How much of the projection the card's chart can use, one reading per minute.
_CURVE_MINUTES = 180


@dataclass(frozen=True)
class Projection:
    thermostats: list[float]
    rooms: list[float]
    fan_at: Optional[int]


@dataclass(frozen=True)
class FanRun:
    start: float
    end: Optional[float]
    speed: str


@dataclass(frozen=True)
class Session:
    start: float
    runs: list[FanRun] = field(default_factory=list)
    stored_heat: float = 0.0
    fan_done: bool = False
    ready_at: Optional[float] = None
    target_at: Optional[float] = None


def _rate(c: tuple, heat: float, thermostat: float, room: float, outdoor: float, stored: float) -> float:
    return c[0] * heat + c[1] + c[2] * thermostat + c[3] * room + c[4] * outdoor + c[5] * stored


def _round(value: float) -> int:
    """Round halves up, as the panel's ``Math.round`` does."""
    return math.floor(value + 0.5)


def _first(series: list[float], level: float) -> Optional[int]:
    return next((i for i, value in enumerate(series) if value >= level), None)


def simulate(
    *,
    thermostat: float,
    room: float,
    outdoor: float,
    target: float = TARGET_F,
    age: float = 0,
    elements: float = 0,
    stored_heat: float = 0,
    fan_left: float = 0,
    fan_speed: str = "medium",
    fan_done: bool = False,
    plan_fan: bool = True,
    minutes: int = _HORIZON_MINUTES,
) -> Projection:
    """Step the fitted rates forward one minute at a time from current readings."""
    thermostats = [thermostat]
    rooms = [room]
    stored = stored_heat
    hold = elements == 0
    left = fan_left
    speed = fan_speed
    done = fan_done
    fan_at: Optional[int] = None
    for k in range(minutes):
        if (plan_fan and not done and left <= 0
                and thermostat >= min(target, TARGET_F) and room < _FAN_ROOM_LIMIT):
            left, speed, done, fan_at = FAN_RUN_MINUTES, "medium", True, k
        if hold:
            if thermostat < target - 1.5:
                hold = False
        elif thermostat >= target + 2:
            hold = True
        warm = age + k >= _WARMUP_MINUTES
        fan = (_FAN.get(speed) or _FAN["medium"]) if left > 0 else None
        if not warm:
            heat = 0.0
        elif fan:
            heat = 1.0
        elif hold:
            heat = 0.0
        else:
            heat = 1.0 if thermostat < target - 2 else 0.75
        if fan:
            d_thermostat = (fan["t"] + 0.6 * room - thermostat) / 3
            d_room = -fan["k"] * (room - fan["r"])
        else:
            d_thermostat = _rate(_THERMOSTAT_RATE, heat, thermostat, room, outdoor, stored)
            d_room = _rate(_ROOM_RATE, heat, thermostat, room, outdoor, stored)
        stored = stored * (1 - 1 / _STORED_HEAT_MINUTES) + (heat if fan else 0)
        if fan:
            left -= 1
        thermostat += d_thermostat
        room += d_room
        thermostats.append(thermostat)
        rooms.append(room)
    return Projection(thermostats, rooms, fan_at)


def session_facts(history: dict[str, list[dict[str, Any]]], now: float) -> Optional[Session]:
    """What this session has done so far. Outages don't end a session."""
    start: Optional[float] = None
    runs: list[dict[str, Any]] = []
    open_run: Optional[dict[str, Any]] = None
    heating = False
    for row in history.get("climate") or []:
        state = row.get("s")
        if state not in ("heat", "off"):
            continue
        heat = state == "heat"
        if heat and not heating:
            start, runs, open_run = row["t"], [], None
        fan = row.get("fan")
        on = heat and fan and fan != "off"
        if on and not open_run:
            open_run = {"start": row["t"], "end": None, "speed": fan}
        elif on:
            open_run["speed"] = fan
        elif open_run:
            open_run["end"] = row["t"]
            runs.append(open_run)
            open_run = None
        if not heat:
            start = None
        heating = heat
    if open_run:
        runs.append(open_run)
    if start is None:
        return None

    stored = 0.0
    t = start
    while t < now:
        on = any(t >= r["start"] and t < (r["end"] if r["end"] is not None else now) for r in runs)
        stored = stored * (1 - 1 / _STORED_HEAT_MINUTES) + (1 if on else 0)
        t += _MINUTE

    def reached(rows: list[dict[str, Any]], level: float) -> Optional[float]:
        return next((r["t"] for r in rows if r["t"] >= start and r["v"] >= level), None)

    return Session(
        start=start,
        runs=[FanRun(r["start"], r["end"], r["speed"]) for r in runs],
        stored_heat=stored,
        fan_done=any(r["start"] - start > 15 * _MINUTE for r in runs),
        ready_at=reached(history.get("room") or [], READY_F),
        target_at=reached(history.get("thermostat") or [], TARGET_F),
    )


def _iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def forecast_heating(
    *,
    thermostat: float,
    room: float,
    outdoor: Optional[float],
    target: Optional[float],
    elements: Optional[float],
    session: Optional[Session],
    session_minutes: Optional[float],
    timer_end: Optional[float],
    now: float,
) -> dict[str, Any]:
    """JSON-safe forecast for an active session, as the panel's forecast card."""
    out = outdoor if outdoor is not None and math.isfinite(outdoor) else _DEFAULT_OUTDOOR
    goal = target if target is not None and 104 <= target <= 212 else TARGET_F
    run = next((r for r in (session.runs if session else []) if r.end is None), None)
    fan_left = 0
    if run:
        ends = timer_end if timer_end is not None else run.start + FAN_RUN_MINUTES * _MINUTE
        fan_left = max(1, _round((ends - now) / _MINUTE))
    projection = simulate(
        thermostat=thermostat,
        room=room,
        outdoor=out,
        target=goal,
        elements=elements or 0,
        age=(now - session.start) / _MINUTE if session else 0,
        stored_heat=session.stored_heat if session else 0,
        fan_left=fan_left,
        fan_speed=run.speed if run else "medium",
        fan_done=session.fan_done if session else False,
    )

    ready_at = session.ready_at if session and session.ready_at is not None else None
    if ready_at is None and room >= READY_F:
        ready_at = now
    target_at = session.target_at if session and session.target_at is not None else None
    if target_at is None and thermostat >= TARGET_F:
        target_at = now
    ready_in = None if ready_at is not None else _first(projection.rooms, READY_F)
    target_in = None if target_at is not None else _first(projection.thermostats, TARGET_F)

    def when(minutes: Optional[int]) -> Optional[float]:
        return None if minutes is None else now + minutes * _MINUTE

    past_runs = [r for r in (session.runs if session else []) if r.start - session.start > 15 * _MINUTE]
    if run:
        fan = {"state": "running", "minutesLeft": fan_left}
    elif projection.fan_at == 0:
        fan = {"state": "due"}
    elif projection.fan_at is not None:
        fan = {"state": "planned", "at": _iso(when(projection.fan_at))}
    elif past_runs:
        fan = {"state": "done", "at": _iso(past_runs[-1].start)}
    else:
        fan = {"state": "optional"}

    session_end = None
    if session and session_minutes and session_minutes > 0:
        session_end = session.start + session_minutes * _MINUTE
    ready_eta = when(ready_in)
    return {
        "readyReached": ready_at is not None,
        "readyAt": _iso(ready_at if ready_at is not None else ready_eta),
        "readyInMinutes": ready_in,
        "targetReached": target_at is not None,
        "targetAt": _iso(target_at if target_at is not None else when(target_in)),
        "targetInMinutes": target_in,
        "fan": fan,
        "fanInMinutes": projection.fan_at,
        "roomCurve": [round(value, 1) for value in projection.rooms[:_CURVE_MINUTES + 1]],
        "sessionEndsBeforeReadyAt": (
            _iso(session_end)
            if session_end is not None and ready_eta is not None and ready_eta > session_end
            else None
        ),
    }
