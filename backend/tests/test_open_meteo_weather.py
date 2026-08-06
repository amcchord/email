"""Tests for the Open-Meteo weather source and the UV / feels-like / wind
shaping in ``eink/ha_client.py``.

These guard the dashboard accuracy fix: UV index and "feels like" now come
from Open-Meteo (the local Ecowitt station consistently underreports both),
the left-rail wind uses the station's hyperlocal gust, and every field falls
back gracefully when a source is unavailable.
"""
from __future__ import annotations

import asyncio

import httpx

from backend.services.eink import ha_client as hc
from backend.services.eink import open_meteo_client as om


# ── Fixtures ──────────────────────────────────────────────────────────


def _state(eid: str, state, **attrs):
    return {"entity_id": eid, "state": state, "attributes": attrs}


def _weather_states(*, gust="2.68", direction="129"):
    """A minimal states list: an Open-Meteo weather entity plus the local
    station sensors the shaper reads for outdoor temp / UV / feels / wind."""
    states = [
        _state("weather.home", "sunny", temperature=79, humidity=40,
               wind_speed=11.62, wind_bearing=268, pressure=29.85, visibility=10),
        _state("sensor.weather_station_outdoor_temperature", "79.7"),
        _state("sensor.weather_station_feels_like_temperature", "79.7"),
        _state("sensor.weather_station_uv_index", "3"),
    ]
    if gust is not None:
        states.append(_state("sensor.weather_station_wind_gust", gust))
    if direction is not None:
        states.append(_state("sensor.weather_station_wind_direction", direction))
    return states


def _shape(states, open_meteo=None):
    return hc.shape_ha_state(
        states, weather_entity_id="weather.home", open_meteo=open_meteo,
    )["weather"]


# ── shape_ha_state: UV / feels-like precedence ────────────────────────


def test_open_meteo_overrides_station_uv_and_feels():
    """Open-Meteo is the source of truth for UV and feels-like; the under-
    reporting station values are only a fallback."""
    w = _shape(
        _weather_states(),
        open_meteo={"uv_index": 7.75, "apparent_temperature": 77.8, "uv_peak": 8.4},
    )
    assert w["uvIndex"] == 7.75
    assert w["feelsLike"] == 77.8
    assert w["uvPeak"] == 8.4


def test_station_fallback_when_open_meteo_missing():
    """When Open-Meteo is unreachable we still show the station readings so
    the dashboard never goes blank."""
    w = _shape(_weather_states(), open_meteo=None)
    assert w["uvIndex"] == 3.0
    assert w["feelsLike"] == 79.7
    assert w["uvPeak"] is None


def test_open_meteo_partial_falls_back_per_field():
    """A partial Open-Meteo response (UV only) keeps the station feels-like
    rather than discarding it."""
    w = _shape(_weather_states(), open_meteo={"uv_index": 7.0})
    assert w["uvIndex"] == 7.0
    assert w["feelsLike"] == 79.7


def test_open_meteo_zero_uv_is_not_treated_as_missing():
    """A genuine 0.0 UV (overnight) must win over the station, not fall back
    -- ``0.0`` is a real reading, not 'no data'."""
    w = _shape(_weather_states(), open_meteo={"uv_index": 0.0})
    assert w["uvIndex"] == 0.0


def test_open_meteo_aqi_shaped_into_weather():
    w = _shape(_weather_states(), open_meteo={"aqi": 42.0})
    assert w["aqi"] == 42.0


def test_aqi_none_when_open_meteo_missing():
    """There is no local-station AQI fallback; the masthead just omits it."""
    w = _shape(_weather_states(), open_meteo=None)
    assert w["aqi"] is None


# ── shape_ha_state: wind from station gust ────────────────────────────


def test_wind_uses_station_gust_and_direction():
    w = _shape(_weather_states(gust="2.68", direction="129"))
    assert w["windSpeed"] == 2.68
    assert w["windBearing"] == 129.0


def test_wind_falls_back_to_weather_entity_when_gust_unknown():
    """If the station gust sensor reports ``unknown`` we use the area weather
    entity's wind instead of dropping the stat."""
    states = _weather_states(gust="unknown", direction=None)
    w = _shape(states)
    assert w["windSpeed"] == 11.62
    assert w["windBearing"] == 268


# ── shape_ha_state: humidity / visibility sourcing ────────────────────


def test_humidity_prefers_open_meteo():
    w = _shape(_weather_states(), open_meteo={"humidity": 38.0})
    assert w["humidity"] == 38.0


def test_visibility_borrowed_from_other_weather_entity():
    """Open-Meteo (`weather.home`) lacks visibility; the shaper borrows it
    from the NWS entity so the rail doesn't show a misleading 0 mi."""
    states = _weather_states()
    # weather.home (primary) has no visibility; add an NWS entity that does.
    for s in states:
        if s["entity_id"] == "weather.home":
            s["attributes"].pop("visibility", None)
    states.append(_state("weather.nws_42_kbos", "partlycloudy", visibility=10))
    w = _shape(states)
    assert w["visibility"] == 10


