"""Battery telemetry sampling and conservative runtime prediction."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional, Protocol

CHARGE_NOTICE_PCT = 20
CHARGE_NOW_PCT = 10
MIN_SAMPLE_INTERVAL = timedelta(minutes=5)
SAMPLE_HEARTBEAT = timedelta(hours=6)
MIN_TREND_SPAN = timedelta(hours=12)
SIGNIFICANT_CHARGE_RISE_PCT = 5
CHARGE_CONFIRMATION_MARGIN_PCT = 3
STALE_AFTER = timedelta(hours=48)
BATTERY_RETENTION = timedelta(days=90)
TREND_BUCKET = timedelta(hours=6)
MAX_TREND_POINTS = 96
MAX_FORECAST_HORIZON_DAYS = 365


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


@dataclass(frozen=True)
class _TrendPoint:
    observed_at: datetime
    battery_pct: float


@dataclass(frozen=True)
class _DischargeTrend:
    span_days: float
    drain_pct_per_day: float
    robust_drop_pct: float
    modeled_current_pct: float
    median_error_pct: float
    direction_agreement: float
    point_count: int


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


def normalize_battery_telemetry(
    *,
    battery_mv: Optional[int],
    battery_pct: Optional[int],
    measurement_valid: Optional[int],
) -> tuple[Optional[int], Optional[int]]:
    """Normalize one firmware reading and honor its explicit quality result.

    Older firmware has no quality header and retains the established bounded
    behavior. Candidate.5 sends 0 only when its seven-sample ADC burst is too
    sparse, implausible, or noisy; that reading must not enter the predictor.
    """
    if measurement_valid == 0:
        return None, None
    return normalize_battery_mv(battery_mv), normalize_battery_pct(battery_pct)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bounded_trend_points(readings: list[BatteryReading]) -> list[_TrendPoint]:
    """Collapse noisy request-time readings into bounded six-hour medians."""
    bucket_seconds = int(TREND_BUCKET.total_seconds())
    buckets: dict[int, list[BatteryReading]] = {}
    for reading in readings:
        key = int(reading.observed_at.timestamp()) // bucket_seconds
        buckets.setdefault(key, []).append(reading)

    points = [
        _TrendPoint(
            observed_at=datetime.fromtimestamp(
                median(item.observed_at.timestamp() for item in bucket),
                tz=timezone.utc,
            ),
            battery_pct=float(median(int(item.battery_pct or 0) for item in bucket)),
        )
        for _, bucket in sorted(buckets.items())
    ]
    if len(points) <= MAX_TREND_POINTS:
        return points

    # Retain the whole observation span without allowing an unusually chatty
    # device to turn the robust pairwise estimator into unbounded work.
    indexes = {
        round(index * (len(points) - 1) / (MAX_TREND_POINTS - 1))
        for index in range(MAX_TREND_POINTS)
    }
    return [points[index] for index in sorted(indexes)]


def _estimate_discharge_trend(
    readings: list[BatteryReading],
) -> Optional[_DischargeTrend]:
    """Return a bounded Theil-Sen-style trend, or None for unsettled data."""
    points = _bounded_trend_points(readings)
    if len(points) < 3:
        return None

    span = points[-1].observed_at - points[0].observed_at
    if span < MIN_TREND_SPAN:
        return None
    span_days = span.total_seconds() / 86400

    slopes: list[float] = []
    for left_index, left in enumerate(points[:-1]):
        for right in points[left_index + 1 :]:
            elapsed_days = (right.observed_at - left.observed_at).total_seconds() / 86400
            if elapsed_days < MIN_TREND_SPAN.total_seconds() / 86400:
                continue
            # Positive means discharge; negative means the observed level rose.
            slopes.append((left.battery_pct - right.battery_pct) / elapsed_days)
    if not slopes:
        return None

    drain_per_day = float(median(slopes))
    window_size = max(1, min(4, len(points) // 3))
    early_level = float(median(point.battery_pct for point in points[:window_size]))
    late_level = float(median(point.battery_pct for point in points[-window_size:]))
    robust_drop = early_level - late_level
    if robust_drop < 2 or drain_per_day < 0.05 or drain_per_day > 100:
        return None

    origin = points[0].observed_at
    intercept = float(
        median(
            point.battery_pct
            + drain_per_day
            * ((point.observed_at - origin).total_seconds() / 86400)
            for point in points
        )
    )
    errors = [
        abs(
            point.battery_pct
            - (
                intercept
                - drain_per_day
                * ((point.observed_at - origin).total_seconds() / 86400)
            )
        )
        for point in points
    ]
    median_error = float(median(errors))
    direction_agreement = sum(slope >= 0 for slope in slopes) / len(slopes)
    # A trend with frequent rises or large residuals is not safe to extrapolate.
    if direction_agreement < 0.7 or median_error > max(2.5, robust_drop * 0.35):
        return None

    modeled_current = intercept - drain_per_day * span_days
    return _DischargeTrend(
        span_days=span_days,
        drain_pct_per_day=drain_per_day,
        robust_drop_pct=robust_drop,
        modeled_current_pct=modeled_current,
        median_error_pct=median_error,
        direction_agreement=direction_agreement,
        point_count=len(points),
    )


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

    pct_readings = [r for r in readings if r.battery_pct is not None]
    mv_readings = [r for r in readings if r.battery_mv is not None]
    current_pct = pct_readings[-1].battery_pct if pct_readings else None
    current_mv = mv_readings[-1].battery_mv if mv_readings else None
    # A newer voltage-only row must not make an older percentage look fresh.
    observed_at = (
        pct_readings[-1].observed_at if pct_readings else readings[-1].observed_at
    )

    base = BatteryHealth(
        status="unknown",
        current_pct=current_pct,
        current_mv=current_mv,
        observed_at=observed_at,
        sample_count=len(pct_readings) if pct_readings else len(readings),
    )
    if current_pct is None:
        return base

    if now is not None:
        age = _utc(now) - observed_at
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

    # A corroborated rise starts a fresh discharge segment. A rise in the most
    # recent sample is surfaced as uncertain, because the current protocol has
    # no external-power signal and boot_count increments on every normal wake.
    # Never claim active charging from voltage-derived percentages alone.
    segment_start = 0
    latest_significant_rise = False
    for idx in range(1, len(pct_readings)):
        previous = pct_readings[idx - 1]
        reading = pct_readings[idx]
        rise = int(reading.battery_pct or 0) - int(previous.battery_pct or 0)
        if rise >= SIGNIFICANT_CHARGE_RISE_PCT:
            is_latest = idx == len(pct_readings) - 1
            stays_elevated = (
                not is_latest
                and int(pct_readings[idx + 1].battery_pct or 0)
                >= int(previous.battery_pct or 0) + CHARGE_CONFIRMATION_MARGIN_PCT
            )
            if is_latest or stays_elevated:
                segment_start = idx
                latest_significant_rise = is_latest
    segment = pct_readings[segment_start:]

    if immediate_status != "healthy":
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": immediate_status,
                "notice": immediate_notice,
            }
        )

    if latest_significant_rise:
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": "possible_charging",
                "notice": (
                    "Battery level rose; charging is possible, but external power "
                    "is not reported."
                ),
            }
        )

    trend = _estimate_discharge_trend(segment)
    if trend is None:
        return BatteryHealth(
            **{
                **base.__dict__,
                "status": immediate_status,
                "notice": immediate_notice,
            }
        )

    # Anchor the forecast to the lower of the latest raw reading and the robust
    # fitted level. This avoids extending runtime because of a transient rise.
    forecast_pct = max(0.0, min(float(current_pct), trend.modeled_current_pct))
    days_remaining = forecast_pct / trend.drain_pct_per_day
    days_to_notice = max(
        0.0,
        (forecast_pct - CHARGE_NOTICE_PCT) / trend.drain_pct_per_day,
    )
    estimated_empty_at = (
        observed_at + timedelta(days=days_remaining)
        if days_remaining <= MAX_FORECAST_HORIZON_DAYS
        else None
    )
    estimated_charge_at = (
        observed_at + timedelta(days=days_to_notice)
        if days_to_notice <= MAX_FORECAST_HORIZON_DAYS
        else None
    )

    confidence = "low"
    if (
        trend.span_days >= 14
        and trend.robust_drop_pct >= 15
        and trend.point_count >= 12
        and trend.median_error_pct <= 1
        and trend.direction_agreement >= 0.9
    ):
        confidence = "high"
    elif (
        trend.span_days >= 2
        and trend.robust_drop_pct >= 5
        and trend.point_count >= 4
        and trend.median_error_pct <= 2
        and trend.direction_agreement >= 0.8
    ):
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
        observed_at=observed_at,
        sample_count=len(pct_readings),
        trend_days=round(trend.span_days, 2),
        drain_pct_per_day=round(trend.drain_pct_per_day, 2),
        estimated_days_remaining=(
            round(days_remaining, 1)
            if days_remaining <= MAX_FORECAST_HORIZON_DAYS
            else None
        ),
        estimated_empty_at=estimated_empty_at,
        estimated_charge_at=estimated_charge_at,
        confidence=confidence,
        notice=notice,
    )
