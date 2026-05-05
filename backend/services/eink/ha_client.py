"""Home Assistant REST client + state shaper for the e-ink dashboard.

This is a Python port of `docs/design/ha-data.js` -- it speaks to HA's
`/api/states` endpoint with a long-lived bearer token, then reshapes the
states list into the exact `HAShape` documented in
`docs/design/HANDOFF.md` Sec 4.1 so the React designs render unchanged.

Hard-codes the Cambridge entity IDs from the handoff doc. Missing entities
just become `None`/empty -- the React designs already render gracefully
when blocks are absent (handoff Sec 11).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from backend.models.terminal import TerminalSettings
from backend.utils.security import decrypt_value

logger = logging.getLogger(__name__)


# ── HA REST fetch ──────────────────────────────────────────────────────


class HAClientError(Exception):
    """Raised when HA cannot be reached or returns a bad response."""


async def fetch_ha_states(
    url: str,
    token: str,
    *,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """GET {url}/api/states with Authorization: Bearer <token>.

    Returns the raw JSON list of state dicts. Raises HAClientError on
    network failure, non-200 response, or missing/malformed JSON.
    """
    if not url or not token:
        raise HAClientError("Home Assistant URL or token not configured")
    base = url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base}/api/states", headers=headers)
    except httpx.RequestError as e:
        raise HAClientError(f"network error: {e}") from e
    if resp.status_code == 401:
        raise HAClientError("HA rejected the access token (401)")
    if resp.status_code != 200:
        raise HAClientError(f"HA returned HTTP {resp.status_code}")
    try:
        data = resp.json()
    except Exception as e:
        raise HAClientError(f"HA response was not JSON: {e}") from e
    if not isinstance(data, list):
        raise HAClientError("HA response was not a list of states")
    return data


# ── State shaping (port of ha-data.js) ─────────────────────────────────


# Hard-coded entity IDs from docs/design/HANDOFF.md Sec 4.2. These can be
# wrong for your install -- missing entities just render as null/empty.
_WEATHER_ENTITY_ID = "weather.forecast_home"

_POOL_ID = "water_heater.53_55_raymond_pool"
_POOL_AIR = "sensor.53_55_raymond_air_sensor"
_POOL_HEAT = "binary_sensor.53_55_raymond_heat_exchanger"
_POOL_PUMP = "binary_sensor.53_55_raymond_filter_pump"
_POOL_SCHED = "binary_sensor.53_55_raymond_schedule_pool"
_POOL_FREEZE = "binary_sensor.53_55_raymond_freeze"

_SAUNA_ID = "climate.saunum_leil"
_SAUNA_DURATION = "number.saunum_leil_sauna_duration"
_SAUNA_HEATERS = "sensor.saunum_leil_heater_elements_active"
_SAUNA_DOOR = "binary_sensor.saunum_leil_door"
_SAUNA_LIGHT = "light.saunum_leil_light"
_SAUNA_ROOM_TEMP = "sensor.usl_environmental_temperature_2"
_SAUNA_ROOM_HUM = "sensor.usl_environmental_humidity_2"

_WASHER_STATUS = "sensor.washer_current_status"
_WASHER_OP = "select.washer_operation"
_WASHER_REMAINING = "sensor.washer_remaining_time"
_WASHER_NOTIF = "event.washer_notification"
_WASHER_POWER = "switch.washer_power"
_WASHER_CYCLES = "sensor.washer_cycles"
_WASHER_ENERGY = "sensor.washer_energy_this_month"

_DW_STATE = "sensor.dishwasher_operation_state"
_DW_PROG = "select.dishwasher_selected_program"
_DW_PROGRESS = "sensor.dishwasher_program_progress"
_DW_FINISH = "sensor.dishwasher_program_finish_time"
_DW_DOOR = "sensor.dishwasher_door"
_DW_POWER = "switch.dishwasher_power"
_DW_CONN = "binary_sensor.dishwasher_connectivity"

_CLIMATE_BASEMENT = "climate.basement"
_CLIMATE_FIRST = "climate.first_floor"
_CLIMATE_SECOND = "climate.second_floor"
_CLIMATE_THIRD = "climate.third_floor"
_CLIMATE_RADIANT_MAIN = "climate.nest_learning_thermostat_4th_gen"
_CLIMATE_RADIANT_APT = "climate.nest_learning_thermostat_4th_gen_3"

_TEMP_BASEMENT = "sensor.basement_temperature"
_TEMP_FIRST = "sensor.first_floor_temperature"
_TEMP_SECOND = "sensor.second_floor_temperature"
_TEMP_THIRD = "sensor.third_floor_temperature"
_TEMP_OUTDOOR = "sensor.weather_station_outdoor_temperature"

_GARAGE_ID = "cover.smart_garage_door_25090565132271610701c4e7ae20a653_garage"

_SUN_ID = "sun.sun"
_SUN_DAWN = "sensor.sun_next_dawn"
_SUN_DUSK = "sensor.sun_next_dusk"
_SUN_RISING = "sensor.sun_next_rising"
_SUN_SETTING = "sensor.sun_next_setting"


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "unknown" or v == "unavailable":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    f = _to_float(v)
    if f is None:
        return None
    return int(round(f))


def _floor_of(entity_id: str) -> Optional[str]:
    """Heuristic floor classification matching the JS ha-data.js helper."""
    if re.match(r"^climate\.(1st|first)", entity_id):
        return "first"
    if re.match(r"^climate\.(2nd|second)", entity_id):
        return "second"
    if re.match(r"^climate\.(3rd|third)", entity_id):
        return "third"
    if re.match(r"^climate\.(bsmt|basement)", entity_id):
        return "basement"
    if re.search(r"above_garage|tree_house|workshop|gym|master_bedroom", entity_id):
        return "other"
    return None


def shape_ha_state(
    states: list[dict[str, Any]],
    *,
    fetched_at: Optional[datetime] = None,
    weather_entity_id: Optional[str] = None,
) -> dict[str, Any]:
    """Reshape `/api/states` into the HAShape consumed by the React designs.

    `weather_entity_id` overrides the default; the JS shape stores this as a
    top-level pointer in lastState.json. Defaults to `weather.forecast_home`
    if the install has it, otherwise the first `weather.*` entity found.
    """
    fetched_at = fetched_at or datetime.now(timezone.utc)
    idx = {s.get("entity_id"): s for s in states if s.get("entity_id")}

    def get(eid: str) -> Optional[dict]:
        return idx.get(eid)

    def state_str(eid: str) -> Optional[str]:
        s = get(eid)
        return s.get("state") if s else None

    def state_num(eid: str) -> Optional[float]:
        s = get(eid)
        if not s:
            return None
        return _to_float(s.get("state"))

    def attr(eid: str, key: str) -> Any:
        s = get(eid)
        if not s:
            return None
        return (s.get("attributes") or {}).get(key)

    # ── Weather ────────────────────────────────────────────────────
    wid = weather_entity_id or _WEATHER_ENTITY_ID
    w = get(wid)
    if w is None:
        # Fall back to the first weather.* entity available.
        for s in states:
            if (s.get("entity_id") or "").startswith("weather."):
                w = s
                break
    weather: Optional[dict] = None
    if w:
        a = w.get("attributes") or {}
        weather = {
            "state": w.get("state"),
            "temperature": a.get("temperature"),
            "humidity": a.get("humidity"),
            "windSpeed": a.get("wind_speed"),
            "windBearing": a.get("wind_bearing"),
            "pressure": a.get("pressure"),
            "visibility": a.get("visibility"),
        }

    # ── Climate helper ─────────────────────────────────────────────
    def shape_climate(eid: str) -> Optional[dict]:
        s = get(eid)
        if not s:
            return None
        a = s.get("attributes") or {}
        return {
            "id": eid,
            "name": a.get("friendly_name") or eid,
            "mode": s.get("state"),
            "current": a.get("current_temperature"),
            "target": a.get("temperature"),
            "action": a.get("hvac_action"),
        }

    climates = {
        "basement": shape_climate(_CLIMATE_BASEMENT),
        "first": shape_climate(_CLIMATE_FIRST),
        "second": shape_climate(_CLIMATE_SECOND),
        "third": shape_climate(_CLIMATE_THIRD),
        "radiantMain": shape_climate(_CLIMATE_RADIANT_MAIN),
        "radiantApt": shape_climate(_CLIMATE_RADIANT_APT),
    }

    # ── Pool ───────────────────────────────────────────────────────
    pool: Optional[dict] = None
    pw = get(_POOL_ID)
    if pw:
        a = pw.get("attributes") or {}
        pool = {
            "name": "Pool",
            "operation": pw.get("state"),
            "current": a.get("current_temperature"),
            "target": a.get("temperature"),
            "air": state_num(_POOL_AIR),
            "heating": state_str(_POOL_HEAT) == "on",
            "pumpRunning": state_str(_POOL_PUMP) == "on",
            "schedule": state_str(_POOL_SCHED) == "on",
            "freezeProtect": state_str(_POOL_FREEZE) == "on",
        }

    # ── Sauna ──────────────────────────────────────────────────────
    sauna: Optional[dict] = None
    sc = get(_SAUNA_ID)
    if sc:
        a = sc.get("attributes") or {}
        sauna = {
            "mode": sc.get("state"),
            "current": a.get("current_temperature"),
            "target": a.get("temperature"),
            "duration": state_num(_SAUNA_DURATION),
            "heaters": state_num(_SAUNA_HEATERS),
            "door": state_str(_SAUNA_DOOR) == "on",
            "light": state_str(_SAUNA_LIGHT) == "on",
            "roomTemp": state_num(_SAUNA_ROOM_TEMP),
            "roomHumidity": state_num(_SAUNA_ROOM_HUM),
        }

    # ── Washer ─────────────────────────────────────────────────────
    washer_notif_event = get(_WASHER_NOTIF)
    last_notif: Optional[dict] = None
    if washer_notif_event:
        a = washer_notif_event.get("attributes") or {}
        last_notif = {
            "type": a.get("event_type"),
            "at": washer_notif_event.get("state"),
        }
    washer = {
        "status": state_str(_WASHER_STATUS),
        "operation": state_str(_WASHER_OP),
        "remaining": state_str(_WASHER_REMAINING),
        "lastNotification": last_notif,
        "powerOn": state_str(_WASHER_POWER) == "on",
        "cycles": state_num(_WASHER_CYCLES),
        "energyMonth": state_num(_WASHER_ENERGY),
    }

    # ── Dishwasher ─────────────────────────────────────────────────
    dishwasher = {
        "state": state_str(_DW_STATE),
        "program": state_str(_DW_PROG),
        "progress": state_num(_DW_PROGRESS),
        "finishTime": state_str(_DW_FINISH),
        "door": state_str(_DW_DOOR),
        "powerOn": state_str(_DW_POWER) == "on",
        "connected": state_str(_DW_CONN) == "on",
    }

    # ── All climates (excluding sauna + serial-test entities) ──────
    all_climates: list[dict] = []
    floor_activity: dict[str, list[dict]] = {
        "first": [],
        "second": [],
        "third": [],
        "basement": [],
        "other": [],
    }
    for s in states:
        eid = s.get("entity_id") or ""
        if not eid.startswith("climate."):
            continue
        if s.get("state") == "unavailable":
            continue
        if eid == _SAUNA_ID:
            continue
        if "serial_test" in eid:
            continue
        a = s.get("attributes") or {}
        c = {
            "id": eid,
            "name": a.get("friendly_name") or eid,
            "mode": s.get("state"),
            "current": a.get("current_temperature"),
            "target": a.get("temperature"),
            "action": a.get("hvac_action"),
        }
        all_climates.append(c)
        f = _floor_of(eid)
        if f:
            floor_activity[f].append(c)

    # ── Temps ──────────────────────────────────────────────────────
    temps = {
        "basement": state_num(_TEMP_BASEMENT),
        "first": state_num(_TEMP_FIRST),
        "second": state_num(_TEMP_SECOND),
        "third": state_num(_TEMP_THIRD),
        "outdoor": state_num(_TEMP_OUTDOOR),
    }

    # ── People ─────────────────────────────────────────────────────
    people = []
    for s in states:
        eid = s.get("entity_id") or ""
        if not eid.startswith("person."):
            continue
        a = s.get("attributes") or {}
        people.append({
            "name": a.get("friendly_name") or eid,
            "state": s.get("state"),
        })

    # ── Garage ─────────────────────────────────────────────────────
    garage = {"state": state_str(_GARAGE_ID) or "closed"}

    # ── Open windows: covers, excluding shades/curtains/garage/skylights ─
    open_windows: list[dict] = []
    for s in states:
        eid = s.get("entity_id") or ""
        if not eid.startswith("cover."):
            continue
        a = s.get("attributes") or {}
        name = a.get("friendly_name") or ""
        haystack = f"{eid} {name}".lower()
        if re.search(r"shade|blind|curtain|skylight|garage", haystack):
            continue
        if s.get("state") != "open":
            continue
        open_windows.append({"id": eid, "name": name or eid})

    # ── Sun ────────────────────────────────────────────────────────
    sun = {
        "state": state_str(_SUN_ID),
        "nextDawn": state_str(_SUN_DAWN),
        "nextDusk": state_str(_SUN_DUSK),
        "nextRising": state_str(_SUN_RISING),
        "nextSetting": state_str(_SUN_SETTING),
    }

    return {
        "fetchedAt": fetched_at.isoformat(),
        "weather": weather,
        "climates": climates,
        "temps": temps,
        "people": people,
        "garage": garage,
        "openWindows": open_windows,
        "sun": sun,
        "pool": pool,
        "sauna": sauna,
        "washer": washer,
        "dishwasher": dishwasher,
        "allClimates": all_climates,
        "floorActivity": floor_activity,
        # floorHeatCount/floorAnyHeating were JS helper functions; the Pillow
        # renderer rebuilds them from floorActivity in
        # backend/services/eink/pillow/helpers.py.
    }


def empty_ha_shape(*, fetched_at: Optional[datetime] = None) -> dict[str, Any]:
    """A minimal valid HAShape with everything null/empty.

    Useful when HA is unreachable but we still need the design to render its
    'calm/quiet' state instead of crashing on a null `ha`.
    """
    fetched_at = fetched_at or datetime.now(timezone.utc)
    return {
        "fetchedAt": fetched_at.isoformat(),
        "weather": None,
        "climates": {},
        "temps": {},
        "people": [],
        "garage": {"state": "closed"},
        "openWindows": [],
        "sun": {"state": "below_horizon"},
        "pool": None,
        "sauna": None,
        "washer": {
            "status": "power_off",
            "operation": None,
            "remaining": None,
            "lastNotification": None,
            "powerOn": False,
            "cycles": 0,
            "energyMonth": 0,
        },
        "dishwasher": {
            "state": None,
            "program": None,
            "progress": None,
            "finishTime": None,
            "door": "closed",
            "powerOn": False,
            "connected": False,
        },
        "allClimates": [],
        "floorActivity": {
            "first": [],
            "second": [],
            "third": [],
            "basement": [],
            "other": [],
        },
    }


# ── Convenience: settings -> shape ─────────────────────────────────────


async def fetch_and_shape(settings: TerminalSettings) -> Optional[dict[str, Any]]:
    """Fetch HA states using a TerminalSettings row and return the shaped HAShape.

    Returns `None` if HA is not configured or the call fails. The caller
    should treat None as "render the calm state" rather than 500'ing -- a
    dashboard with a stale-but-painted face is better than a missing one.
    """
    url = (settings.home_assistant_url or "").strip()
    if not url or not settings.home_assistant_token_encrypted:
        return None
    try:
        token = decrypt_value(settings.home_assistant_token_encrypted)
    except Exception:
        logger.exception("Failed to decrypt HA token for user_id=%s", settings.user_id)
        return None
    try:
        states = await fetch_ha_states(url, token)
    except HAClientError as e:
        logger.warning("HA fetch failed for user_id=%s: %s", settings.user_id, e)
        return None
    return shape_ha_state(states, fetched_at=datetime.now(timezone.utc))
