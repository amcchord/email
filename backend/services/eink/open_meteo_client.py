"""Open-Meteo REST client for the fields HA weather entities don't expose.

The Home Assistant Open-Meteo integration only surfaces condition,
temperature, wind, and precipitation on its weather entity -- it does not
expose UV index or apparent ("feels like") temperature. Both are available
from the free Open-Meteo forecast API (no key, non-commercial use), so we
fetch them directly using the Home zone's latitude/longitude. The current
US AQI comes from Open-Meteo's companion air-quality API the same way.

Never raises: every helper returns ``None`` on any failure so a weather
hiccup degrades to the local-station / NWS fallback in ``ha_client`` instead
of failing the whole render.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_CURRENT_FIELDS = "uv_index,apparent_temperature,temperature_2m,relative_humidity_2m"


def _as_float(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _today_uv_peak(hourly: Any) -> Optional[float]:
    """Max UV index across the hourly array (one forecast day = today)."""
    if not isinstance(hourly, dict):
        return None
    values = [_as_float(v) for v in (hourly.get("uv_index") or [])]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return max(values)


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """GET `url` and return the parsed JSON dict, or None on any failure."""
    try:
        resp = await client.get(url, params=params)
    except httpx.RequestError as e:
        logger.warning("Open-Meteo fetch failed (%s): %s", url, e)
        return None
    if resp.status_code != 200:
        logger.warning("Open-Meteo returned HTTP %s (%s)", resp.status_code, url)
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


async def fetch_current(
    lat: float,
    lon: float,
    *,
    timeout: float = 5.0,
) -> Optional[dict[str, Any]]:
    """Fetch current UV index, apparent temperature, and US AQI for a coordinate.

    Returns a dict with float values (``uv_index``, ``apparent_temperature``,
    ``temperature``, ``humidity``, ``aqi``, plus today's ``uv_peak``); keys are
    omitted when Open-Meteo doesn't return them. The weather and air-quality
    calls are independent, so one failing still yields the other's fields.
    Returns ``None`` when neither call produced anything.
    """
    forecast_params = {
        "latitude": lat,
        "longitude": lon,
        "current": _CURRENT_FIELDS,
        "hourly": "uv_index",
        "forecast_days": 1,
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
    }
    aqi_params = {
        "latitude": lat,
        "longitude": lon,
        "current": "us_aqi",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        weather_data, aqi_data = await asyncio.gather(
            _get_json(client, _API_URL, forecast_params),
            _get_json(client, _AIR_QUALITY_URL, aqi_params),
        )

    out: dict[str, Any] = {}

    current = (weather_data or {}).get("current")
    if isinstance(current, dict):
        for src, dst in (
            ("uv_index", "uv_index"),
            ("apparent_temperature", "apparent_temperature"),
            ("temperature_2m", "temperature"),
            ("relative_humidity_2m", "humidity"),
        ):
            v = _as_float(current.get(src))
            if v is not None:
                out[dst] = v
        peak = _today_uv_peak((weather_data or {}).get("hourly"))
        if peak is not None:
            out["uv_peak"] = peak

    aqi_current = (aqi_data or {}).get("current")
    if isinstance(aqi_current, dict):
        aqi = _as_float(aqi_current.get("us_aqi"))
        if aqi is not None:
            out["aqi"] = aqi

    return out or None
