"""Sauna heat-up forecast: parity with the Home Assistant panel, and its plumbing.

The expected numbers below were produced by running the real panel code,
``www/sauna-room-panel.js`` in the HomeAssistant project (?v=5, Nov 1 2026),
over the same inputs. They pin the port, not the accuracy of the model.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.services.eink import ha_client as hc
from backend.services.eink import sauna_forecast as sf
from backend.services.eink.pillow.ha_view import _build_sauna_view, _span
from backend.services.eink.pillow.palette import get_palette
from backend.services.eink.pillow.render_ctx import build_render_context

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
T = NOW.timestamp()


def ago(minutes):
    return T - minutes * 60


@pytest.mark.parametrize(
    ("inputs", "ready", "target", "fan_at", "t60", "r60"),
    [
        (dict(thermostat=41, room=41, outdoor=38), 102, 81, 81, 155.597134, 122.907627),
        (dict(thermostat=123, room=91, outdoor=45, target=185, age=40, elements=3),
         60, 39, 39, 188.265422, 165.192075),
        (dict(thermostat=186, room=150, outdoor=45, target=185, age=70, elements=1),
         24, 0, 0, 184.417916, 174.838144),
        (dict(thermostat=165, room=146, outdoor=45, target=185, age=80, elements=3,
              fan_left=4, fan_speed="medium", fan_done=True, stored_heat=5),
         20, 14, None, 185.634937, 175.211787),
        (dict(thermostat=100, room=80, outdoor=20, target=185, age=30, elements=3,
              plan_fan=False),
         71, 51, None, 184.450025, 159.159451),
        (dict(thermostat=50, room=50, outdoor=40, target=140),
         None, None, 48, 144.193103, 117.025375),
    ],
)
def test_simulate_matches_the_panel(inputs, ready, target, fan_at, t60, r60):
    p = sf.simulate(**inputs)
    assert sf._first(p.rooms, sf.READY_F) == ready
    assert sf._first(p.thermostats, sf.TARGET_F) == target
    assert p.fan_at == fan_at
    assert p.thermostats[60] == pytest.approx(t60, abs=1e-6)
    assert p.rooms[60] == pytest.approx(r60, abs=1e-6)


def test_session_facts_match_the_panel():
    s = sf.session_facts({
        "climate": [
            {"t": ago(200), "s": "off", "fan": "off"},
            {"t": ago(90), "s": "heat", "fan": "off"},
            {"t": ago(30), "s": "unavailable", "fan": "off"},
            {"t": ago(29), "s": "heat", "fan": "off"},
            {"t": ago(15), "s": "heat", "fan": "medium"},
            {"t": ago(5), "s": "heat", "fan": "off"},
        ],
        "thermostat": [{"t": ago(100), "v": 190}, {"t": ago(20), "v": 185}],
        "room": [{"t": ago(60), "v": 120}, {"t": ago(2), "v": 166}],
    }, T)
    assert s.start == ago(90), "an outage does not restart the session"
    assert len(s.runs) == 1
    assert s.fan_done is True
    assert s.stored_heat == pytest.approx(4.513219, abs=1e-6)
    assert s.target_at == ago(20), "readings from before the session do not count"
    assert s.ready_at == ago(2)
    assert sf.session_facts({"climate": [{"t": ago(9), "s": "off"}]}, T) is None


def session(**extra):
    return sf.Session(**{"start": ago(40), **extra})


def forecast(**inputs):
    base = dict(outdoor=38, target=185, elements=0, session_minutes=120,
                timer_end=None, now=T, session=session())
    return sf.forecast_heating(**{**base, **inputs})


def minutes_from_now(iso):
    return (datetime.fromisoformat(iso).timestamp() - T) / 60


@pytest.mark.parametrize(
    ("inputs", "ready_mark", "target_mark", "fan_state"),
    [
        (dict(thermostat=123, room=91, elements=3), 61, 40, "planned"),
        (dict(thermostat=186, room=150, elements=1, session=session(target_at=ago(1))),
         24, -1, "due"),
        (dict(thermostat=165, room=146, elements=3, timer_end=T + 240,
              session=session(target_at=ago(8), fan_done=True,
                              runs=[sf.FanRun(ago(6), None, "medium")])),
         24, -8, "running"),
        (dict(thermostat=192, room=160,
              session=session(start=ago(100), ready_at=ago(3), target_at=ago(20))),
         -3, -20, "optional"),
    ],
)
def test_forecast_card_states_match_the_panel(inputs, ready_mark, target_mark, fan_state):
    f = forecast(**inputs)
    assert minutes_from_now(f["readyAt"]) == ready_mark
    assert minutes_from_now(f["targetAt"]) == target_mark
    assert f["fan"]["state"] == fan_state


def test_running_fan_reports_time_left_from_the_timer():
    f = forecast(thermostat=165, room=146, elements=3, timer_end=T + 240,
                 session=session(target_at=ago(8), fan_done=True,
                                 runs=[sf.FanRun(ago(6), None, "medium")]))
    assert f["fan"]["minutesLeft"] == 4


def test_a_dip_below_ready_during_a_fan_run_does_not_undo_ready():
    f = forecast(thermostat=192, room=160,
                 session=session(start=ago(100), ready_at=ago(3), target_at=ago(20)))
    assert f["readyReached"] is True
    assert f["readyInMinutes"] is None


def test_session_that_ends_first_is_called_out():
    f = forecast(thermostat=90, room=70, elements=3, session_minutes=45)
    assert minutes_from_now(f["sessionEndsBeforeReadyAt"]) == 5
    assert forecast(thermostat=123, room=91, elements=3)["sessionEndsBeforeReadyAt"] is None


def test_a_low_target_never_promises_ready():
    f = forecast(thermostat=50, room=50, target=140)
    assert f["readyAt"] is None and f["targetAt"] is None
    assert f["readyReached"] is False


def _state(entity, value, **attributes):
    return {"entity_id": entity, "state": value, "attributes": attributes}


def _heating_states(thermostat=123, room="91"):
    return [
        {**_state(hc._SAUNA_ID, "heat", current_temperature=thermostat, temperature=185,
                  fan_mode="off"),
         "last_changed": (NOW - timedelta(minutes=40)).isoformat()},
        _state(hc._SAUNA_ROOM_TEMP, room),
        _state(hc._SAUNA_HEATERS, "3"),
        _state(hc._SAUNA_DURATION, "120"),
        _state(hc._SAUNA_FORECAST_OUTDOOR, "45"),
    ]


def test_shape_adds_a_forecast_only_while_heating():
    shaped = hc.shape_ha_state(_heating_states(), fetched_at=NOW)["sauna"]
    assert shaped["forecast"]["readyInMinutes"] == 60
    assert shaped["forecast"]["fan"]["state"] == "planned"

    off = [{**_state(hc._SAUNA_ID, "off", current_temperature=68)}]
    assert "forecast" not in hc.shape_ha_state(off, fetched_at=NOW)["sauna"]


def test_forecast_pauses_without_the_room_sensor():
    states = _heating_states(room="unavailable")
    assert hc.shape_ha_state(states, fetched_at=NOW)["sauna"]["forecast"] is None


def test_shape_uses_session_history_for_milestones():
    history = {
        "climate": [{"t": ago(100), "s": "heat", "fan": "off"}],
        "thermostat": [{"t": ago(20), "v": 185}],
        "room": [{"t": ago(3), "v": 166}],
    }
    shaped = hc.shape_ha_state(_heating_states(thermostat=192, room="160"),
                               fetched_at=NOW, sauna_history=history)["sauna"]
    assert shaped["forecast"]["readyReached"] is True
    assert minutes_from_now(shaped["forecast"]["readyAt"]) == -3


def test_view_localizes_forecast_labels():
    shaped = hc.shape_ha_state(_heating_states(), fetched_at=NOW)
    ctx = build_render_context(
        {"fetchedAt": NOW.isoformat()}, get_palette("editorial", "bw"),
        tz_name="America/New_York",
    )
    view = _build_sauna_view(shaped, ctx)
    forecast = view.extras["forecast"]
    # 13:00 UTC on Nov 1 2026 is 8:00 AM Eastern, one hour after DST ended.
    assert forecast["ready_label"] == "8:00 AM"
    assert forecast["ready_in"] == "1 h"
    assert forecast["fan_label"] == "7:39 AM"
    assert view.eyebrow_kicker == "Sauna · Heating"


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
async def test_history_fetch_parses_climate_and_minimal_sensor_rows(monkeypatch):
    def handler(request):
        entity = request.url.params["filter_entity_id"]
        if entity == hc._SAUNA_ID:
            assert "minimal_response" not in request.url.params
            return httpx.Response(200, json=[[
                {"entity_id": entity, "state": "heat", "last_updated": "2026-11-01T11:00:00+00:00",
                 "attributes": {"fan_mode": "off"}},
                {"entity_id": entity, "state": "heat", "last_updated": "2026-11-01T11:30:00+00:00",
                 "attributes": {"fan_mode": "medium"}},
                {"entity_id": entity, "state": "unavailable", "last_updated": "2026-11-01T11:31:00+00:00",
                 "attributes": {}},
            ]])
        assert "minimal_response" in request.url.params
        return httpx.Response(200, json=[
            [{"entity_id": hc._SAUNA_ROOM_TEMP, "state": "90", "last_changed": "2026-11-01T11:00:00+00:00"},
             {"state": "unavailable", "last_changed": "2026-11-01T11:01:00+00:00"},
             {"state": "120.5", "last_changed": "2026-11-01T11:30:00+00:00"}],
            [{"entity_id": hc._SAUNA_THERMOSTAT_TEMP, "state": "150", "last_changed": "2026-11-01T11:00:00+00:00"}],
        ])

    _mock_ha(monkeypatch, handler)
    history = await hc.fetch_ha_sauna_history("http://ha.example.test/", "token", now=NOW)
    assert [row["fan"] for row in history["climate"]] == ["off", "medium", "medium"]
    assert history["climate"][2]["s"] == "unavailable"
    assert [row["v"] for row in history["room"]] == [90.0, 120.5]
    assert [row["v"] for row in history["thermostat"]] == [150.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(500, text="boom"),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"unexpected": "shape"}),
])
async def test_history_failure_returns_none_and_forecast_still_runs(monkeypatch, response):
    _mock_ha(monkeypatch, lambda request: response)
    assert await hc.fetch_ha_sauna_history("http://ha.example.test", "token", now=NOW) is None
    shaped = hc.shape_ha_state(_heating_states(), fetched_at=NOW, sauna_history=None)
    assert shaped["sauna"]["forecast"]["readyAt"] is not None
