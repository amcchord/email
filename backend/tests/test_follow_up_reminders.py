from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.schemas.email import ComposeRequest
from backend.services.follow_up_reminders import calculate_follow_up_wake_at


def test_follow_up_request_defaults_and_validates_timezone():
    request = ComposeRequest(
        account_id=1,
        to=["recipient@example.test"],
        body_text="Generated",
        idempotency_key="a03a5af9-0182-4ff5-acb5-1cbd30dde126",
    )
    assert request.follow_up_reminder == "default"
    assert request.follow_up_time_zone is None

    explicit = request.model_copy(
        update={
            "follow_up_reminder": "enabled",
            "follow_up_time_zone": "America/New_York",
        }
    )
    assert explicit.follow_up_time_zone == "America/New_York"

    with pytest.raises(ValidationError, match="Follow-up timezone"):
        ComposeRequest(
            account_id=1,
            to=["recipient@example.test"],
            body_text="Generated",
            follow_up_reminder="enabled",
            follow_up_time_zone="Not/A_Zone",
            idempotency_key="a03a5af9-0182-4ff5-acb5-1cbd30dde126",
        )


def test_weekday_reminder_anchors_to_actual_delivery():
    # Friday evening plus three weekdays returns Wednesday morning, not a
    # duration from send admission or the scheduled-send time.
    delivered = datetime(2026, 8, 28, 22, 30, tzinfo=timezone.utc)
    wake = calculate_follow_up_wake_at(
        delivered,
        delay_days=3,
        wake_local_time="09:00",
        time_zone="America/New_York",
        weekdays_only=True,
    )
    assert wake == datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)


def test_calendar_day_reminder_includes_weekends():
    delivered = datetime(2026, 8, 28, 16, 0, tzinfo=timezone.utc)
    wake = calculate_follow_up_wake_at(
        delivered,
        delay_days=2,
        wake_local_time="10:15",
        time_zone="America/New_York",
        weekdays_only=False,
    )
    assert wake == datetime(2026, 8, 30, 14, 15, tzinfo=timezone.utc)


def test_dst_gap_defers_to_first_real_minute():
    delivered = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    wake = calculate_follow_up_wake_at(
        delivered,
        delay_days=1,
        wake_local_time="02:30",
        time_zone="America/New_York",
        weekdays_only=False,
    )
    assert wake == datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)


def test_dst_repeat_uses_later_occurrence():
    delivered = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    wake = calculate_follow_up_wake_at(
        delivered,
        delay_days=1,
        wake_local_time="01:30",
        time_zone="America/New_York",
        weekdays_only=False,
    )
    assert wake == datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
