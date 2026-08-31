"""Focused contracts for deterministic private Share Availability."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

import backend.routers.calendar_availability as availability_router
import backend.services.google_calendar as google_calendar
from backend.database import get_db
from backend.routers.auth import get_current_user
from backend.schemas.calendar_availability import (
    MAX_AVAILABILITY_ACCOUNTS,
    MAX_AVAILABILITY_SLOTS,
    CalendarAvailabilityCoverage,
    CalendarAvailabilityRequest,
    CalendarAvailabilityResponse,
)
from backend.services.calendar_availability import (
    CalendarAvailabilityInvalidRequest,
    CalendarAvailabilityNotFound,
    _event_range_statement,
    calculate_available_slots,
    coverage_for_account,
    get_calendar_availability,
    resolve_exact_local_datetime,
)
from backend.services.google_scopes import CALENDAR_READONLY_SCOPE


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _payload(**overrides):
    values = {
        "account_ids": [7],
        "start_date": "2026-08-31",
        "end_date": "2026-08-31",
        "timezone": "UTC",
        "duration_minutes": 30,
        "step_minutes": 30,
        "day_start": "09:00",
        "day_end": "12:00",
        "include_weekends": True,
        "minimum_notice_minutes": 0,
    }
    values.update(overrides)
    return values


def _request(**overrides) -> CalendarAvailabilityRequest:
    return CalendarAvailabilityRequest(**_payload(**overrides))


def _account(account_id=7, email="owner@example.test", *, calendar=True):
    scopes = [CALENDAR_READONLY_SCOPE] if calendar else []
    return SimpleNamespace(id=account_id, email=email, scopes=json.dumps(scopes))


def _sync(**overrides):
    values = {
        "last_full_sync": NOW - timedelta(minutes=10),
        "last_incremental_sync": NOW - timedelta(minutes=2),
        "status": "completed",
        "needs_reauth": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _event(**overrides):
    values = {
        "account_id": 7,
        "calendar_id": "primary",
        "status": "confirmed",
        "transparency": None,
        "attendees": None,
        "is_all_day": False,
        "start_time": NOW,
        "end_time": NOW + timedelta(minutes=30),
        "start_date": None,
        "end_date": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Result:
    def __init__(self, *, rows=None, scalars=None):
        self._rows = rows or []
        self._scalars = scalars or []

    def all(self):
        return self._rows

    def scalars(self):
        return _Result(rows=self._scalars)


class _ReadOnlySession:
    """Intentionally exposes no mutation API."""

    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def _app(*, authenticated: bool):
    app = FastAPI()
    app.include_router(availability_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=17)

        app.dependency_overrides[get_current_user] = fake_user
    return app


def test_request_schema_is_strict_bounded_and_frozen():
    request = _request()
    assert set(request.model_dump()) == {
        "account_ids",
        "start_date",
        "end_date",
        "timezone",
        "duration_minutes",
        "step_minutes",
        "day_start",
        "day_end",
        "include_weekends",
        "minimum_notice_minutes",
    }

    invalid_payloads = [
        {"account_ids": []},
        {"account_ids": list(range(1, MAX_AVAILABILITY_ACCOUNTS + 2))},
        {"account_ids": [7, 7]},
        {"account_ids": [True]},
        {"account_ids": [0]},
        {"timezone": "Not/A_Zone"},
        {"duration_minutes": 20},
        {"step_minutes": 5},
        {"day_start": "05:59"},
        {"day_end": "22:01"},
        {"day_start": "10:00", "day_end": "10:00"},
        {"start_date": "2026-09-01", "end_date": "2026-08-31"},
        {"include_weekends": 1},
        {"minimum_notice_minutes": 10081},
        {"unexpected": "field"},
    ]
    for overrides in invalid_payloads:
        with pytest.raises(ValidationError):
            _request(**overrides)


def test_rolling_local_date_horizon_is_exactly_21_days():
    accepted = _request(end_date="2026-09-20")
    assert calculate_available_slots(accepted, [], now=NOW)

    for overrides in (
        {"start_date": "2026-08-30", "end_date": "2026-08-31"},
        {"end_date": "2026-09-21"},
    ):
        with pytest.raises(CalendarAvailabilityInvalidRequest, match="next 21"):
            calculate_available_slots(_request(**overrides), [], now=NOW)


@pytest.mark.parametrize(
    ("account", "sync_status", "state"),
    [
        (_account(calendar=False), _sync(), "calendar_not_enabled"),
        (_account(), _sync(needs_reauth=True), "reauthorization_required"),
        (_account(), None, "sync_incomplete"),
        (_account(), _sync(last_full_sync=None), "sync_incomplete"),
        (_account(), _sync(status="syncing"), "syncing"),
        (_account(), _sync(status="error"), "sync_error"),
        (
            _account(),
            _sync(
                last_full_sync=NOW - timedelta(minutes=31),
                last_incremental_sync=None,
            ),
            "stale",
        ),
        (_account(), _sync(), "ready"),
    ],
)
def test_coverage_states_fail_closed(account, sync_status, state):
    coverage = coverage_for_account(account, sync_status, now=NOW)
    assert coverage.state == state
    assert set(coverage.model_dump()) == {
        "account_id",
        "account_email",
        "state",
        "last_success_at",
    }


@pytest.mark.asyncio
async def test_exact_active_ownership_is_required_before_event_query():
    session = _ReadOnlySession(
        [_Result(rows=[(_account(7), _sync())])]
    )
    with pytest.raises(CalendarAvailabilityNotFound, match="Account not found"):
        await get_calendar_availability(
            session,
            user_id=17,
            request=_request(account_ids=[7, 99]),
            now=NOW,
        )
    assert len(session.statements) == 1
    statement = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "google_accounts.user_id" in sql
    assert "google_accounts.is_active IS true" in sql
    assert "google_accounts.id IN" in sql
    assert 17 in statement.params.values()


@pytest.mark.asyncio
async def test_any_unready_account_suppresses_every_slot_and_event_read():
    session = _ReadOnlySession(
        [_Result(rows=[(_account(7), _sync()), (_account(8), _sync(status="error"))])]
    )
    response = await get_calendar_availability(
        session,
        user_id=17,
        request=_request(account_ids=[7, 8]),
        now=NOW,
    )
    assert response.ready is False
    assert [item.state for item in response.coverage] == ["ready", "sync_error"]
    assert response.slots == []
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_combined_accounts_union_conflicts_and_query_primary_only():
    events = [
        _event(
            account_id=7,
            start_time=datetime(2026, 8, 31, 9, 30, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc),
        ),
        _event(
            account_id=8,
            start_time=datetime(2026, 8, 31, 10, 30, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc),
        ),
    ]
    session = _ReadOnlySession(
        [
            _Result(rows=[(_account(7), _sync()), (_account(8), _sync())]),
            _Result(scalars=events),
            _Result(rows=[(_account(7), _sync()), (_account(8), _sync())]),
        ]
    )
    response = await get_calendar_availability(
        session,
        user_id=17,
        request=_request(account_ids=[7, 8]),
        now=NOW - timedelta(hours=4),
    )
    assert response.ready is True
    assert [slot.start for slot in response.slots] == [
        "2026-08-31T09:00:00+00:00",
        "2026-08-31T10:00:00+00:00",
        "2026-08-31T11:30:00+00:00",
    ]
    event_statement = session.statements[1].compile(dialect=postgresql.dialect())
    assert "calendar_events.calendar_id" in str(event_statement)
    assert "primary" in event_statement.params.values()


@pytest.mark.asyncio
async def test_status_race_after_event_read_fails_closed_with_current_coverage():
    initial_sync = _sync()
    current_sync = _sync(status="syncing")
    session = _ReadOnlySession(
        [
            _Result(rows=[(_account(), initial_sync)]),
            _Result(scalars=[]),
            _Result(rows=[(_account(), current_sync)]),
        ]
    )

    response = await get_calendar_availability(
        session,
        user_id=17,
        request=_request(),
        now=NOW - timedelta(hours=4),
    )

    assert response.ready is False
    assert response.slots == []
    assert [item.state for item in response.coverage] == ["syncing"]
    assert len(session.statements) == 3
    assert session.statements[2].get_execution_options()["populate_existing"] is True


@pytest.mark.asyncio
async def test_completed_version_race_after_event_read_fails_closed():
    initial_sync = _sync()
    current_sync = _sync(last_incremental_sync=NOW - timedelta(minutes=1))
    session = _ReadOnlySession(
        [
            _Result(rows=[(_account(), initial_sync)]),
            _Result(scalars=[]),
            _Result(rows=[(_account(), current_sync)]),
        ]
    )

    response = await get_calendar_availability(
        session,
        user_id=17,
        request=_request(),
        now=NOW - timedelta(hours=4),
    )

    assert response.ready is False
    assert response.slots == []
    assert [item.state for item in response.coverage] == ["ready"]


def test_all_day_blocks_while_cancelled_transparent_and_self_declined_do_not():
    request = _request()
    all_day = _event(
        is_all_day=True,
        start_time=None,
        end_time=None,
        start_date="2026-08-31",
        end_date="2026-09-01",
    )
    assert calculate_available_slots(request, [all_day], now=NOW - timedelta(hours=4)) == []

    nonblocking = [
        _event(
            status="cancelled",
            start_time=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc),
        ),
        _event(
            transparency="transparent",
            start_time=datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 31, 11, 0, tzinfo=timezone.utc),
        ),
        _event(
            attendees=[
                {"self": True, "response_status": "declined"},
                {"self": False, "response_status": "accepted"},
            ],
            start_time=datetime(2026, 8, 31, 11, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        ),
    ]
    assert len(calculate_available_slots(request, nonblocking, now=NOW - timedelta(hours=4))) == 6


@pytest.mark.parametrize("response_status", ["tentative", "needsAction"])
def test_tentative_and_needs_action_events_remain_busy(response_status):
    event = _event(
        attendees=[{"self": True, "response_status": response_status}],
        start_time=datetime(2026, 8, 31, 9, 30, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 31, 10, 30, tzinfo=timezone.utc),
    )
    starts = [
        slot.start
        for slot in calculate_available_slots(
            _request(), [event], now=NOW - timedelta(hours=4)
        )
    ]
    assert "2026-08-31T09:30:00+00:00" not in starts
    assert "2026-08-31T10:00:00+00:00" not in starts


def test_notice_and_weekend_filters_are_applied_in_the_requested_zone():
    notice_request = _request(minimum_notice_minutes=135)
    starts = [
        slot.start
        for slot in calculate_available_slots(
            notice_request, [], now=datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
        )
    ]
    assert starts[0] == "2026-08-31T10:30:00+00:00"

    weekend_request = _request(
        start_date="2026-09-05",
        end_date="2026-09-05",
        include_weekends=False,
    )
    assert calculate_available_slots(weekend_request, [], now=NOW) == []


def test_dst_resolution_skips_gaps_chooses_later_fold_and_emits_offset():
    new_york = ZoneInfo("America/New_York")
    assert resolve_exact_local_datetime(
        date(2026, 3, 8), time(2, 30), new_york
    ) is None
    repeated = resolve_exact_local_datetime(
        date(2026, 11, 1), time(1, 30), new_york
    )
    assert repeated is not None
    assert repeated.fold == 1
    assert repeated.utcoffset() == timedelta(hours=-5)

    request = _request(
        start_date="2026-03-08",
        end_date="2026-03-08",
        timezone="America/New_York",
        day_start="06:00",
        day_end="07:00",
    )
    slots = calculate_available_slots(
        request,
        [],
        now=datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
    )
    assert slots[0].start == "2026-03-08T06:00:00-04:00"


def test_easter_island_fold_never_emits_a_slot_with_wrong_elapsed_duration():
    request = _request(
        start_date="2026-04-04",
        end_date="2026-04-04",
        timezone="Pacific/Easter",
        duration_minutes=60,
        step_minutes=30,
        day_start="20:00",
        day_end="22:00",
    )
    slots = calculate_available_slots(
        request,
        [],
        now=datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert [(slot.start, slot.end) for slot in slots] == [
        ("2026-04-04T21:00:00-06:00", "2026-04-04T22:00:00-06:00")
    ]
    assert all(
        datetime.fromisoformat(slot.end).astimezone(timezone.utc)
        - datetime.fromisoformat(slot.start).astimezone(timezone.utc)
        == timedelta(minutes=request.duration_minutes)
        for slot in slots
    )


def test_slot_output_is_hard_capped():
    request = _request(
        end_date="2026-09-20",
        duration_minutes=15,
        step_minutes=15,
        day_start="06:00",
        day_end="22:00",
    )
    slots = calculate_available_slots(request, [], now=NOW - timedelta(hours=12))
    assert len(slots) == MAX_AVAILABILITY_SLOTS == 256


@pytest.mark.asyncio
async def test_service_is_read_only_and_never_calls_google(monkeypatch):
    async def provider_call_forbidden(*_args, **_kwargs):
        raise AssertionError("provider call attempted")

    monkeypatch.setattr(
        google_calendar.GoogleCalendarService,
        "list_events",
        provider_call_forbidden,
    )
    session = _ReadOnlySession(
        [
            _Result(rows=[(_account(), _sync())]),
            _Result(scalars=[]),
            _Result(rows=[(_account(), _sync())]),
        ]
    )
    response = await get_calendar_availability(
        session,
        user_id=17,
        request=_request(),
        now=NOW - timedelta(hours=4),
    )
    assert response.ready is True
    assert len(session.statements) == 3


@pytest.mark.asyncio
async def test_route_is_post_authenticated_private_no_store_and_frozen(monkeypatch):
    payload = _payload()
    unauthenticated = _app(authenticated=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=unauthenticated), base_url="https://test"
    ) as client:
        unauthorized = await client.post("/api/calendar/availability", json=payload)
    assert unauthorized.status_code == 401
    assert unauthorized.headers["cache-control"] == "private, no-store"

    async def available(*_args, **_kwargs):
        return CalendarAvailabilityResponse(
            ready=True,
            generated_at=NOW,
            timezone="UTC",
            duration_minutes=30,
            coverage=[
                CalendarAvailabilityCoverage(
                    account_id=7,
                    account_email="owner@example.test",
                    state="ready",
                    last_success_at=NOW - timedelta(minutes=2),
                )
            ],
            slots=[],
        )

    monkeypatch.setattr(availability_router, "get_calendar_availability", available)
    authenticated = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated), base_url="https://test"
    ) as client:
        response = await client.post("/api/calendar/availability", json=payload)
        invalid = await client.post(
            "/api/calendar/availability", json={**payload, "account_ids": []}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert set(response.json()) == {
        "ready",
        "generated_at",
        "timezone",
        "duration_minutes",
        "coverage",
        "slots",
    }
    assert set(response.json()["coverage"][0]) == {
        "account_id",
        "account_email",
        "state",
        "last_success_at",
    }
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_route_maps_foreign_missing_or_inactive_to_one_no_store_404(monkeypatch):
    async def missing(*_args, **_kwargs):
        raise CalendarAvailabilityNotFound("Account not found")

    monkeypatch.setattr(availability_router, "get_calendar_availability", missing)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.post("/api/calendar/availability", json=_payload())
    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["detail"] == {
        "code": "account_not_found",
        "message": "Account not found",
    }


def test_event_query_is_local_postgres_read_only_and_primary_calendar_only():
    statement = _event_range_statement(account_ids=[7, 8], request=_request())
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.lstrip().startswith("SELECT")
    assert "calendar_events.account_id IN" in sql
    assert "calendar_events.calendar_id" in sql
    assert "primary" in compiled.params.values()
