"""Read-only availability calculation over synchronized primary calendars."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.calendar import CalendarEvent, CalendarSyncStatus
from backend.schemas.calendar_availability import (
    MAX_AVAILABILITY_SLOTS,
    CalendarAvailabilityCoverage,
    CalendarAvailabilityRequest,
    CalendarAvailabilityResponse,
    CalendarAvailabilitySlot,
)
from backend.services.calendar_sync import RECENT_SUCCESS_WINDOW
from backend.services.google_scopes import (
    CALENDAR_READONLY_SCOPE,
    runtime_scopes_for_account,
)


MAX_AVAILABILITY_DAYS = 21
OK_SYNC_STATUS = "completed"


class CalendarAvailabilityNotFound(Exception):
    """At least one requested account is not an active account owned by the user."""


class CalendarAvailabilityInvalidRequest(Exception):
    """The otherwise well-formed request falls outside the rolling date horizon."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _last_success(sync_status: CalendarSyncStatus | None) -> datetime | None:
    if sync_status is None:
        return None
    candidates = [
        value
        for value in (
            sync_status.last_full_sync,
            sync_status.last_incremental_sync,
        )
        if value is not None
    ]
    return max((_utc(value) for value in candidates), default=None)


def _coverage_version(
    account: GoogleAccount,
    sync_status: CalendarSyncStatus | None,
) -> tuple:
    """Capture every local field that can change availability readiness."""
    if sync_status is None:
        sync_version = None
    else:
        sync_version = (
            str(sync_status.status or "").casefold(),
            bool(sync_status.needs_reauth),
            _utc(sync_status.last_full_sync) if sync_status.last_full_sync else None,
            _utc(sync_status.last_incremental_sync)
            if sync_status.last_incremental_sync
            else None,
            _utc(sync_status.started_at)
            if getattr(sync_status, "started_at", None)
            else None,
            getattr(sync_status, "sync_token", None),
        )
    return (account.id, account.email, account.scopes, sync_version)


def coverage_for_account(
    account: GoogleAccount,
    sync_status: CalendarSyncStatus | None,
    *,
    now: datetime,
) -> CalendarAvailabilityCoverage:
    """Return one non-secret, deterministic coverage verdict."""
    last_success_at = _last_success(sync_status)
    granted_scopes = runtime_scopes_for_account(account.scopes)

    if CALENDAR_READONLY_SCOPE not in granted_scopes:
        state = "calendar_not_enabled"
    elif sync_status is not None and sync_status.needs_reauth:
        state = "reauthorization_required"
    elif sync_status is None or sync_status.last_full_sync is None:
        state = "sync_incomplete"
    elif str(sync_status.status or "").casefold() == "syncing":
        state = "syncing"
    elif str(sync_status.status or "").casefold() != OK_SYNC_STATUS:
        state = "sync_error"
    elif last_success_at is None or _utc(now) - last_success_at > RECENT_SUCCESS_WINDOW:
        state = "stale"
    else:
        state = "ready"

    return CalendarAvailabilityCoverage(
        account_id=account.id,
        account_email=account.email,
        state=state,
        last_success_at=last_success_at,
    )


def _valid_local_candidate(candidate: datetime, zone: ZoneInfo) -> bool:
    round_trip = candidate.astimezone(timezone.utc).astimezone(zone)
    return round_trip.replace(tzinfo=None) == candidate.replace(tzinfo=None)


