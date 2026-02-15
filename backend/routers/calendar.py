from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from backend.database import get_db
from backend.models.user import User
from backend.models.account import GoogleAccount
from backend.models.calendar import CalendarEvent, CalendarSyncStatus
from backend.schemas.calendar import (
    CalendarEventResponse,
    CalendarEventListResponse,
    CalendarSyncStatusResponse,
)
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


async def _get_user_account_ids(db: AsyncSession, user: User) -> list[int]:
    """Get all account IDs belonging to the current user."""
    result = await db.execute(
        select(GoogleAccount.id).where(
            GoogleAccount.user_id == user.id,
            GoogleAccount.is_active == True,
        )
    )
    return [r[0] for r in result.all()]


async def _get_account_email_map(db: AsyncSession, account_ids: list[int]) -> dict[int, str]:
    """Map account IDs to email addresses."""
    result = await db.execute(
        select(GoogleAccount.id, GoogleAccount.email).where(
            GoogleAccount.id.in_(account_ids)
        )
    )
    return {r[0]: r[1] for r in result.all()}


@router.get("/events", response_model=CalendarEventListResponse)
async def list_calendar_events(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    account_id: int = Query(None, description="Filter by account ID"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List calendar events in a date range."""
    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        return CalendarEventListResponse(events=[], total=0)

    if account_id and account_id not in account_ids:
        raise HTTPException(status_code=404, detail="Account not found")

    target_ids = [account_id] if account_id else account_ids

    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Query for timed events in range
    timed_condition = and_(
        CalendarEvent.is_all_day == False,
        CalendarEvent.start_time <= end_dt,
        CalendarEvent.end_time >= start_dt,
    )

    # Query for all-day events in range
    start_str = start
    end_str = end
    allday_condition = and_(
        CalendarEvent.is_all_day == True,
        CalendarEvent.start_date <= end_str,
        CalendarEvent.end_date >= start_str,
    )

    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.account_id.in_(target_ids),
            CalendarEvent.status != "cancelled",
            or_(timed_condition, allday_condition),
        )
        .order_by(
            CalendarEvent.is_all_day.desc(),
            CalendarEvent.start_time.asc().nullslast(),
            CalendarEvent.start_date.asc().nullslast(),
        )
    )
    events = result.scalars().all()

    email_map = await _get_account_email_map(db, target_ids)

    event_responses = []
    for e in events:
        resp = CalendarEventResponse.model_validate(e)
        resp.account_email = email_map.get(e.account_id)
        event_responses.append(resp)

    return CalendarEventListResponse(events=event_responses, total=len(event_responses))


@router.get("/events/{event_id}", response_model=CalendarEventResponse)
async def get_calendar_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single calendar event by ID."""
    account_ids = await _get_user_account_ids(db, user)

    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.account_id.in_(account_ids),
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    email_map = await _get_account_email_map(db, account_ids)
    resp = CalendarEventResponse.model_validate(event)
    resp.account_email = email_map.get(event.account_id)
    return resp


@router.post("/sync")
async def trigger_calendar_sync(
    account_id: int = Query(None, description="Sync specific account"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Trigger calendar sync for all accounts or a specific one."""
    from backend.workers.tasks import parse_redis_url
    from arq import create_pool
    from backend.config import get_settings

    settings = get_settings()
    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        raise HTTPException(status_code=404, detail="No accounts found")

    if account_id:
        if account_id not in account_ids:
            raise HTTPException(status_code=404, detail="Account not found")
        target_ids = [account_id]
    else:
        target_ids = account_ids

    redis = await create_pool(parse_redis_url(settings.redis_url))
    try:
        for aid in target_ids:
            await redis.enqueue_job("sync_calendar_incremental", aid)
    finally:
        await redis.close()

    return {"message": f"Calendar sync triggered for {len(target_ids)} account(s)"}


@router.get("/sync-status", response_model=list[CalendarSyncStatusResponse])
async def get_calendar_sync_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get calendar sync status for all accounts."""
    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        return []

    result = await db.execute(
        select(CalendarSyncStatus).where(
            CalendarSyncStatus.account_id.in_(account_ids)
        )
    )
    statuses = result.scalars().all()
    email_map = await _get_account_email_map(db, account_ids)

    responses = []
    for s in statuses:
        resp = CalendarSyncStatusResponse.model_validate(s)
        resp.account_email = email_map.get(s.account_id)
        responses.append(resp)
    return responses


@router.get("/upcoming", response_model=CalendarEventListResponse)
async def get_upcoming_events(
    days: int = Query(7, description="Number of days to look ahead"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get upcoming events for AI context."""
    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        return CalendarEventListResponse(events=[], total=0)

    now = datetime.now(timezone.utc)
    end_dt = now + timedelta(days=days)
    today_str = now.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    timed_condition = and_(
        CalendarEvent.is_all_day == False,
        CalendarEvent.start_time >= now,
        CalendarEvent.start_time <= end_dt,
    )

    allday_condition = and_(
        CalendarEvent.is_all_day == True,
        CalendarEvent.start_date >= today_str,
        CalendarEvent.start_date <= end_str,
    )

    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.account_id.in_(account_ids),
            CalendarEvent.status != "cancelled",
            or_(timed_condition, allday_condition),
        )
        .order_by(
            CalendarEvent.start_time.asc().nullslast(),
            CalendarEvent.start_date.asc().nullslast(),
        )
        .limit(100)
    )
    events = result.scalars().all()
    email_map = await _get_account_email_map(db, account_ids)

    event_responses = []
    for e in events:
        resp = CalendarEventResponse.model_validate(e)
        resp.account_email = email_map.get(e.account_id)
        event_responses.append(resp)

    return CalendarEventListResponse(events=event_responses, total=len(event_responses))
