"""Sauna heat-up forecast for the e-ink dashboard, read from Home Assistant.

Home Assistant runs the model (``custom_components/sauna_forecast`` in the
HomeAssistant project, the same code path as its Sauna panel) and publishes the
result as ``sensor.sauna_heat_forecast``. The attribute contract is in that
project's ``SAUNA_CONTROLS_RUNBOOK.md``. The screens hold no model of their own,
so a refit or fan-plan change there reaches them with no change here.

This module checks the sensor is current and reshapes it for the cards. "Ready"
means the room sensor reaches 165°F. "185°F" means the controller's thermostat
reaches it. Times passed in and out are epoch seconds or ISO-8601 strings.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

READY_F = 165
TARGET_F = 185
SENSOR = "sensor.sauna_heat_forecast"
FAN_STATES = frozenset({"running", "due", "planned", "done", "skipped", "optional"})
# The sensor refreshes every minute while heating; older than this, HA has stopped
# updating it and its minutes no longer describe the room.
STALE_SECONDS = 180


def _epoch(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _whole(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(value)


def from_sensor(
    entity: Optional[dict[str, Any]],
    room_history: Optional[list[dict[str, float]]],
    now: float,
) -> Optional[dict[str, Any]]:
    """The card's forecast from the sensor, or None when it has none to give.

    `room_history` is room readings ``{"t", "v"}``; the chart draws those since the
    session started. Minutes and the curve are moved from the sensor's
    ``computed_at`` to `now`, so a reading a minute old still lines up.
    """
    attrs = (entity or {}).get("attributes")
    if not isinstance(attrs, dict) or attrs.get("active") is not True or attrs.get("reason"):
        return None
    computed = _epoch(attrs.get("computed_at"))
    if computed is None:
        return None
    age = now - computed
    if age > STALE_SECONDS:
        logger.warning("Sauna forecast sensor is %.0f s old; rendering the card without it", age)
        return None
    shift = max(0, round(age / 60))

    def minutes(key: str) -> Optional[int]:
        value = _whole(attrs.get(key))
        return None if value is None else max(0, value - shift)

    curve = attrs.get("room_curve")
    if not isinstance(curve, list) or not all(_whole(v) is not None for v in curve):
        curve = []
    start = _epoch(attrs.get("session_start"))
    history = [
        {"minutes": round((row["t"] - now) / 60, 1), "value": row["v"]}
        for row in room_history or []
        if start is not None and start <= row["t"] <= now
    ]
    fan_state = attrs.get("fan_state")
    return {
        "modelVersion": attrs.get("model_version"),
        "readyReached": attrs.get("ready_reached") is True,
        "readyAt": attrs.get("ready_at"),
        "readyInMinutes": minutes("ready_in_minutes"),
        "targetReached": attrs.get("target_reached") is True,
        "targetAt": attrs.get("target_at"),
        "targetInMinutes": minutes("target_in_minutes"),
        "fan": {
            "state": fan_state if fan_state in FAN_STATES else None,
            "auto": attrs.get("auto_fan") is True,
            "at": attrs.get("fan_at"),
            "minutesLeft": minutes("fan_minutes_left"),
        },
        "fanInMinutes": minutes("fan_in_minutes"),
        "roomCurve": curve[shift:],
        "roomHistory": history,
        "sessionStart": attrs.get("session_start"),
        "sessionEndsBeforeReadyAt": attrs.get("session_ends_before_ready_at"),
    }
