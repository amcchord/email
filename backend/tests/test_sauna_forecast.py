"""Sauna heat-up forecast: reading Home Assistant's sensor.sauna_heat_forecast.

The samples in fixtures/sauna_heat_forecast.json were produced by Home
Assistant's own model (``custom_components/sauna_forecast/model.py`` in the
HomeAssistant project, model 2026-11-02.1). They pin how the screens read the
sensor, not the model's accuracy, which that project tests against its panel.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from backend.services.eink import ha_client as hc
from backend.services.eink import sauna_forecast as sf
from backend.services.eink.pillow.ha_view import _build_sauna_view, _span
from backend.services.eink.pillow.palette import get_palette
from backend.services.eink.pillow.render_ctx import build_render_context

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "sauna_heat_forecast.json").read_text())
# The heating and ready samples were computed at 19:12 UTC, 2:12 PM Eastern.
NOW = datetime(2026, 11, 1, 19, 12, tzinfo=timezone.utc)
T = NOW.timestamp()


def sample(name="heating", **attributes):
    entity = copy.deepcopy(SAMPLES[name])
    entity["attributes"].update(attributes)
    return entity


def ctx():
    return build_render_context({"fetchedAt": NOW.isoformat()}, get_palette("editorial", "bw"),
                                tz_name="America/New_York")


def test_the_sensor_maps_onto_the_card():
    forecast = sf.from_sensor(sample(), [], T)
    assert forecast["modelVersion"] == SAMPLES["model_version"]
    assert forecast["readyReached"] is False
    assert forecast["readyAt"] == "2026-11-01T20:11:00+00:00"
    assert (forecast["readyInMinutes"], forecast["targetInMinutes"]) == (59, 50)
    assert forecast["fan"] == {"state": "planned", "auto": True,
                               "at": "2026-11-01T19:45:00+00:00", "minutesLeft": None}
    assert forecast["fanInMinutes"] == 33
    assert len(forecast["roomCurve"]) == 181
    assert forecast["roomCurve"][0] == 91


def test_minutes_and_the_curve_move_to_render_time():
    curve = SAMPLES["heating"]["attributes"]["room_curve"]
    forecast = sf.from_sensor(sample(), [], T + 70)
    assert (forecast["readyInMinutes"], forecast["fanInMinutes"]) == (58, 32)
    assert forecast["roomCurve"] == curve[1:]
    assert forecast["readyAt"] == "2026-11-01T20:11:00+00:00", "absolute times don't move"


def test_a_stale_sensor_gives_no_forecast():
    assert sf.from_sensor(sample(), [], T + sf.STALE_SECONDS) is not None
    assert sf.from_sensor(sample(), [], T + sf.STALE_SECONDS + 1) is None


@pytest.mark.parametrize("entity", [
    None,
    {"entity_id": sf.SENSOR, "state": "unknown"},
    sample(active=False),
    sample(reason="room sensor unavailable"),
    sample(computed_at=None),
    sample(computed_at="not a time"),
])
def test_no_forecast_without_a_live_session_reading(entity):
    assert sf.from_sensor(entity, [], T) is None


def test_room_history_is_this_session_only():
    rows = [{"t": T - 3600, "v": 60}, {"t": T - 600, "v": 88}, {"t": T + 60, "v": 92}]
    forecast = sf.from_sensor(sample(), rows, T)
    assert forecast["roomHistory"] == [{"minutes": -10.0, "value": 88}]


def test_odd_values_are_dropped_rather_than_guessed():
    forecast = sf.from_sensor(
        sample(fan_state="spinning", ready_in_minutes="soon", room_curve="flat"), [], T)
    assert forecast["fan"]["state"] is None
    assert forecast["readyInMinutes"] is None
    assert forecast["roomCurve"] == []


def _heating_states(*extra):
    return [
        {"entity_id": hc._SAUNA_ID, "state": "heat",
         "attributes": {"current_temperature": 123, "temperature": 185, "fan_mode": "off"}},
        {"entity_id": hc._SAUNA_ROOM_TEMP, "state": "91", "attributes": {}},
        *extra,
    ]


def test_shape_reads_the_sensor_only_while_heating():
    shaped = hc.shape_ha_state(_heating_states(sample()), fetched_at=NOW)["sauna"]
    assert shaped["forecast"]["readyInMinutes"] == 59

    off = [{"entity_id": hc._SAUNA_ID, "state": "off", "attributes": {}}, sample()]
    assert "forecast" not in hc.shape_ha_state(off, fetched_at=NOW)["sauna"]

    missing = hc.shape_ha_state(_heating_states(), fetched_at=NOW)["sauna"]
    assert missing["forecast"] is None
    assert missing["roomTemp"] == 91, "the card keeps its live readings"


def test_view_localizes_the_sensor():
    view = _build_sauna_view({"sauna": {"forecast": sf.from_sensor(sample(), [], T)}}, ctx())
    forecast = view.extras["forecast"]
    # 20:11 UTC on Nov 1 2026 is 3:11 PM Eastern, the day DST ended.
    assert forecast["ready_label"] == "3:11 PM"
    assert forecast["ready_in"] == "59 min"
    assert (forecast["fan_label"], forecast["fan_note"]) == ("2:45 PM", "Auto 10 min")
    assert forecast["fan_auto"] is True
    assert view.eyebrow_kicker == "Sauna · Heating"

    ready = _build_sauna_view(
        {"sauna": {"forecast": sf.from_sensor(sample("ready"), [], T)}}, ctx())
    assert ready.eyebrow_kicker == "Sauna · Ready"
    assert ready.extras["forecast"]["ready_label"] == "2:07 PM"
    assert (ready.extras["forecast"]["fan_label"], ready.extras["forecast"]["fan_note"]) == (
        "1:47 PM", "Ran")


@pytest.mark.parametrize(("attributes", "label", "note"), [
    (dict(fan_state="running", fan_minutes_left=6, fan_at="2026-11-01T19:08:00+00:00"),
     "Running", "6 min left"),
    (dict(fan_state="due", fan_in_minutes=0), "Soon", "Auto 10 min"),
    (dict(fan_state="due", fan_in_minutes=0, auto_fan=False), "Run now", "10 min Med"),
    (dict(auto_fan=False), "2:45 PM", "10 min Med"),
    (dict(fan_state="skipped", fan_at=None), "Didn't run", "Auto fan"),
    (dict(fan_state="optional", fan_at=None), "Optional", "Room even"),
    (dict(fan_state="spinning"), "—", None),
])
def test_fan_labels_follow_the_sensor(attributes, label, note):
    raw = sf.from_sensor(sample(**attributes), [], T)
    forecast = _build_sauna_view({"sauna": {"forecast": raw}}, ctx()).extras["forecast"]
    assert (forecast["fan_label"], forecast["fan_note"]) == (label, note)


@pytest.mark.parametrize(("minutes", "label"), [
    (1, "1 min"), (59, "59 min"), (60, "1 h"), (61, "1 h 1 min"), (None, "—"),
])
def test_span_labels(minutes, label):
    assert _span(minutes) == label


def _mock_ha(monkeypatch, handler):
    real = httpx.AsyncClient

    def client(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(hc.httpx, "AsyncClient", client)


@pytest.mark.asyncio
async def test_history_fetch_reads_the_room_since_the_session_start(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[[
            {"entity_id": hc._SAUNA_ROOM_TEMP, "state": "90", "last_changed": "2026-11-01T18:40:00+00:00"},
            {"state": "unavailable", "last_changed": "2026-11-01T18:41:00+00:00"},
            {"state": "120.5", "last_changed": "2026-11-01T19:10:00+00:00"},
        ]])

    _mock_ha(monkeypatch, handler)
    since = NOW - timedelta(minutes=40)
    rows = await hc.fetch_ha_sauna_history("http://ha.example.test/", "token", since, now=NOW)
    assert [row["v"] for row in rows] == [90.0, 120.5]
    request = seen[0]
    assert request.url.params["filter_entity_id"] == hc._SAUNA_ROOM_TEMP
    assert "minimal_response" in request.url.params
    assert since.isoformat() in request.url.path

    # A session older than the look-back reads only the last few hours.
    await hc.fetch_ha_sauna_history("http://ha.example.test", "token", NOW - timedelta(hours=9), now=NOW)
    floor = NOW - timedelta(hours=hc._SAUNA_HISTORY_HOURS)
    assert floor.isoformat() in seen[1].url.path


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(500, text="boom"),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"unexpected": "shape"}),
])
async def test_history_failure_returns_none_and_the_forecast_still_shows(monkeypatch, response):
    _mock_ha(monkeypatch, lambda request: response)
    since = NOW - timedelta(minutes=40)
    assert await hc.fetch_ha_sauna_history("http://ha.example.test", "token", since, now=NOW) is None
    shaped = hc.shape_ha_state(_heating_states(sample()), fetched_at=NOW, sauna_history=None)
    assert shaped["sauna"]["forecast"]["readyAt"] is not None
    assert shaped["sauna"]["forecast"]["roomHistory"] == []
