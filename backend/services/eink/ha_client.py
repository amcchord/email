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

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from backend.models.terminal import TerminalSettings
from backend.services.eink.open_meteo_client import fetch_current as fetch_open_meteo
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


# HA WeatherEntityFeature bits (declared by each weather integration on its
# `supported_features` attribute):
#   FORECAST_DAILY       = 1
#   FORECAST_HOURLY      = 2
#   FORECAST_TWICE_DAILY = 4
# NWS in particular reports 6 (HOURLY + TWICE_DAILY) -- asking it for "daily"
# returns HTTP 500. We use these bits to skip kinds we know will fail.
WEATHER_FEATURE_DAILY = 1
WEATHER_FEATURE_HOURLY = 2
WEATHER_FEATURE_TWICE_DAILY = 4


async def fetch_ha_forecast(
    url: str,
    token: str,
    entity_id: str,
    *,
    kind: str = "daily",
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Call HA's `weather.get_forecasts` service for `entity_id`.

    Returns the list of forecast slot dicts (each: condition / temperature /
    templow / datetime / precipitation_probability / etc.) for the requested
    `kind` ("daily" | "hourly" | "twice_daily"). Returns an empty list on any
    failure -- the renderer's job is to draw a "Forecast unavailable" fallback,
    not to crash, when HA is older than 2024.4 or the weather integration
    doesn't expose forecasts.
    """
    if not url or not token or not entity_id:
        return []
    base = url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"entity_id": entity_id, "type": kind}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/api/services/weather/get_forecasts",
                headers=headers,
                json=body,
                params={"return_response": "true"},
            )
    except httpx.RequestError as e:
        logger.warning("HA forecast fetch failed (%s, %s): %s", entity_id, kind, e)
        return []
    if resp.status_code != 200:
        logger.warning(
            "HA forecast fetch returned HTTP %s for %s (%s): %s",
            resp.status_code, entity_id, kind, resp.text[:200],
        )
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    svc = (data or {}).get("service_response") or {}
    entry = svc.get(entity_id) or {}
    forecast = entry.get("forecast") or []
    if not isinstance(forecast, list):
        return []
    return forecast


def _consolidate_twice_daily(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a twice-daily forecast (alternating daytime/night slots, each
    carrying a single `temperature`) into one entry per day with `temperature`
    (the daytime high) and `templow` (the following nighttime low).

    NWS (and other US providers) reports forecasts as day/night periods --
    typical pattern is [Today daytime, Tonight, Tomorrow day, Tomorrow night,
    ...]. If the first slot is a nighttime period (e.g. we're rendering after
    sundown) we use it as the low for the prior day rather than dropping the
    most-recent overnight low on the floor.
    """
    out: list[dict[str, Any]] = []
    i = 0
    n = len(slots)
    while i < n:
        s = slots[i]
        is_day = bool(s.get("is_daytime"))
        if is_day:
            entry = {
                "datetime": s.get("datetime"),
                "condition": s.get("condition"),
                "temperature": s.get("temperature"),
                "templow": None,
                "precipitation_probability": s.get("precipitation_probability"),
                "humidity": s.get("humidity"),
                "wind_speed": s.get("wind_speed"),
                "wind_bearing": s.get("wind_bearing"),
            }
            if i + 1 < n and slots[i + 1].get("is_daytime") is False:
                entry["templow"] = slots[i + 1].get("temperature")
                i += 2
            else:
                i += 1
            out.append(entry)
        else:
            # Lone nighttime slot. If we have a previous entry without a low,
            # attach it there; otherwise emit a stub day so the row still
            # shows a low temperature for "tonight".
            if out and out[-1].get("templow") is None:
                out[-1]["templow"] = s.get("temperature")
            else:
                out.append({
                    "datetime": s.get("datetime"),
                    "condition": s.get("condition"),
                    "temperature": None,
                    "templow": s.get("temperature"),
                    "precipitation_probability": s.get("precipitation_probability"),
                    "humidity": s.get("humidity"),
                    "wind_speed": s.get("wind_speed"),
                    "wind_bearing": s.get("wind_bearing"),
                })
            i += 1
    return out


async def fetch_ha_daily_forecast(
    url: str,
    token: str,
    entity_id: str,
    supported_features: Optional[int] = None,
    *,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Fetch a daily-shape forecast for `entity_id`, honoring the integration's
    advertised support. Tries `daily` first when available, falls back to
    consolidating a `twice_daily` response (used by NWS, met.no, etc.).
    """
    feats = int(supported_features or 0)
    can_daily = bool(feats & WEATHER_FEATURE_DAILY) or feats == 0
    can_twice = bool(feats & WEATHER_FEATURE_TWICE_DAILY) or feats == 0

    if can_daily:
        daily = await fetch_ha_forecast(url, token, entity_id, kind="daily",
                                        timeout=timeout)
        if daily:
            return daily
    if can_twice:
        twice = await fetch_ha_forecast(url, token, entity_id, kind="twice_daily",
                                        timeout=timeout)
        if twice:
            return _consolidate_twice_daily(twice)
    return []


async def fetch_ha_hourly_forecast(
    url: str,
    token: str,
    entity_id: str,
    supported_features: Optional[int] = None,
    *,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Fetch an hourly forecast for `entity_id`. Returns [] if the integration
    doesn't advertise hourly support."""
    feats = int(supported_features or 0)
    if feats and not (feats & WEATHER_FEATURE_HOURLY):
        return []
    return await fetch_ha_forecast(url, token, entity_id, kind="hourly",
                                   timeout=timeout)


# ── State shaping (port of ha-data.js) ─────────────────────────────────


# Hard-coded entity IDs from docs/design/HANDOFF.md Sec 4.2. These can be
# wrong for your install -- missing entities just render as null/empty.
#
# Weather-entity preference: Open-Meteo (`weather.home`) gives a forecast and
# condition that track the area model the rest of the dashboard is now built
# around; fall through to the historical `weather.forecast_home`, then to any
# `weather.*` entity (typically NWS) so other installs still resolve.
_OPEN_METEO_WEATHER_ENTITY = "weather.home"
_WEATHER_ENTITY_ID = "weather.forecast_home"
_WEATHER_ENTITY_PREFERENCE = (_OPEN_METEO_WEATHER_ENTITY, _WEATHER_ENTITY_ID)

_HOME_ZONE_ID = "zone.home"

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

# LG ThinQ dryer mirrors the washer entity layout, minus cycles/energy
# (those sensors aren't exposed for the dryer model). Status enum adds
# `cooling` and `wrinkle_care` for the post-cycle anti-wrinkle phase --
# those still count as "running" so the active card stays up.
_DRYER_STATUS = "sensor.dryer_current_status"
_DRYER_OP = "select.dryer_operation"
_DRYER_REMAINING = "sensor.dryer_remaining_time"
_DRYER_NOTIF = "event.dryer_notification"
_DRYER_POWER = "switch.dryer_power"

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
_FEELS_LIKE = "sensor.weather_station_feels_like_temperature"
_UV_INDEX = "sensor.weather_station_uv_index"
# Left-rail wind uses the local station's gust + direction (hyperlocal, what's
# actually happening at the house) rather than the area weather entity.
_WIND_GUST = "sensor.weather_station_wind_gust"
_WIND_DIRECTION = "sensor.weather_station_wind_direction"

_GARAGE_ID = "cover.smart_garage_door_25090565132271610701c4e7ae20a653_garage"

_SUN_ID = "sun.sun"
_SUN_DAWN = "sensor.sun_next_dawn"
_SUN_DUSK = "sensor.sun_next_dusk"
_SUN_RISING = "sensor.sun_next_rising"
_SUN_SETTING = "sensor.sun_next_setting"

# Enphase Envoy rooftop array. Serial (202329034883) is install-specific,
# consistent with every other hard-coded entity ID in this module. The
# microinverters report one `sensor.inverter_<serial>` each; counting them
# gives the panel count, which scales the right-rail power bar's full scale.
_SOLAR_POWER_NOW = "sensor.envoy_202329034883_current_power_production"      # kW
_SOLAR_ENERGY_TODAY = "sensor.envoy_202329034883_energy_production_today"    # kWh
_SOLAR_ENERGY_WEEK = "sensor.envoy_202329034883_energy_production_last_seven_days"  # kWh
_SOLAR_ENERGY_LIFETIME = "sensor.envoy_202329034883_lifetime_energy_production"     # MWh
_SOLAR_INVERTER_RE = re.compile(r"^sensor\.inverter_\d+$")
_SOLAR_HISTORY_WINDOW = timedelta(minutes=5)


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


def _solar_delta_kwh(
    current_lifetime_mwh: Optional[float],
    starting_lifetime_mwh: Optional[float],
) -> Optional[float]:
    """Convert two monotonic lifetime readings into period energy."""
    if current_lifetime_mwh is None or starting_lifetime_mwh is None:
        return None
    delta = (current_lifetime_mwh - starting_lifetime_mwh) * 1000.0
    if delta < 0:
        return None
    return delta


def _solar_period_value(
    computed: Any,
    reported: Any,
    lifetime_mwh: Optional[float],
) -> Optional[float]:
    """Prefer a history delta and reject Envoy's lifetime-as-period bug."""
    computed_num = _to_float(computed)
    if computed_num is not None and computed_num >= 0:
        return computed_num

    reported_num = _to_float(reported)
    if reported_num is None or reported_num < 0:
        return None
    if lifetime_mwh is None:
        return reported_num

    lifetime_kwh = lifetime_mwh * 1000.0
    # Current Envoy firmware can expose the lifetime total, converted to kWh,
    # through both the "today" and "last seven days" entities. Never paint
    # that value as a period total if recorder history is temporarily absent.
    if lifetime_kwh > 1.0 and abs(reported_num - lifetime_kwh) < 0.1:
        return None
    return reported_num


async def fetch_ha_state_near(
    url: str,
    token: str,
    entity_id: str,
    target: datetime,
    *,
    timeout: float = 5.0,
) -> Optional[float]:
    """Read the recorder value immediately before ``target``.

    A narrow ten-minute history window keeps the response small even when an
    Envoy sensor updates every few seconds. If there is no point before the
    target, the first point after it is the closest available baseline.
    """
    if not url or not token or not entity_id:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    else:
        target = target.astimezone(timezone.utc)

    start = target - _SOLAR_HISTORY_WINDOW
    end = target + _SOLAR_HISTORY_WINDOW
    encoded_start = quote(start.isoformat(), safe="")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    params = {
        "filter_entity_id": entity_id,
        "end_time": end.isoformat(),
        "minimal_response": "true",
        "no_attributes": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{url.rstrip('/')}/api/history/period/{encoded_start}",
                headers=headers,
                params=params,
            )
    except httpx.RequestError as exc:
        logger.warning("HA history fetch failed for %s: %s", entity_id, exc)
        return None
    if response.status_code != 200:
        logger.warning(
            "HA history fetch returned HTTP %s for %s: %s",
            response.status_code,
            entity_id,
            response.text[:200],
        )
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    history = payload[0]
    if not isinstance(history, list):
        return None

    before: list[tuple[datetime, float]] = []
    after: list[tuple[datetime, float]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        value = _to_float(item.get("state"))
        stamp_raw = item.get("last_changed") or item.get("last_updated")
        if value is None or not isinstance(stamp_raw, str):
            continue
        try:
            stamp = datetime.fromisoformat(stamp_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = stamp.astimezone(timezone.utc)
        point = (stamp, value)
        if stamp <= target:
            before.append(point)
        else:
            after.append(point)

    if before:
        return max(before, key=lambda point: point[0])[1]
    if after:
        return min(after, key=lambda point: point[0])[1]
    return None


async def fetch_ha_solar_period_totals(
    url: str,
    token: str,
    current_lifetime_mwh: Optional[float],
    timezone_name: str,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Optional[float]]:
    """Derive today's and rolling seven-day energy from lifetime history."""
    if current_lifetime_mwh is None:
        return {"todayKwh": None, "weekKwh": None}

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    zone_name = timezone_name or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown terminal timezone %r; using UTC for solar totals", zone_name)
        zone = ZoneInfo("UTC")

    local_now = now_utc.astimezone(zone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = local_midnight.astimezone(timezone.utc)
    week_ago = now_utc - timedelta(days=7)
    today_base, week_base = await asyncio.gather(
        fetch_ha_state_near(
            url, token, _SOLAR_ENERGY_LIFETIME, midnight_utc,
        ),
        fetch_ha_state_near(
            url, token, _SOLAR_ENERGY_LIFETIME, week_ago,
        ),
    )
    return {
        "todayKwh": _solar_delta_kwh(current_lifetime_mwh, today_base),
        "weekKwh": _solar_delta_kwh(current_lifetime_mwh, week_base),
    }


def _normalize_forecast_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim a `weather.get_forecasts` response down to the fields renderers
    actually use. Unknown extra keys (humidity, wind_speed, dew_point) are
    preserved so the Swiss / Editorial designs can read more detail without
    a follow-up shape change."""
    out: list[dict[str, Any]] = []
    for s in slots or []:
        if not isinstance(s, dict):
            continue
        out.append({
            "datetime": s.get("datetime"),
            "condition": s.get("condition"),
            "temperature": s.get("temperature"),
            "templow": s.get("templow"),
            "precipitation_probability": s.get("precipitation_probability"),
            "humidity": s.get("humidity"),
            "wind_speed": s.get("wind_speed"),
            "wind_bearing": s.get("wind_bearing"),
        })
    return out


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


def _any_weather_attr(states: list[dict[str, Any]], key: str) -> Any:
    """First non-null `key` attribute across all `weather.*` entities.

    Open-Meteo (`weather.home`) doesn't expose humidity or visibility, so we
    borrow those from whichever other weather entity (e.g. NWS) still carries
    them instead of rendering a misleading zero."""
    for s in states:
        if (s.get("entity_id") or "").startswith("weather."):
            v = (s.get("attributes") or {}).get(key)
            if v is not None:
                return v
    return None


def shape_ha_state(
    states: list[dict[str, Any]],
    *,
    fetched_at: Optional[datetime] = None,
    weather_entity_id: Optional[str] = None,
    forecast_daily: Optional[list[dict[str, Any]]] = None,
    forecast_hourly: Optional[list[dict[str, Any]]] = None,
    open_meteo: Optional[dict[str, Any]] = None,
    solar_periods: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Reshape `/api/states` into the HAShape consumed by the React designs.

    `weather_entity_id` overrides the default; the JS shape stores this as a
    top-level pointer in lastState.json. Defaults to `weather.forecast_home`
    if the install has it, otherwise the first `weather.*` entity found.

    `forecast_daily` / `forecast_hourly` are optional pre-fetched lists from
    `fetch_ha_forecast`. When provided they're attached to
    `weather["forecast"]` so renderers don't have to know about HA services.

    `open_meteo` is an optional dict from `open_meteo_client.fetch_current`
    supplying `uv_index` / `apparent_temperature` (and today's `uv_peak`),
    which the HA weather entity does not expose. Its values take precedence
    over the local station's UV / feels-like sensors, which remain the
    fallback when Open-Meteo is unavailable.

    `solar_periods` contains recorder-history deltas for today and the rolling
    seven-day window. Envoy's direct period sensors can incorrectly mirror the
    lifetime total, so history-derived values take precedence.
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
        om = open_meteo or {}

        def om_val(key: str, fallback: Any) -> Any:
            v = om.get(key)
            return v if v is not None else fallback

        # Wind shows the local station's gust + direction (hyperlocal), with
        # the area weather entity as the fallback when the station is offline.
        gust = state_num(_WIND_GUST)
        wind_dir = state_num(_WIND_DIRECTION)
        weather = {
            "state": w.get("state"),
            "temperature": a.get("temperature"),
            "outdoorTemp": state_num(_TEMP_OUTDOOR),
            "feelsLike": om_val("apparent_temperature", state_num(_FEELS_LIKE)),
            "uvIndex": om_val("uv_index", state_num(_UV_INDEX)),
            "uvPeak": om.get("uv_peak"),
            # US AQI comes only from the Open-Meteo air-quality API; there is
            # no local-station fallback, so it's simply absent on failure.
            "aqi": om.get("aqi"),
            # Open-Meteo's HA entity omits humidity/visibility, so prefer the
            # Open-Meteo API humidity (matches the feels-like source) and
            # borrow visibility from any weather entity that still reports it.
            "humidity": om_val("humidity", _any_weather_attr(states, "humidity")),
            "windSpeed": gust if gust is not None else a.get("wind_speed"),
            "windBearing": wind_dir if wind_dir is not None else a.get("wind_bearing"),
            "pressure": a.get("pressure"),
            "visibility": _any_weather_attr(states, "visibility"),
        }
        weather["forecast"] = {
            "daily": _normalize_forecast_slots(forecast_daily or []),
            "hourly": _normalize_forecast_slots(forecast_hourly or []),
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

    # ── Dryer ──────────────────────────────────────────────────────
    dryer_notif_event = get(_DRYER_NOTIF)
    dryer_last_notif: Optional[dict] = None
    if dryer_notif_event:
        a = dryer_notif_event.get("attributes") or {}
        dryer_last_notif = {
            "type": a.get("event_type"),
            "at": dryer_notif_event.get("state"),
        }
    dryer = {
        "status": state_str(_DRYER_STATUS),
        "operation": state_str(_DRYER_OP),
        "remaining": state_str(_DRYER_REMAINING),
        "lastNotification": dryer_last_notif,
        "powerOn": state_str(_DRYER_POWER) == "on",
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

    # ── Solar (Enphase Envoy) ──────────────────────────────────────
    panel_count = sum(
        1 for s in states if _SOLAR_INVERTER_RE.match(s.get("entity_id") or "")
    )
    lifetime_mwh = state_num(_SOLAR_ENERGY_LIFETIME)
    periods = solar_periods or {}
    solar = {
        "currentKw": state_num(_SOLAR_POWER_NOW),
        "todayKwh": _solar_period_value(
            periods.get("todayKwh"),
            state_num(_SOLAR_ENERGY_TODAY),
            lifetime_mwh,
        ),
        "weekKwh": _solar_period_value(
            periods.get("weekKwh"),
            state_num(_SOLAR_ENERGY_WEEK),
            lifetime_mwh,
        ),
        "lifetimeMwh": lifetime_mwh,
        "panelCount": panel_count or None,
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
        "solar": solar,
        "pool": pool,
        "sauna": sauna,
        "washer": washer,
        "dryer": dryer,
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
        "weather": {
            "state": None,
            "temperature": None,
            "outdoorTemp": None,
            "feelsLike": None,
            "uvIndex": None,
            "uvPeak": None,
            "aqi": None,
            "humidity": None,
            "windSpeed": None,
            "windBearing": None,
            "pressure": None,
            "visibility": None,
            "forecast": {"daily": [], "hourly": []},
        },
        "climates": {},
        "temps": {},
        "people": [],
        "garage": {"state": "closed"},
        "openWindows": [],
        "sun": {"state": "below_horizon"},
        "solar": {
            "currentKw": None,
            "todayKwh": None,
            "weekKwh": None,
            "lifetimeMwh": None,
            "panelCount": None,
        },
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
        "dryer": {
            "status": "power_off",
            "operation": None,
            "remaining": None,
            "lastNotification": None,
            "powerOn": False,
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


def _resolve_weather_entity(
    states: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[int]]:
    """Pick the weather entity we should fetch forecasts against.

    Walks `_WEATHER_ENTITY_PREFERENCE` in order ("weather.home" /
    Open-Meteo first, then "weather.forecast_home"), then falls back to the
    first available `weather.*` entity (matching the existing fallback in
    `shape_ha_state`). Returns `(entity_id, supported_features)` so the
    forecast call can skip kinds the integration doesn't advertise.
    """
    idx = {s.get("entity_id"): s for s in states if s.get("entity_id")}
    chosen: Optional[dict[str, Any]] = None
    for eid in _WEATHER_ENTITY_PREFERENCE:
        if eid in idx:
            chosen = idx[eid]
            break
    if chosen is None:
        for s in states:
            if (s.get("entity_id") or "").startswith("weather."):
                chosen = s
                break
    if chosen is None:
        return None, None
    feats = (chosen.get("attributes") or {}).get("supported_features")
    try:
        feats_i = int(feats) if feats is not None else None
    except (TypeError, ValueError):
        feats_i = None
    return chosen.get("entity_id"), feats_i


def _home_coords(states: list[dict[str, Any]]) -> Optional[tuple[float, float]]:
    """Read the Home zone's latitude/longitude so we can query Open-Meteo for
    the same location HA is configured for. Returns None if `zone.home` is
    missing or doesn't carry numeric coordinates."""
    for s in states:
        if (s.get("entity_id") or "") == _HOME_ZONE_ID:
            a = s.get("attributes") or {}
            lat = a.get("latitude")
            lon = a.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return float(lat), float(lon)
            return None
    return None


async def fetch_and_shape(settings: TerminalSettings) -> Optional[dict[str, Any]]:
    """Fetch HA states + forecasts using a TerminalSettings row and return the
    shaped HAShape.

    Issues `/api/states` first, discovers the actual `weather.*` entity (some
    installs use `weather.forecast_home`, others use `weather.nws_...` etc.),
    then fires the daily + hourly forecast service calls in parallel against
    the discovered entity. Forecast failures fall back to empty lists so the
    state fetch still produces a usable shape.

    Returns `None` if HA is not configured or the states call fails. The
    caller should treat None as "render the calm state" rather than 500'ing
    -- a dashboard with a stale-but-painted face is better than a missing one.
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

    weather_eid, feats = _resolve_weather_entity(states)
    coords = _home_coords(states)
    state_index = {s.get("entity_id"): s for s in states if s.get("entity_id")}
    lifetime_state = state_index.get(_SOLAR_ENERGY_LIFETIME) or {}
    lifetime_mwh = _to_float(lifetime_state.get("state"))

    async def _open_meteo() -> Optional[dict[str, Any]]:
        if not coords:
            return None
        return await fetch_open_meteo(coords[0], coords[1])

    async def _solar_periods() -> dict[str, Optional[float]]:
        return await fetch_ha_solar_period_totals(
            url,
            token,
            lifetime_mwh,
            settings.timezone,
        )

    daily: list[dict[str, Any]] = []
    hourly: list[dict[str, Any]] = []
    if weather_eid:
        daily, hourly, open_meteo, solar_periods = await asyncio.gather(
            fetch_ha_daily_forecast(url, token, weather_eid, feats),
            fetch_ha_hourly_forecast(url, token, weather_eid, feats),
            _open_meteo(),
            _solar_periods(),
        )
    else:
        open_meteo, solar_periods = await asyncio.gather(
            _open_meteo(),
            _solar_periods(),
        )

    return shape_ha_state(
        states,
        fetched_at=datetime.now(timezone.utc),
        weather_entity_id=weather_eid,
        forecast_daily=daily,
        forecast_hourly=hourly,
        open_meteo=open_meteo,
        solar_periods=solar_periods,
    )