def resolve_exact_local_datetime(
    local_date: date,
    local_time: time,
    zone: ZoneInfo,
) -> datetime | None:
    """Resolve a real wall time, choosing the later occurrence on a DST fold."""
    naive = datetime.combine(local_date, local_time)
    candidates = [naive.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [candidate for candidate in candidates if _valid_local_candidate(candidate, zone)]
    if not valid:
        return None
    return max(valid, key=lambda candidate: candidate.astimezone(timezone.utc))


def _resolve_local_boundary(
    local_date: date,
    local_time: time,
    zone: ZoneInfo,
) -> datetime:
    """Resolve a range boundary forward if the named local minute does not exist."""
    exact = resolve_exact_local_datetime(local_date, local_time, zone)
    if exact is not None:
        return exact
    naive = datetime.combine(local_date, local_time)
    for minute_offset in range(1, 24 * 60 + 1):
        shifted = naive + timedelta(minutes=minute_offset)
        resolved = resolve_exact_local_datetime(shifted.date(), shifted.time(), zone)
        if resolved is not None:
            return resolved
    raise CalendarAvailabilityInvalidRequest("Could not resolve local date boundary")


def _request_zone_and_now(
    request: CalendarAvailabilityRequest,
    now: datetime,
) -> tuple[ZoneInfo, datetime]:
    zone = ZoneInfo(request.timezone)
    now_utc = _utc(now)
    local_today = now_utc.astimezone(zone).date()
    last_allowed_day = local_today + timedelta(days=MAX_AVAILABILITY_DAYS - 1)
    if request.start_date < local_today or request.end_date > last_allowed_day:
        raise CalendarAvailabilityInvalidRequest(
            "start_date and end_date must be within the next 21 local calendar days"
        )
    return zone, now_utc


def _event_is_nonblocking(event: CalendarEvent) -> bool:
    if str(event.status or "").casefold() == "cancelled":
        return True
    if str(event.transparency or "").casefold() == "transparent":
        return True
    attendees = event.attendees if isinstance(event.attendees, list) else []
    return any(
        isinstance(attendee, dict)
        and attendee.get("self") is True
        and str(attendee.get("response_status") or "").casefold() == "declined"
        for attendee in attendees
    )


def _event_interval(
    event: CalendarEvent,
    zone: ZoneInfo,
) -> tuple[datetime, datetime] | None:
    if _event_is_nonblocking(event):
        return None
    if event.is_all_day:
        try:
            start_day = date.fromisoformat(event.start_date)
            end_day = date.fromisoformat(event.end_date)
        except (TypeError, ValueError):
            return None
        start = _resolve_local_boundary(start_day, time.min, zone)
        end = _resolve_local_boundary(end_day, time.min, zone)
    else:
        if event.start_time is None or event.end_time is None:
            return None
        start = _utc(event.start_time)
        end = _utc(event.end_time)
    start_utc, end_utc = _utc(start), _utc(end)
    if end_utc <= start_utc:
        return None
    return start_utc, end_utc


def _busy_union(
    events: Iterable[CalendarEvent],
    zone: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    intervals = sorted(
        (interval for event in events if (interval := _event_interval(event, zone))),
        key=lambda interval: (interval[0], interval[1]),
    )
    merged: list[list[datetime]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [(start, end) for start, end in merged]


def _parse_local_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def calculate_available_slots(
    request: CalendarAvailabilityRequest,
    events: Iterable[CalendarEvent],
    *,
    now: datetime,
) -> list[CalendarAvailabilitySlot]:
    """Calculate the bounded chronological complement of the busy union."""
    zone, now_utc = _request_zone_and_now(request, now)
    busy = _busy_union(events, zone)
    notice_cutoff = now_utc + timedelta(minutes=request.minimum_notice_minutes)
    day_start = _parse_local_time(request.day_start)
    day_end = _parse_local_time(request.day_end)
    first_minute = day_start.hour * 60 + day_start.minute
    final_minute = day_end.hour * 60 + day_end.minute
    slots: list[CalendarAvailabilitySlot] = []

    day = request.start_date
    while day <= request.end_date and len(slots) < MAX_AVAILABILITY_SLOTS:
        if request.include_weekends or day.weekday() < 5:
            minute = first_minute
            while (
                minute + request.duration_minutes <= final_minute
                and len(slots) < MAX_AVAILABILITY_SLOTS
            ):
                start_wall = time(hour=minute // 60, minute=minute % 60)
                end_minute = minute + request.duration_minutes
                end_wall = time(hour=end_minute // 60, minute=end_minute % 60)
                start = resolve_exact_local_datetime(day, start_wall, zone)
                end = resolve_exact_local_datetime(day, end_wall, zone)
                if start is not None and end is not None:
                    start_utc, end_utc = _utc(start), _utc(end)
                    exact_duration = end_utc - start_utc == timedelta(
                        minutes=request.duration_minutes
                    )
                    overlaps = any(
                        start_utc < busy_end and end_utc > busy_start
                        for busy_start, busy_end in busy
                    )
                    if (
                        start_utc >= notice_cutoff
                        and exact_duration
                        and not overlaps
                    ):
                        slots.append(
                            CalendarAvailabilitySlot(
                                start=start.isoformat(),
                                end=end.isoformat(),
                            )
                        )
                minute += request.step_minutes
        day += timedelta(days=1)
    return slots


def _event_range_statement(
    *,
    account_ids: list[int],
    request: CalendarAvailabilityRequest,
) -> object:
    zone = ZoneInfo(request.timezone)
    start_utc = _resolve_local_boundary(request.start_date, time.min, zone).astimezone(
        timezone.utc
    )
    end_exclusive_utc = _resolve_local_boundary(
        request.end_date + timedelta(days=1), time.min, zone
    ).astimezone(timezone.utc)
    return select(CalendarEvent).where(
        CalendarEvent.account_id.in_(account_ids),
        CalendarEvent.calendar_id == "primary",
        or_(
            and_(
                CalendarEvent.is_all_day.is_(False),
                CalendarEvent.start_time < end_exclusive_utc,
                CalendarEvent.end_time > start_utc,
            ),
            and_(
                CalendarEvent.is_all_day.is_(True),
                CalendarEvent.start_date <= request.end_date.isoformat(),
                CalendarEvent.end_date > request.start_date.isoformat(),
            ),
        ),
    )


def _owned_account_status_statement(
    *,
    user_id: int,
    account_ids: list[int],
    refresh: bool = False,
):
    statement = (
        select(GoogleAccount, CalendarSyncStatus)
        .outerjoin(
            CalendarSyncStatus,
            CalendarSyncStatus.account_id == GoogleAccount.id,
        )
        .where(
            GoogleAccount.user_id == user_id,
            GoogleAccount.is_active.is_(True),
            GoogleAccount.id.in_(account_ids),
        )
    )
    if refresh:
        statement = statement.execution_options(populate_existing=True)
    return statement


async def _load_owned_account_statuses(
    db: AsyncSession,
    *,
    user_id: int,
    account_ids: list[int],
    refresh: bool = False,
) -> dict[int, tuple[GoogleAccount, CalendarSyncStatus | None]]:
    result = await db.execute(
        _owned_account_status_statement(
            user_id=user_id,
            account_ids=account_ids,
            refresh=refresh,
        )
    )
    by_id = {
        account.id: (account, sync_status)
        for account, sync_status in result.all()
    }
    if set(by_id) != set(account_ids):
        raise CalendarAvailabilityNotFound("Account not found")
    return by_id


async def get_calendar_availability(
    db: AsyncSession,
    *,
    user_id: int,
    request: CalendarAvailabilityRequest,
    now: datetime | None = None,
) -> CalendarAvailabilityResponse:
    """Read synchronized rows and fail closed unless every account is fresh."""
    generated_at = _utc(now or datetime.now(timezone.utc))
    _request_zone_and_now(request, generated_at)

    by_id = await _load_owned_account_statuses(
        db,
        user_id=user_id,
        account_ids=request.account_ids,
    )
    coverage = [
        coverage_for_account(*by_id[account_id], now=generated_at)
        for account_id in request.account_ids
    ]
    coverage_versions = {
        account_id: _coverage_version(*by_id[account_id])
        for account_id in request.account_ids
    }
    ready = all(item.state == "ready" for item in coverage)
    if not ready:
        return CalendarAvailabilityResponse(
            ready=False,
            generated_at=generated_at,
            timezone=request.timezone,
            duration_minutes=request.duration_minutes,
            coverage=coverage,
            slots=[],
        )

    event_result = await db.execute(
        _event_range_statement(account_ids=request.account_ids, request=request)
    )
    events = event_result.scalars().all()
    current_by_id = await _load_owned_account_statuses(
        db,
        user_id=user_id,
        account_ids=request.account_ids,
        refresh=True,
    )
    current_coverage = [
        coverage_for_account(*current_by_id[account_id], now=generated_at)
        for account_id in request.account_ids
    ]
    coverage_changed = any(
        _coverage_version(*current_by_id[account_id])
        != coverage_versions[account_id]
        for account_id in request.account_ids
    )
    if coverage_changed or any(item.state != "ready" for item in current_coverage):
        return CalendarAvailabilityResponse(
            ready=False,
            generated_at=generated_at,
            timezone=request.timezone,
            duration_minutes=request.duration_minutes,
            coverage=current_coverage,
            slots=[],
        )
    return CalendarAvailabilityResponse(
        ready=True,
        generated_at=generated_at,
        timezone=request.timezone,
        duration_minutes=request.duration_minutes,
        coverage=current_coverage,
        slots=calculate_available_slots(request, events, now=generated_at),
    )
