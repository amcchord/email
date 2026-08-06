"""Regression tests for Envoy period-energy totals on the e-ink dashboard."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.services.eink import ha_client as hc


def _state(entity_id: str, state: str) -> dict:
    return {"entity_id": entity_id, "state": state, "attributes": {}}


def _solar_states(
    *,
    today: str = "47920.191",
    week: str = "47920.191",
    lifetime: str = "47.920191",
) -> list[dict]:
    return [
        _state(hc._SOLAR_POWER_NOW, "5.202"),
        _state(hc._SOLAR_ENERGY_TODAY, today),
        _state(hc._SOLAR_ENERGY_WEEK, week),
        _state(hc._SOLAR_ENERGY_LIFETIME, lifetime),
    ]


def test_history_deltas_override_broken_envoy_period_entities():
    solar = hc.shape_ha_state(
        _solar_states(),
        solar_periods={"todayKwh": 12.577, "weekKwh": 529.647},
    )["solar"]

    assert solar["todayKwh"] == 12.577
    assert solar["weekKwh"] == 529.647
    assert solar["lifetimeMwh"] == 47.920191


def test_lifetime_values_are_not_painted_as_period_totals():
    solar = hc.shape_ha_state(_solar_states())["solar"]

    assert solar["todayKwh"] is None
    assert solar["weekKwh"] is None


def test_valid_reported_period_values_remain_as_fallback():
    solar = hc.shape_ha_state(
        _solar_states(today="21.4", week="487.2"),
    )["solar"]

    assert solar["todayKwh"] == 21.4
    assert solar["weekKwh"] == 487.2


class _FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return [[
            {"state": "47.100", "last_changed": "2026-08-06T11:58:00+00:00"},
            {"state": "47.200", "last_changed": "2026-08-06T11:59:30+00:00"},
            {"state": "47.300", "last_changed": "2026-08-06T12:00:30+00:00"},
        ]]


def test_history_lookup_uses_latest_value_before_target(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None, params=None):
            captured["url"] = url
            captured["params"] = params
            return _FakeResponse()

    monkeypatch.setattr(hc.httpx, "AsyncClient", FakeClient)
    target = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    result = asyncio.run(
        hc.fetch_ha_state_near("http://ha.local", "token", "sensor.energy", target),
    )

    assert result == 47.2
    assert "/api/history/period/" in captured["url"]
    assert captured["params"]["filter_entity_id"] == "sensor.energy"
    assert captured["params"]["minimal_response"] == "true"
    assert captured["params"]["no_attributes"] == "true"


def test_period_totals_use_local_midnight_and_rolling_week(monkeypatch):
    targets = []

    async def fake_state_near(url, token, entity_id, target, timeout=5.0):
        targets.append(target)
        if target.hour == 4:
            return 47.907765
        return 47.390695

    monkeypatch.setattr(hc, "fetch_ha_state_near", fake_state_near)
    now = datetime(2026, 8, 6, 14, 30, tzinfo=timezone.utc)
    totals = asyncio.run(
        hc.fetch_ha_solar_period_totals(
            "http://ha.local",
            "token",
            47.920342,
            "America/New_York",
            now=now,
        ),
    )

    assert targets[0] == datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc)
    assert targets[1] == datetime(2026, 7, 30, 14, 30, tzinfo=timezone.utc)
    assert totals["todayKwh"] == pytest.approx(12.577)
    assert totals["weekKwh"] == pytest.approx(529.647)
