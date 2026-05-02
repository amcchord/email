"""Public read-only JSON API at /api/v1/...

Authenticated by per-user shared-secret API tokens (see backend.utils.api_auth).
Designed to be small, stable, and curl-friendly so external tools (e.g. an
e-ink "day ahead" display) can build on top.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, desc, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter

from backend.database import get_db
from backend.models.account import GoogleAccount
from backend.models.calendar import CalendarEvent
from backend.models.email import Email
from backend.models.user import User
from backend.routers.emails import MAILBOX_LABEL_MAP, jsonb_contains
from backend.schemas.public_api import (
    PublicAccount,
    PublicCalendarEvent,
    PublicCalendarListResponse,
    PublicEmail,
    PublicEmailListResponse,
    PublicMeResponse,
    PublicUnreadByAccount,
    PublicUnreadCountResponse,
)
from backend.utils.api_auth import api_token_rate_limit_key, get_api_user

router = APIRouter(prefix="/api/v1", tags=["public"])

limiter = Limiter(key_func=api_token_rate_limit_key)


async def _get_account_map(db: AsyncSession, user: User) -> dict[int, str]:
    """Return {account_id: email} for the current user's active accounts."""
    result = await db.execute(
        select(GoogleAccount.id, GoogleAccount.email).where(
            GoogleAccount.user_id == user.id,
            GoogleAccount.is_active == True,
        )
    )
    return {row[0]: row[1] for row in result.all()}


def _resolve_tz(tz_name: Optional[str]) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz_name}")


# ── Identity ────────────────────────────────────────────────────────

@router.get("/me", response_model=PublicMeResponse)
@limiter.limit("60/minute")
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    accounts = await _get_account_map(db, user)
    return PublicMeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        accounts=[
            PublicAccount(id=aid, email=email) for aid, email in accounts.items()
        ],
    )


# ── Calendar ────────────────────────────────────────────────────────

def _serialize_event(e: CalendarEvent, account_email: Optional[str]) -> PublicCalendarEvent:
    return PublicCalendarEvent(
        id=e.id,
        account_email=account_email,
        google_event_id=e.google_event_id,
        calendar_id=e.calendar_id or "primary",
        summary=e.summary,
        description=e.description,
        location=e.location,
        start_time=e.start_time,
        end_time=e.end_time,
        start_date=e.start_date,
        end_date=e.end_date,
        timezone=e.timezone,
        is_all_day=e.is_all_day,
        status=e.status or "confirmed",
        html_link=e.html_link,
        hangout_link=e.hangout_link,
        organizer_email=e.organizer_email,
        organizer_name=e.organizer_name,
        attendees=e.attendees,
    )


@router.get("/calendar/today", response_model=PublicCalendarListResponse)
@limiter.limit("60/minute")
async def calendar_today(
    request: Request,
    tz: Optional[str] = Query(None, description="IANA timezone, e.g. America/New_York. Defaults to UTC."),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Events that overlap 'today' in the requested timezone."""
    accounts = await _get_account_map(db, user)
    if not accounts:
        return PublicCalendarListResponse(events=[], total=0)

    zone = _resolve_tz(tz)
    now_local = datetime.now(zone)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    today_str = start_local.strftime("%Y-%m-%d")

    timed_condition = and_(
        CalendarEvent.is_all_day == False,
        CalendarEvent.start_time <= end_utc,
        CalendarEvent.end_time >= start_utc,
    )
    allday_condition = and_(
        CalendarEvent.is_all_day == True,
        CalendarEvent.start_date <= today_str,
        CalendarEvent.end_date >= today_str,
    )

    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.account_id.in_(accounts.keys()),
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
    serialized = [_serialize_event(e, accounts.get(e.account_id)) for e in events]
    return PublicCalendarListResponse(events=serialized, total=len(serialized))


@router.get("/calendar/upcoming", response_model=PublicCalendarListResponse)
@limiter.limit("60/minute")
async def calendar_upcoming(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Upcoming events for the next `days` days, ordered by start."""
    accounts = await _get_account_map(db, user)
    if not accounts:
        return PublicCalendarListResponse(events=[], total=0)

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
            CalendarEvent.account_id.in_(accounts.keys()),
            CalendarEvent.status != "cancelled",
            or_(timed_condition, allday_condition),
        )
        .order_by(
            CalendarEvent.start_time.asc().nullslast(),
            CalendarEvent.start_date.asc().nullslast(),
        )
        .limit(limit)
    )
    events = result.scalars().all()
    serialized = [_serialize_event(e, accounts.get(e.account_id)) for e in events]
    return PublicCalendarListResponse(events=serialized, total=len(serialized))


