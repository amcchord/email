#!/usr/bin/env python3
"""Regenerate backend/tests/fixtures/sauna_heat_forecast.json.

The samples are sensor.sauna_heat_forecast as Home Assistant's own model
(``custom_components/sauna_forecast/model.py`` in the HomeAssistant project)
publishes it. Regenerate only when that sensor's contract changes; a refit alone
needs nothing here. Then rerun test_sauna_forecast.py and update what it pins.

Usage:
    python3 scripts/sauna_forecast_samples.py \
        ~/Development/HomeAssistant/config-backup/config/custom_components/sauna_forecast/model.py \
        backend/tests/fixtures/sauna_heat_forecast.json
"""
import importlib.util
import json
import sys
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("ha_sauna_model", sys.argv[1])
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)

MIN = 60_000


def ms(dt):
    return int(dt.timestamp() * 1000)


def entity(states, history, now):
    ready_ms, attrs = model.evaluate(states, history, now)
    state = "unknown" if ready_ms is None else datetime.fromtimestamp(
        ready_ms / 1000, timezone.utc).isoformat(timespec="seconds")
    return {"entity_id": "sensor.sauna_heat_forecast", "state": state, "attributes": attrs}


def inputs(*, start, thermostat, room, elements, duration, fan="off"):
    return {
        model.CLIMATE: {"state": "heat", "last_changed": start, "attributes": {
            "current_temperature": thermostat, "temperature": 185, "fan_mode": fan}},
        model.ROOM: {"state": str(room), "attributes": {}, "last_changed": start},
        model.OUTDOOR: {"state": "45", "attributes": {}, "last_changed": start},
        model.ELEMENTS: {"state": str(elements), "attributes": {}, "last_changed": start},
        model.SESSION: {"state": str(duration), "attributes": {}, "last_changed": start},
        model.TIMER: {"state": "idle", "attributes": {}, "last_changed": start},
        model.AUTO_FAN: {"state": "on", "attributes": {}, "last_changed": start},
        model.AUTO_FAN_RAN: {"state": "off", "attributes": {}, "last_changed": start},
    }


out = {"model_version": model.MODEL_VERSION}

# Forty minutes into a cold start; the auto fan is still ahead.
now = ms(datetime(2026, 11, 1, 19, 12, tzinfo=timezone.utc))
start = now - 40 * MIN
out["heating"] = entity(
    inputs(start=start, thermostat=123, room=91, elements=3, duration=180),
    {"climate": [{"t": start, "s": "heat", "fan": "off"}], "thermostat": [],
     "room": [{"t": start, "v": 64}, {"t": now - 2 * MIN, "v": 90}]},
    now,
)

# Ready five minutes ago, after a ten-minute fan run at the backoff.
start = now - 100 * MIN
out["ready"] = entity(
    inputs(start=start, thermostat=186, room=168, elements=1, duration=180),
    {"climate": [{"t": start, "s": "heat", "fan": "off"},
                 {"t": start + 75 * MIN, "s": "heat", "fan": "medium"},
                 {"t": start + 85 * MIN, "s": "heat", "fan": "off"}],
     "thermostat": [{"t": start + 70 * MIN, "v": 177}, {"t": start + 90 * MIN, "v": 186}],
     "room": [{"t": start, "v": 60}, {"t": start + 74 * MIN, "v": 140}, {"t": now - 5 * MIN, "v": 166}]},
    now,
)

# The layout audit's long case: a one-hour session that ends before it's ready.
now = ms(datetime(2026, 5, 5, 22, 0, tzinfo=timezone.utc))
out["short_session"] = entity(
    inputs(start=now, thermostat=127, room=84, elements=3, duration=60), None, now)

with open(sys.argv[2], "w") as f:
    # One sample per line keeps the file reviewable without spreading the curves out.
    f.write("{\n" + ",\n".join(f" {json.dumps(k)}: {json.dumps(v)}" for k, v in out.items()) + "\n}\n")
for name in ("heating", "ready", "short_session"):
    a = out[name]["attributes"]
    print(name, out[name]["state"], {k: v for k, v in a.items() if not k.endswith("curve")})