# ── _resolve_weather_entity preference ────────────────────────────────


def test_resolve_weather_entity_prefers_open_meteo():
    states = [
        _state("weather.nws_42_kbos", "partlycloudy", supported_features=6),
        _state("weather.home", "sunny", supported_features=3),
    ]
    eid, feats = hc._resolve_weather_entity(states)
    assert eid == "weather.home"
    assert feats == 3


def test_resolve_weather_entity_prefers_forecast_home_over_generic():
    states = [
        _state("weather.nws_42_kbos", "partlycloudy", supported_features=6),
        _state("weather.forecast_home", "cloudy", supported_features=3),
    ]
    eid, _feats = hc._resolve_weather_entity(states)
    assert eid == "weather.forecast_home"


def test_resolve_weather_entity_falls_back_to_any_weather():
    states = [_state("weather.nws_42_kbos", "partlycloudy", supported_features=6)]
    eid, feats = hc._resolve_weather_entity(states)
    assert eid == "weather.nws_42_kbos"
    assert feats == 6


def test_resolve_weather_entity_none_when_absent():
    eid, feats = hc._resolve_weather_entity([_state("sensor.foo", "1")])
    assert eid is None
    assert feats is None


# ── _home_coords ──────────────────────────────────────────────────────


def test_home_coords_reads_zone_home():
    states = [_state("zone.home", "1", latitude=42.38, longitude=-71.13)]
    assert hc._home_coords(states) == (42.38, -71.13)


def test_home_coords_none_without_zone():
    assert hc._home_coords([_state("sensor.foo", "1")]) is None


# ── Open-Meteo client parsing ─────────────────────────────────────────


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _patch_httpx(monkeypatch, *, payload=None, aqi_payload=None, status_code=200,
                 raise_error=None):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            if raise_error is not None:
                raise raise_error
            if "air-quality" in url:
                return _FakeResp(status_code, aqi_payload)
            return _FakeResp(status_code, payload)

    monkeypatch.setattr(om.httpx, "AsyncClient", FakeClient)


def test_today_uv_peak_picks_max():
    hourly = {"uv_index": [0.0, 2.1, 7.9, 5.0, None, "bad"]}
    assert om._today_uv_peak(hourly) == 7.9


def test_today_uv_peak_none_when_empty():
    assert om._today_uv_peak({"uv_index": []}) is None
    assert om._today_uv_peak(None) is None


def test_fetch_current_parses_payload(monkeypatch):
    payload = {
        "current": {
            "uv_index": 7.75,
            "apparent_temperature": 77.8,
            "temperature_2m": 79.1,
            "relative_humidity_2m": 40,
        },
        "hourly": {"uv_index": [0.0, 3.2, 8.4, 6.1]},
    }
    _patch_httpx(monkeypatch, payload=payload)
    result = asyncio.run(om.fetch_current(42.38, -71.13))
    assert result == {
        "uv_index": 7.75,
        "apparent_temperature": 77.8,
        "temperature": 79.1,
        "humidity": 40.0,
        "uv_peak": 8.4,
    }


def test_fetch_current_parses_aqi(monkeypatch):
    payload = {"current": {"uv_index": 7.75}}
    aqi_payload = {"current": {"us_aqi": 43}}
    _patch_httpx(monkeypatch, payload=payload, aqi_payload=aqi_payload)
    result = asyncio.run(om.fetch_current(42.38, -71.13))
    assert result == {"uv_index": 7.75, "aqi": 43.0}


def test_fetch_current_aqi_survives_weather_failure(monkeypatch):
    """The two Open-Meteo endpoints are independent; an empty forecast
    response must not discard a good AQI reading (and vice versa)."""
    _patch_httpx(monkeypatch, payload=None,
                 aqi_payload={"current": {"us_aqi": 51}})
    assert asyncio.run(om.fetch_current(42.38, -71.13)) == {"aqi": 51.0}


def test_fetch_current_http_error_returns_none(monkeypatch):
    _patch_httpx(monkeypatch, status_code=500, payload={})
    assert asyncio.run(om.fetch_current(42.38, -71.13)) is None


def test_fetch_current_network_error_returns_none(monkeypatch):
    _patch_httpx(monkeypatch, raise_error=httpx.RequestError("boom"))
    assert asyncio.run(om.fetch_current(42.38, -71.13)) is None


def test_fetch_current_empty_current_returns_none(monkeypatch):
    _patch_httpx(monkeypatch, payload={"current": {}})
    assert asyncio.run(om.fetch_current(42.38, -71.13)) is None