# ── Emails ──────────────────────────────────────────────────────────

@router.get("/emails/recent", response_model=PublicEmailListResponse)
@limiter.limit("60/minute")
async def emails_recent(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    unread_only: bool = Query(False),
    mailbox: str = Query("INBOX"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Most recent emails (snippet only — no full bodies)."""
    accounts = await _get_account_map(db, user)
    if not accounts:
        return PublicEmailListResponse(emails=[], total=0)

    query = select(Email).where(Email.account_id.in_(accounts.keys()))

    if mailbox == "STARRED":
        query = query.where(Email.is_starred == True)
    elif mailbox == "TRASH":
        query = query.where(Email.is_trash == True)
    elif mailbox == "SPAM":
        query = query.where(Email.is_spam == True)
    elif mailbox == "DRAFTS":
        query = query.where(Email.is_draft == True)
    elif mailbox == "SENT":
        query = query.where(Email.is_sent == True, Email.is_trash == False)
    elif mailbox == "ALL":
        query = query.where(Email.is_trash == False, Email.is_spam == False)
    else:
        gmail_label = MAILBOX_LABEL_MAP.get(mailbox, mailbox)
        if gmail_label:
            query = query.where(jsonb_contains(Email.labels, f'["{gmail_label}"]'))
        query = query.where(Email.is_trash == False, Email.is_spam == False)

    if unread_only:
        query = query.where(Email.is_read == False)

    query = query.order_by(desc(Email.date)).limit(limit)
    result = await db.execute(query)
    emails = result.scalars().all()

    serialized = [
        PublicEmail(
            id=e.id,
            gmail_message_id=e.gmail_message_id,
            gmail_thread_id=e.gmail_thread_id,
            account_email=accounts.get(e.account_id),
            subject=e.subject,
            from_name=e.from_name,
            from_address=e.from_address,
            date=e.date,
            snippet=e.snippet,
            is_read=e.is_read,
            is_starred=e.is_starred,
            has_attachments=e.has_attachments,
            labels=e.labels or [],
        )
        for e in emails
    ]
    return PublicEmailListResponse(emails=serialized, total=len(serialized))


@router.get("/emails/unread-count", response_model=PublicUnreadCountResponse)
@limiter.limit("120/minute")
async def emails_unread_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Total unread (INBOX, not trash/spam) and a per-account breakdown."""
    accounts = await _get_account_map(db, user)
    if not accounts:
        return PublicUnreadCountResponse(unread=0, by_account=[])

    base_filter = [
        Email.account_id.in_(accounts.keys()),
        Email.is_read == False,
        Email.is_trash == False,
        Email.is_spam == False,
        jsonb_contains(Email.labels, '["INBOX"]'),
    ]

    total = await db.scalar(
        select(func.count(Email.id)).where(*base_filter)
    ) or 0

    per_account_result = await db.execute(
        select(Email.account_id, func.count(Email.id))
        .where(*base_filter)
        .group_by(Email.account_id)
    )
    counts = {row[0]: row[1] for row in per_account_result.all()}

    by_account = [
        PublicUnreadByAccount(
            account_id=aid,
            account_email=email,
            unread=counts.get(aid, 0),
        )
        for aid, email in accounts.items()
    ]

    return PublicUnreadCountResponse(unread=total, by_account=by_account)
