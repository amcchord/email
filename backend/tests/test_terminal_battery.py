"""Pure-unit coverage for sparse terminal battery history and prediction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.terminal.battery import (
    BatteryReading,
    estimate_battery_health,
    normalize_battery_mv,
    normalize_battery_pct,
    should_record_sample,
)

START = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _reading(
    day: float,
    pct: int | None,
    mv: int | None = 3900,
    boot_count: int | None = None,
) -> BatteryReading:
    return BatteryReading(
        observed_at=START + timedelta(days=day),
        battery_pct=pct,
        battery_mv=mv,
        boot_count=boot_count,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (-1, None),
        (0, 0),
        (50, 50),
        (100, 100),
        (101, None),
    ],
)
def test_battery_percentage_validation(value, expected):
    assert normalize_battery_pct(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (2499, None),
        (2500, 2500),
        (3900, 3900),
        (5000, 5000),
        (5001, None),
    ],
)
def test_battery_voltage_validation(value, expected):
    assert normalize_battery_mv(value) == expected


def test_invalid_readings_do_not_become_health_samples():
    health = estimate_battery_health([_reading(0, 101, 6000)])

    assert health.status == "unknown"
    assert health.current_pct is None
    assert health.current_mv is None
    assert health.sample_count == 0


def test_sparse_sampling_keeps_changes_and_six_hour_heartbeats():
    latest = _reading(0, 72, 3900)

    assert not should_record_sample(
        None,
        observed_at=START,
        battery_pct=None,
        battery_mv=None,
    )
    assert should_record_sample(
        None,
        observed_at=START,
        battery_pct=72,
        battery_mv=3900,
    )
    assert not should_record_sample(
        latest,
        observed_at=START + timedelta(hours=5, minutes=59),
        battery_pct=72,
        battery_mv=3949,
    )
    assert should_record_sample(
        latest,
        observed_at=START + timedelta(minutes=5),
        battery_pct=71,
        battery_mv=3900,
    )
    assert should_record_sample(
        latest,
        observed_at=START + timedelta(minutes=5),
        battery_pct=72,
        battery_mv=3950,
    )
    assert should_record_sample(
        latest,
        observed_at=START + timedelta(hours=6),
        battery_pct=72,
        battery_mv=3900,
    )


def test_sparse_sampling_rate_limits_changes_and_keeps_new_voltage():
    latest = _reading(0, 72, None)

    assert not should_record_sample(
        latest,
        observed_at=START + timedelta(minutes=4, seconds=59),
        battery_pct=71,
        battery_mv=3900,
    )
    assert should_record_sample(
        latest,
        observed_at=START + timedelta(minutes=5),
        battery_pct=72,
        battery_mv=3900,
    )


def test_partial_headers_carry_forward_latest_known_percentage_and_voltage():
    health = estimate_battery_health(
        [
            _reading(0, 72, None),
            _reading(0.5, None, 3880),
            _reading(1, 70, None),
        ]
    )

    assert health.current_pct == 70
    assert health.current_mv == 3880


def test_discharge_prediction_uses_ordered_history():
    samples = [
        _reading(3, 65, 3750),
        _reading(1, 75, 3850),
        _reading(0, 80, 3900),
        _reading(2, 70, 3800),
    ]

    health = estimate_battery_health(samples)

    assert health.status == "healthy"
    assert health.current_pct == 65
    assert health.current_mv == 3750
    assert health.observed_at == START + timedelta(days=3)
    assert health.sample_count == 4
    assert health.trend_days == 3.0
    assert health.drain_pct_per_day == 5.0
    assert health.estimated_days_remaining == 13.0
    assert health.estimated_empty_at == START + timedelta(days=16)
    assert health.estimated_charge_at == START + timedelta(days=12)
    assert health.confidence == "medium"
    assert health.notice is None


@pytest.mark.parametrize(
    ("pct", "status", "notice_fragment"),
    [
        (10, "charge_now", "Charge this terminal now"),
        (20, "charge_soon", "Charge this terminal soon"),
        (21, "healthy", None),
    ],
)
def test_low_battery_notices_do_not_require_a_trend(pct, status, notice_fragment):
    health = estimate_battery_health([_reading(0, pct)])

    assert health.status == status
    if notice_fragment is None:
        assert health.notice is None
    else:
        assert notice_fragment in health.notice
        assert f"{pct}%" in health.notice


def test_prediction_warns_before_the_battery_crosses_the_low_threshold():
    health = estimate_battery_health(
        [_reading(0, 40), _reading(1, 35), _reading(2, 30), _reading(3, 25)]
    )

    assert health.status == "charge_soon"
    assert health.current_pct == 25
    assert health.estimated_charge_at == START + timedelta(days=4)
    assert health.notice == "Plan to charge this terminal within about 1 day."


def test_single_significant_rise_is_only_possible_charging():
    health = estimate_battery_health(
        [_reading(0, 80), _reading(1, 60), _reading(2, 90)]
    )

    assert health.status == "possible_charging"
    assert health.current_pct == 90
    assert health.notice == (
        "Battery level rose; waiting for another reading to confirm charging."
    )
    assert health.drain_pct_per_day is None
    assert health.estimated_days_remaining is None
    assert health.estimated_empty_at is None


def test_two_rising_readings_confirm_charging():
    health = estimate_battery_health(
        [_reading(0, 60), _reading(1, 70), _reading(2, 90)]
    )

    assert health.status == "charging"
    assert health.notice == "Battery level is rising; charging detected."


def test_low_battery_warning_takes_precedence_over_a_noisy_rise():
    health = estimate_battery_health([_reading(0, 3), _reading(1, 9)])

    assert health.status == "charge_now"
    assert health.notice == "Charge this terminal now — battery is at 9%."


def test_rise_across_a_reboot_does_not_claim_charging():
    health = estimate_battery_health(
        [_reading(0, 60, boot_count=7), _reading(1, 90, boot_count=8)]
    )

    assert health.status == "healthy"
    assert health.notice is None


def test_discharge_prediction_restarts_after_a_charge_cycle():
    health = estimate_battery_health(
        [
            _reading(0, 80),
            _reading(1, 60),
            _reading(2, 90),
            _reading(3, 85),
            _reading(4, 80),
        ]
    )

    assert health.status == "healthy"
    assert health.current_pct == 80
    assert health.trend_days == 2.0
    assert health.drain_pct_per_day == 5.0
    assert health.estimated_days_remaining == 16.0
    assert health.estimated_empty_at == START + timedelta(days=20)
    assert health.confidence == "low"


def test_stale_telemetry_suppresses_old_runtime_prediction():
    health = estimate_battery_health(
        [_reading(0, 80), _reading(1, 75), _reading(2, 70)],
        now=START + timedelta(days=5),
    )

    assert health.status == "stale"
    assert health.current_pct == 70
    assert health.estimated_days_remaining is None
    assert health.notice == (
        "Battery estimate is stale — last battery check-in was 3 days ago at 70%."
    )
