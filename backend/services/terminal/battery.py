"""Battery telemetry sampling and conservative runtime prediction."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

CHARGE_NOTICE_PCT = 20
CHARGE_NOW_PCT = 10
MIN_SAMPLE_INTERVAL = timedelta(minutes=5)
SAMPLE_HEARTBEAT = timedelta(hours=6)
MIN_TREND_SPAN = timedelta(hours=12)
SIGNIFICANT_CHARGE_RISE_PCT = 5
STALE_AFTER = timedelta(hours=48)
BATTERY_RETENTION = timedelta(days=90)


class BatterySampleLike(Protocol):
    observed_at: datetime
    battery_pct: Optional[int]
    battery_mv: Optional[int]
    boot_count: Optional[int]


@dataclass(frozen=True)
class BatteryReading:
    observed_at: datetime
    battery_pct: Optional[int]
    battery_mv: Optional[int]
    boot_count: Optional[int] = None


@dataclass(frozen=True)
class BatteryHealth:
    status: str
    current_pct: Optional[int]
    current_mv: Optional[int]
    observed_at: Optional[datetime]
    sample_count: int
    trend_days: Optional[float] = None
    drain_pct_per_day: Optional[float] = None
    estimated_days_remaining: Optional[float] = None
    estimated_empty_at: Optional[datetime] = None
    estimated_charge_at: Optional[datetime] = None
    confidence: Optional[str] = None
    notice: Optional[str] = None


def normalize_battery_pct(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    value = int(value)
    return value if 0 <= value <= 100 else None


def normalize_battery_mv(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    value = int(value)
    # Wide enough for common 1S Li-ion measurement/calibration variance while
    # rejecting missing/garbled ADC values.
    return value if 2500 <= value <= 5000 else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def should_record_sample(
    latest: Optional[BatterySampleLike],
    *,
    observed_at: datetime,
    battery_pct: Optional[int],
    battery_mv: Optional[int],
) -> bool:
    """Keep meaningful changes plus a six-hour heartbeat, not every HTTP hit."""
    if battery_pct is None and battery_mv is None:
        return False
    if latest is None:
        return True
    elapsed = _utc(observed_at) - _utc(latest.observed_at)
    # A malicious or noisy client can vary its headers on every HTTP request.
    # Bound history growth independently of the device's configured cadence.
    if elapsed < MIN_SAMPLE_INTERVAL:
        return False
    if battery_pct is not None and (
        latest.battery_pct is None or battery_pct != latest.battery_pct
    ):
        return True
    if (
        battery_mv is not None
        and (
            latest.battery_mv is None
            or abs(battery_mv - latest.battery_mv) >= 50
        )
    ):
        return True
    return elapsed >= SAMPLE_HEARTBEAT


def estimate_battery_health(
    samples: Iterable[BatterySampleLike],
    *,
    now: datetime | None = None,
) -> BatteryHealth:
    readings = sorted(
        (
            BatteryReading(
                observed_at=_utc(sample.observed_at),
                battery_pct=normalize_battery_pct(sample.battery_pct),
                battery_mv=normalize_battery_mv(sample.battery_mv),
                boot_count=getattr(sample, "boot_count", None),
            )
            for sample in samples
            if sample.observed_at is not None
        ),
        key=lambda sample: sample.observed_at,
    )
    readings = [r for r in readings if r.battery_pct is not None or r.battery_mv is not None]
    if not readings:
        return BatteryHealth(
            status="unknown",
            current_pct=None,
            current_mv=None,
            observed_at=None,
            sample_count=0,
        )

    current = readings[-1]
    pct_readings = [r for r in readings if r.battery_pct is not None]
    mv_readings = [r for r in readings if r.battery_mv is not None]
    current_pct = current.battery_pct
    if current_pct is None and pct_readings:
        current_pct = pct_readings[-1].battery_pct
    current_mv = current.battery_mv
    if current_mv is None and mv_readings:
        current_mv = mv_readings[-1].battery_mv

    base = BatteryHealth(
        status="unknown",
        current_pct=current_pct,
        current_mv=current_mv,
        observed_at=current.observed_at,
        sample_count=len(readings),
    )
    if current_pct is None:
        return base

    if now is not None:
        age = _utc(now) - current.observed_at
        if age > STALE_AFTER:
            age_days = max(2, round(age.total_seconds() / 86400))
            return BatteryHealth(
                **{
                    **base.__dict__,
                    "status": "stale",
                    "notice": (
                        f"Battery estimate is stale — last battery check-in was "
                        f"{age_days} days ago at {current_pct}%."
                    ),
                }
            )

    immediate_status = "healthy"
    immediate_notice = None
    if current_pct <= CHARGE_NOW_PCT:
        immediate_status = "charge_now"
        immediate_notice = f"Charge this terminal now — battery is at {current_pct}%."
    elif current_pct <= CHARGE_NOTICE_PCT:
        immediate_status = "charge_soon"
        immediate_notice = f"Charge this terminal soon — battery is at {current_pct}%."

    # A significant rise starts a fresh discharge segment, but a single rise
    # can be ADC recalibration. Require two consecutive rising readings before
    # calling the terminal "charging", and never let that inference suppress
    # a low-battery warning. Boot-count changes are treated as restarts rather
    # than charging evidence.
    segment_start = 0
    latest_significant_rise = False
    latest_rise_crossed_boot = False
    for idx in range(1, len(pct_readings)):
        previous = pct_readings[idx - 1]
        reading = pct_readings[idx]
        rise = int(reading.battery_pct or 0) - int(previous.battery_pct or 0)
        if rise >= SIGNIFICANT_CHARGE_RISE_PCT:
            segment_start = idx
            if idx == len(pct_readings) - 1:
                latest_significant_rise = True
                latest_rise_crossed_boot = (
                    previous.boot_count is not None
                    and reading.boot_count is not None
                    and previous.boot_count != reading.boot_count
                )
    segment = pct_readings[segment_start:]

    if immediate_status != "healthy":
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": immediate_status,
                "notice": immediate_notice,
            }
        )

    if latest_significant_rise and not latest_rise_crossed_boot:
        confirmed = False
        if len(pct_readings) >= 3:
            before = pct_readings[-3]
            previous = pct_readings[-2]
            latest = pct_readings[-1]
            boots_stable = all(
                a.boot_count is None
                or b.boot_count is None
                or a.boot_count == b.boot_count
                for a, b in ((before, previous), (previous, latest))
            )
            confirmed = (
                boots_stable
                and int(before.battery_pct or 0) < int(previous.battery_pct or 0)
                < int(latest.battery_pct or 0)
                and int(latest.battery_pct or 0) - int(before.battery_pct or 0)
                >= SIGNIFICANT_CHARGE_RISE_PCT
            )
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": "charging" if confirmed else "possible_charging",
                "notice": (
                    "Battery level is rising; charging detected."
                    if confirmed
                    else "Battery level rose; waiting for another reading to confirm charging."
                ),
            }
        )

    if len(segment) < 3:
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": immediate_status,
                "notice": immediate_notice,
            }
        )

    first = segment[0]
    last = segment[-1]
    span = last.observed_at - first.observed_at
    drop = int(first.battery_pct or 0) - int(last.battery_pct or 0)
    if span < MIN_TREND_SPAN or drop < 2:
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": immediate_status,
                "notice": immediate_notice,
            }
        )

    span_days = span.total_seconds() / 86400
    drain_per_day = drop / span_days
    if drain_per_day < 0.05 or drain_per_day > 100:
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": immediate_status,
                "notice": immediate_notice,
            }
        )

    days_remaining = current_pct / drain_per_day
    days_to_notice = max(0.0, (current_pct - CHARGE_NOTICE_PCT) / drain_per_day)
    estimated_empty_at = last.observed_at + timedelta(days=days_remaining)
    estimated_charge_at = last.observed_at + timedelta(days=days_to_notice)

    confidence = "low"
    if span_days >= 7 and drop >= 10 and len(segment) >= 6:
        confidence = "high"
    elif span_days >= 2 and drop >= 5 and len(segment) >= 4:
        confidence = "medium"

    status = immediate_status
    notice = immediate_notice
    if status == "healthy" and days_to_notice <= 2:
        status = "charge_soon"
        notice = f"Plan to charge this terminal within about {max(1, round(days_to_notice))} day."
    elif status == "healthy" and days_to_notice <= 5:
        status = "watch"
        notice = f"Battery is trending toward the charge threshold in about {round(days_to_notice)} days."

    return BatteryHealth(
        status=status,
        current_pct=current_pct,
        current_mv=current_mv,
        observed_at=current.observed_at,
        sample_count=len(readings),
        trend_days=round(span_days, 2),
        drain_pct_per_day=round(drain_per_day, 2),
        estimated_days_remaining=round(days_remaining, 1),
        estimated_empty_at=estimated_empty_at,
        estimated_charge_at=estimated_charge_at,
        confidence=confidence,
        notice=notice,
    )
