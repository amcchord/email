"""Public read-only JSON API at /api/v1/...

Authenticated by per-user shared-secret API tokens (see backend.utils.api_auth).
Designed to be small, stable, and curl-friendly so external tools (e.g. an
e-ink "day ahead" display) can build on top.
"""
import asyncio
import json
import logging
import time
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter

from backend.database import get_db
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis, ThreadDigest
from backend.models.calendar import CalendarEvent
from backend.models.email import Email
from backend.models.user import User
from backend.routers.emails import MAILBOX_LABEL_MAP, jsonb_contains
from backend.schemas.public_api import (
    PublicAccount,
    PublicAskRequest,
    PublicAskResponse,
    PublicAskTask,
    PublicBriefing,
    PublicBriefingMeta,
    PublicBriefingSummaryResponse,
    PublicCalendarEvent,
    PublicCalendarListResponse,
    PublicEmail,
    PublicEmailListResponse,
    PublicImportantEmail,
    PublicImportantEmailListResponse,
    PublicMeResponse,
    PublicThreadDigest,
    PublicThreadDigestListResponse,
    PublicUnreadByAccount,
    PublicUnreadCountResponse,
    PublicVolumeAccountRollup,
    PublicVolumeDay,
    PublicVolumeResponse,
    PublicWeekDay,
    PublicWeekEvent,
    PublicWeekResponse,
)
from backend.utils.api_auth import api_token_rate_limit_key, get_api_user

logger = logging.getLogger(__name__)

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


# ── Important emails (joins AIAnalysis) ─────────────────────────────


def _serialize_important_email(
    e: Email,
    a: Optional[AIAnalysis],
    account_email: Optional[str],
) -> PublicImportantEmail:
    return PublicImportantEmail(
        id=e.id,
        gmail_message_id=e.gmail_message_id,
        gmail_thread_id=e.gmail_thread_id,
        account_email=account_email,
        subject=e.subject,
        from_name=e.from_name,
        from_address=e.from_address,
        date=e.date,
        snippet=e.snippet,
        is_read=e.is_read,
        is_starred=e.is_starred,
        has_attachments=e.has_attachments,
        labels=e.labels or [],
        priority=(a.priority if a and a.priority is not None else 0),
        needs_reply=bool(a.needs_reply) if a else False,
        ai_summary=a.summary if a else None,
        ai_category=a.category if a else None,
    )


async def _fetch_important_emails(
    db: AsyncSession,
    account_emails: dict[int, str],
    *,
    limit: int,
    unread_only: bool,
    days: Optional[int],
    mailbox: str,
) -> list[PublicImportantEmail]:
    if not account_emails:
        return []

    query = (
        select(Email, AIAnalysis)
        .join(AIAnalysis, AIAnalysis.email_id == Email.id)
        .where(Email.account_id.in_(account_emails.keys()))
    )

    if mailbox == "STARRED":
        query = query.where(Email.is_starred == True)
    elif mailbox == "ALL":
        query = query.where(Email.is_trash == False, Email.is_spam == False)
    else:
        gmail_label = MAILBOX_LABEL_MAP.get(mailbox, mailbox)
        if gmail_label:
            query = query.where(jsonb_contains(Email.labels, f'["{gmail_label}"]'))
        query = query.where(Email.is_trash == False, Email.is_spam == False)

    if unread_only:
        query = query.where(Email.is_read == False)

    if days and days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.where(Email.date >= cutoff)

    query = query.where(
        or_(
            AIAnalysis.priority >= 2,
            and_(
                AIAnalysis.needs_reply == True,
                or_(
                    AIAnalysis.needs_reply_ignored == False,
                    AIAnalysis.needs_reply_ignored.is_(None),
                ),
            ),
        )
    )

    # Order by priority desc, then needs_reply, then date
    query = query.order_by(
        desc(AIAnalysis.priority),
        desc(AIAnalysis.needs_reply),
        desc(Email.date),
    ).limit(limit)

    result = await db.execute(query)
    rows = result.all()
    return [
        _serialize_important_email(e, a, account_emails.get(e.account_id))
        for e, a in rows
    ]


@router.get("/emails/important", response_model=PublicImportantEmailListResponse)
@limiter.limit("60/minute")
async def emails_important(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    unread_only: bool = Query(True),
    days: int = Query(7, ge=1, le=90),
    mailbox: str = Query("INBOX"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Emails the AI flagged as important: priority>=high or needs_reply=true (and not ignored)."""
    accounts = await _get_account_map(db, user)
    emails = await _fetch_important_emails(
        db,
        accounts,
        limit=limit,
        unread_only=unread_only,
        days=days,
        mailbox=mailbox,
    )
    return PublicImportantEmailListResponse(emails=emails, total=len(emails))


# ── Thread digests ──────────────────────────────────────────────────


def _serialize_digest(d: ThreadDigest, account_email: Optional[str]) -> PublicThreadDigest:
    return PublicThreadDigest(
        id=d.id,
        account_email=account_email,
        thread_id=d.gmail_thread_id,
        subject=d.subject,
        conversation_type=d.conversation_type,
        summary=d.summary,
        resolved_outcome=d.resolved_outcome,
        is_resolved=bool(d.is_resolved),
        key_topics=d.key_topics or [],
        message_count=d.message_count or 0,
        participants=d.participants or [],
        latest_date=d.latest_date,
        updated_at=d.updated_at,
    )


async def _fetch_recent_digests(
    db: AsyncSession,
    account_emails: dict[int, str],
    *,
    limit: int,
    unresolved_only: bool,
) -> list[PublicThreadDigest]:
    if not account_emails:
        return []
    query = select(ThreadDigest).where(
        ThreadDigest.account_id.in_(account_emails.keys())
    )
    if unresolved_only:
        query = query.where(
            or_(ThreadDigest.is_resolved == False, ThreadDigest.is_resolved.is_(None))
        )
    query = query.order_by(desc(ThreadDigest.latest_date)).limit(limit)
    result = await db.execute(query)
    return [
        _serialize_digest(d, account_emails.get(d.account_id))
        for d in result.scalars().all()
    ]


@router.get("/emails/digests", response_model=PublicThreadDigestListResponse)
@limiter.limit("60/minute")
async def emails_digests(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    unresolved_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Recent AI-generated thread digests (multi-message threads collapsed into one summary)."""
    accounts = await _get_account_map(db, user)
    digests = await _fetch_recent_digests(
        db, accounts, limit=limit, unresolved_only=unresolved_only
    )
    return PublicThreadDigestListResponse(digests=digests, total=len(digests))


# ── Email volume ────────────────────────────────────────────────────


async def _fetch_email_volume(
    db: AsyncSession,
    account_emails: dict[int, str],
    *,
    days: int,
    zone: ZoneInfo,
) -> PublicVolumeResponse:
    """Per-day received/unread/sent counts plus per-account totals.

    Days are bucketed in the requested local timezone.
    """
    if not account_emails:
        return PublicVolumeResponse(
            days=[],
            by_account=[],
            received_total=0,
            sent_total=0,
            average_per_day=0.0,
            timezone=str(zone),
        )

    end_local = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start_local = end_local - timedelta(days=days)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    # PostgreSQL: convert UTC date column to the requested timezone, then truncate to day.
    local_day = func.to_char(
        func.timezone(str(zone), Email.date),
        "YYYY-MM-DD",
    ).label("local_day")

    base_filter = [
        Email.account_id.in_(account_emails.keys()),
        Email.date >= start_utc,
        Email.date < end_utc,
        Email.is_trash == False,
        Email.is_spam == False,
    ]

    received_query = (
        select(
            local_day,
            func.count(Email.id).label("received"),
            func.sum(case((Email.is_read == False, 1), else_=0)).label("unread"),
        )
        .where(*base_filter, Email.is_sent == False)
        .group_by("local_day")
    )

    sent_query = (
        select(
            local_day,
            func.count(Email.id).label("sent"),
        )
        .where(*base_filter, Email.is_sent == True)
        .group_by("local_day")
    )

    received_rows = (await db.execute(received_query)).all()
    sent_rows = (await db.execute(sent_query)).all()

    received_map = {r.local_day: (int(r.received or 0), int(r.unread or 0)) for r in received_rows}
    sent_map = {r.local_day: int(r.sent or 0) for r in sent_rows}

    days_list: list[PublicVolumeDay] = []
    cursor = start_local
    while cursor < end_local:
        key = cursor.strftime("%Y-%m-%d")
        recv, unread = received_map.get(key, (0, 0))
        sent = sent_map.get(key, 0)
        days_list.append(PublicVolumeDay(date=key, received=recv, unread=unread, sent=sent))
        cursor += timedelta(days=1)

    received_total = sum(d.received for d in days_list)
    sent_total = sum(d.sent for d in days_list)

    # Per-account rollup
    per_account_rows = (
        await db.execute(
            select(
                Email.account_id,
                Email.is_sent,
                func.count(Email.id),
            )
            .where(*base_filter)
            .group_by(Email.account_id, Email.is_sent)
        )
    ).all()

    per_account: dict[int, dict[str, int]] = {}
    for aid, is_sent, cnt in per_account_rows:
        bucket = per_account.setdefault(aid, {"received": 0, "sent": 0})
        if is_sent:
            bucket["sent"] += int(cnt)
        else:
            bucket["received"] += int(cnt)

    by_account = [
        PublicVolumeAccountRollup(
            account_id=aid,
            account_email=email,
            received=per_account.get(aid, {}).get("received", 0),
            sent=per_account.get(aid, {}).get("sent", 0),
        )
        for aid, email in account_emails.items()
    ]

    avg = round(received_total / days, 2) if days > 0 else 0.0

    return PublicVolumeResponse(
        days=days_list,
        by_account=by_account,
        received_total=received_total,
        sent_total=sent_total,
        average_per_day=avg,
        timezone=str(zone),
    )


@router.get("/emails/volume", response_model=PublicVolumeResponse)
@limiter.limit("60/minute")
async def emails_volume(
    request: Request,
    days: int = Query(14, ge=1, le=90),
    tz: Optional[str] = Query(None, description="IANA timezone for day bucketing. Defaults to UTC."),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Daily inbound (received + unread) and outbound (sent) email counts."""
    accounts = await _get_account_map(db, user)
    zone = _resolve_tz(tz)
    return await _fetch_email_volume(db, accounts, days=days, zone=zone)


# ── Calendar week-ahead ─────────────────────────────────────────────


_IMPORTANCE_KEYWORDS = (
    "interview",
    "review",
    "board",
    "1:1",
    "1-on-1",
    "one on one",
    "kickoff",
    "kick off",
    "all-hands",
    "all hands",
    "demo",
    "presentation",
    "exec",
    "leadership",
    "investor",
    "customer",
    "client",
    "offsite",
    "off site",
    "launch",
    "release",
    "release review",
    "performance review",
)


def _event_importance(
    event: CalendarEvent,
    user_emails: set[str],
) -> tuple[bool, list[str]]:
    """Cheap heuristics: returns (is_important, reasons).

    Important when any of:
    - Has external attendees (someone not in the user's connected emails)
    - User is the organizer
    - Summary contains a flagged keyword
    """
    reasons: list[str] = []

    attendees = event.attendees or []
    other_emails = []
    for a in attendees:
        if not isinstance(a, dict):
            continue
        email = (a.get("email") or "").strip().lower()
        if email and email not in user_emails:
            other_emails.append(email)
    if other_emails:
        reasons.append(f"with {len(other_emails)} external attendee(s)")

    organizer = (event.organizer_email or "").strip().lower()
    if organizer and organizer in user_emails:
        reasons.append("you organized")

    summary = (event.summary or "").lower()
    matched_keyword = next((kw for kw in _IMPORTANCE_KEYWORDS if kw in summary), None)
    if matched_keyword:
        reasons.append(f'"{matched_keyword}" in title')

    return (len(reasons) > 0, reasons)


def _serialize_week_event(
    event: CalendarEvent,
    account_email: Optional[str],
    user_emails: set[str],
) -> PublicWeekEvent:
    important, reasons = _event_importance(event, user_emails)
    base = _serialize_event(event, account_email).model_dump()
    return PublicWeekEvent(**base, is_important=important, importance_reasons=reasons)


def _event_local_dates(event: CalendarEvent, zone: ZoneInfo) -> list[str]:
    """Return all local YYYY-MM-DD dates this event touches in the given timezone."""
    if event.is_all_day:
        if not event.start_date:
            return []
        # Google all-day events have an exclusive end_date; treat as inclusive of start through (end - 1 day).
        try:
            start = datetime.strptime(event.start_date, "%Y-%m-%d").date()
        except ValueError:
            return []
        end_str = event.end_date or event.start_date
        try:
            end_excl = datetime.strptime(end_str, "%Y-%m-%d").date()
        except ValueError:
            end_excl = start + timedelta(days=1)
        if end_excl <= start:
            end_excl = start + timedelta(days=1)
        days: list[str] = []
        cur = start
        while cur < end_excl:
            days.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        return days

    if not event.start_time:
        return []
    end = event.end_time or (event.start_time + timedelta(minutes=30))
    start_local = event.start_time.astimezone(zone)
    end_local = end.astimezone(zone)
    days: list[str] = []
    cur = start_local.date()
    last = end_local.date()
    # Don't count an event ending exactly at midnight as touching the next day.
    if end_local.time() == datetime.min.time() and end_local.date() > start_local.date():
        last = end_local.date() - timedelta(days=1)
    while cur <= last:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def _event_busy_minutes_on_date(event: CalendarEvent, day_str: str, zone: ZoneInfo) -> int:
    if event.is_all_day or not event.start_time or not event.end_time:
        return 0
    try:
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
    except ValueError:
        return 0
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=zone)
    day_end = day_start + timedelta(days=1)
    start = max(event.start_time.astimezone(zone), day_start)
    end = min(event.end_time.astimezone(zone), day_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)


def _day_label(target: date_cls, today: date_cls) -> str:
    delta = (target - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    return target.strftime("%a %b %-d")


async def _build_week(
    db: AsyncSession,
    user: User,
    accounts: dict[int, str],
    *,
    days: int,
    zone: ZoneInfo,
) -> PublicWeekResponse:
    if not accounts:
        return PublicWeekResponse(days=[], timezone=str(zone))

    now_local = datetime.now(zone)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=days)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    today_str = start_local.strftime("%Y-%m-%d")
    end_str = end_local.strftime("%Y-%m-%d")

    timed_condition = and_(
        CalendarEvent.is_all_day == False,
        CalendarEvent.start_time < end_utc,
        CalendarEvent.end_time > start_utc,
    )
    allday_condition = and_(
        CalendarEvent.is_all_day == True,
        CalendarEvent.start_date < end_str,
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

    user_emails = {e.lower() for e in accounts.values() if e}
    if user.email:
        user_emails.add(user.email.lower())

    # Bucket events by local date
    buckets: dict[str, list[PublicWeekEvent]] = {}
    busy: dict[str, int] = {}
    for ev in events:
        we = _serialize_week_event(ev, accounts.get(ev.account_id), user_emails)
        for day_str in _event_local_dates(ev, zone):
            buckets.setdefault(day_str, []).append(we)
            busy[day_str] = busy.get(day_str, 0) + _event_busy_minutes_on_date(ev, day_str, zone)

    today = start_local.date()
    days_out: list[PublicWeekDay] = []
    for offset in range(days):
        d = today + timedelta(days=offset)
        key = d.strftime("%Y-%m-%d")
        evs = buckets.get(key, [])
        days_out.append(
            PublicWeekDay(
                date=key,
                label=_day_label(d, today),
                weekday=d.strftime("%A"),
                events=evs,
                busy_minutes=busy.get(key, 0),
                important_count=sum(1 for e in evs if e.is_important),
            )
        )
    return PublicWeekResponse(days=days_out, timezone=str(zone))


@router.get("/calendar/week", response_model=PublicWeekResponse)
@limiter.limit("60/minute")
async def calendar_week(
    request: Request,
    days: int = Query(7, ge=1, le=21),
    tz: Optional[str] = Query(None, description="IANA timezone for day bucketing. Defaults to UTC."),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Calendar grouped by local day for the next `days` days, with cheap importance flags."""
    accounts = await _get_account_map(db, user)
    zone = _resolve_tz(tz)
    return await _build_week(db, user, accounts, days=days, zone=zone)


# ── Briefing (newspaper front page) ─────────────────────────────────


def _truncate_for_prompt(text: Optional[str], n: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "\u2026"


def _briefing_to_prompt_payload(briefing: PublicBriefing) -> dict:
    """Compress a PublicBriefing into the structured JSON we hand to Claude."""
    def event_dict(e: PublicWeekEvent) -> dict:
        return {
            "summary": _truncate_for_prompt(e.summary, 140),
            "start": e.start_time.isoformat() if e.start_time else e.start_date,
            "end": e.end_time.isoformat() if e.end_time else e.end_date,
            "all_day": e.is_all_day,
            "location": _truncate_for_prompt(e.location, 100),
            "important": e.is_important,
            "important_reasons": e.importance_reasons,
        }

    return {
        "today": [event_dict(e) for e in briefing.today][:25],
        "tomorrow": [event_dict(e) for e in briefing.tomorrow][:25],
        "week_ahead": [
            {
                "date": d.date,
                "label": d.label,
                "weekday": d.weekday,
                "busy_minutes": d.busy_minutes,
                "important_count": d.important_count,
                "events": [event_dict(e) for e in d.events][:8],
            }
            for d in briefing.week_ahead
        ],
        "important_emails": [
            {
                "from": e.from_name or e.from_address,
                "subject": _truncate_for_prompt(e.subject, 140),
                "snippet": _truncate_for_prompt(e.snippet, 220),
                "ai_summary": _truncate_for_prompt(e.ai_summary, 220),
                "priority": e.priority,
                "needs_reply": e.needs_reply,
                "category": e.ai_category,
                "is_read": e.is_read,
                "date": e.date.isoformat() if e.date else None,
            }
            for e in briefing.important_emails
        ][:20],
        "recent_digests": [
            {
                "subject": _truncate_for_prompt(d.subject, 140),
                "summary": _truncate_for_prompt(d.summary, 280),
                "outcome": _truncate_for_prompt(d.resolved_outcome, 200),
                "is_resolved": d.is_resolved,
                "type": d.conversation_type,
                "messages": d.message_count,
            }
            for d in briefing.recent_digests
        ][:10],
        "volume": {
            "received_total": briefing.volume.received_total,
            "sent_total": briefing.volume.sent_total,
            "average_per_day": briefing.volume.average_per_day,
            "days": [d.model_dump() for d in briefing.volume.days],
        },
        "unread": {
            "total": briefing.unread.unread,
            "by_account": [
                {"email": a.account_email, "unread": a.unread}
                for a in briefing.unread.by_account
            ],
        },
    }


_BRIEFING_PROMPT_SYSTEM_TMPL = """You write short, concrete daily briefings for a busy person -- think morning newspaper editor, not corporate report.

Length target:
- Aim for roughly {char_target} characters of plain text. {length_guidance}
- This is a soft target: a little over or under is fine. Never leave a sentence half-finished to hit the number.

Style:
- Plain text (no markdown bullet lists, no headings).
- Lead with what matters most about today.
- Mention specific calendar items by title and time when they are important; skip routine blocks.
- Mention specific emails or threads the user should engage with, by sender, when space allows.
- If the target length permits, end with a brief week-ahead note about anything notable coming up.
- Don't restate raw counts mechanically; weave them into prose ("today is unusually quiet", "your inbox is up about 30% this week").
- If there is little going on, say so plainly. Don't pad to hit the length."""


def _length_guidance(char_target: int) -> str:
    """Style hint that scales with the requested length."""
    if char_target <= 200:
        return "One tight sentence. Single most important thing only."
    if char_target <= 400:
        return "1-2 sentences. Today's headline and at most one other beat."
    if char_target <= 800:
        return "2-3 short paragraphs. Today, then one note about emails or the week ahead."
    if char_target <= 1500:
        return "3-4 paragraphs. Cover today, the week's anchor events, and 2-3 specific emails or threads."
    return "Up to a full column. Cover today thoroughly, name multiple specific events and threads, and end with a real week-ahead outlook."


def _trim_to_chars(text: str, char_target: int) -> str:
    """Soft trim if Claude overshot the requested length.

    Uses 1.4x the target as a forgiving ceiling so well-balanced prose isn't chopped.
    Trims at the last sentence boundary inside the budget when possible.
    """
    if not text:
        return text
    ceiling = max(int(char_target * 1.4), char_target + 80)
    if len(text) <= ceiling:
        return text
    cut = text[:ceiling]
    for sep in (". ", "! ", "? ", "\n\n"):
        idx = cut.rfind(sep)
        if idx >= int(char_target * 0.6):
            return cut[: idx + len(sep)].rstrip()
    return cut.rstrip() + "\u2026"


async def _generate_briefing_summary(
    user: User,
    briefing: PublicBriefing,
    *,
    char_target: int,
) -> tuple[str, str, int]:
    """Call Claude once to write the briefing prose. Returns (summary, model, tokens)."""
    from backend.config import get_settings as _gs
    from backend.services.ai import get_custom_prompt_model_for_user

    settings_local = _gs()
    if not settings_local.claude_api_key:
        raise HTTPException(status_code=503, detail="Claude API key not configured")

    model = await get_custom_prompt_model_for_user(user.id)
    payload = _briefing_to_prompt_payload(briefing)

    user_prompt = (
        "Here is structured data about today, the week ahead, important emails, "
        "thread digests, and recent inbox volume. Write the briefing.\n\n"
        f"```json\n{json.dumps(payload, default=str)[:60000]}\n```"
    )

    system_prompt = _BRIEFING_PROMPT_SYSTEM_TMPL.format(
        char_target=char_target,
        length_guidance=_length_guidance(char_target),
    )

    # ~4 chars per token, plus generous headroom so Claude can finish a sentence
    # past the soft target without getting cut off; clamp to a sane ceiling.
    max_tokens = max(120, min(int(char_target / 4 * 1.6) + 80, 2400))

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings_local.claude_api_key)
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Claude briefing summary failed")
        raise HTTPException(status_code=502, detail=f"Upstream AI error: {exc}")

    text_parts = [
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ]
    text = "\n".join(text_parts).strip()
    text = _trim_to_chars(text, char_target)
    tokens = (resp.usage.input_tokens or 0) + (resp.usage.output_tokens or 0)
    return text, model, tokens


async def _build_briefing(
    db: AsyncSession,
    user: User,
    *,
    days: int,
    zone: ZoneInfo,
    include_summary: bool,
    important_limit: int = 20,
    digests_limit: int = 10,
    summary_chars: int = 600,
) -> PublicBriefing:
    accounts = await _get_account_map(db, user)

    week_task = _build_week(db, user, accounts, days=days, zone=zone)
    important_task = _fetch_important_emails(
        db, accounts, limit=important_limit, unread_only=True, days=14, mailbox="INBOX"
    )
    digests_task = _fetch_recent_digests(
        db, accounts, limit=digests_limit, unresolved_only=False
    )
    volume_task = _fetch_email_volume(db, accounts, days=7, zone=zone)
    unread_task = _compute_unread(db, accounts)

    week, important, digests, volume, unread = await asyncio.gather(
        week_task, important_task, digests_task, volume_task, unread_task
    )

    today_key = datetime.now(zone).strftime("%Y-%m-%d")
    tomorrow_key = (datetime.now(zone) + timedelta(days=1)).strftime("%Y-%m-%d")
    today_events: list[PublicWeekEvent] = []
    tomorrow_events: list[PublicWeekEvent] = []
    for d in week.days:
        if d.date == today_key:
            today_events = d.events
        elif d.date == tomorrow_key:
            tomorrow_events = d.events

    briefing = PublicBriefing(
        meta=PublicBriefingMeta(
            generated_at=datetime.now(timezone.utc),
            timezone=str(zone),
            days=days,
            summary_included=include_summary,
        ),
        today=today_events,
        tomorrow=tomorrow_events,
        week_ahead=week.days,
        important_emails=important,
        recent_digests=digests,
        volume=volume,
        unread=unread,
    )

    if include_summary:
        summary, model, tokens = await _generate_briefing_summary(
            user, briefing, char_target=summary_chars
        )
        briefing.summary = summary
        briefing.meta.summary_model = model
        briefing.meta.summary_tokens_used = tokens
        briefing.meta.summary_char_target = summary_chars

    return briefing


async def _compute_unread(
    db: AsyncSession,
    accounts: dict[int, str],
) -> PublicUnreadCountResponse:
    if not accounts:
        return PublicUnreadCountResponse(unread=0, by_account=[])

    base_filter = [
        Email.account_id.in_(accounts.keys()),
        Email.is_read == False,
        Email.is_trash == False,
        Email.is_spam == False,
        jsonb_contains(Email.labels, '["INBOX"]'),
    ]

    total = await db.scalar(select(func.count(Email.id)).where(*base_filter)) or 0
    per_account_result = await db.execute(
        select(Email.account_id, func.count(Email.id))
        .where(*base_filter)
        .group_by(Email.account_id)
    )
    counts = {row[0]: row[1] for row in per_account_result.all()}
    by_account = [
        PublicUnreadByAccount(account_id=aid, account_email=email, unread=counts.get(aid, 0))
        for aid, email in accounts.items()
    ]
    return PublicUnreadCountResponse(unread=total, by_account=by_account)


@router.get("/briefing", response_model=PublicBriefing)
@limiter.limit("30/minute")
async def briefing(
    request: Request,
    tz: Optional[str] = Query(None, description="IANA timezone for day bucketing."),
    days: int = Query(7, ge=1, le=14, description="How many days to include in week_ahead."),
    summary: bool = Query(False, description="If true, also generates a Claude-written prose briefing."),
    summary_chars: int = Query(
        600,
        ge=100,
        le=4000,
        description="Soft target length for the AI prose summary, in characters. Ignored when summary=false.",
    ),
    important_limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of important_emails to return.",
    ),
    digests_limit: int = Query(
        10,
        ge=1,
        le=50,
        description="Maximum number of recent_digests to return.",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Newspaper-style 'what's going on' payload. Pass ?summary=true for the AI prose.

    The /briefing path itself is rate-limited at 30/min. The Claude prose path is also
    available standalone at /briefing/summary with a stricter 10/min limit; if you poll
    this endpoint with ?summary=true frequently, prefer that split instead.
    """
    zone = _resolve_tz(tz)
    return await _build_briefing(
        db,
        user,
        days=days,
        zone=zone,
        include_summary=summary,
        important_limit=important_limit,
        digests_limit=digests_limit,
        summary_chars=summary_chars,
    )


@router.get("/briefing/summary", response_model=PublicBriefingSummaryResponse)
@limiter.limit("10/minute")
async def briefing_summary(
    request: Request,
    tz: Optional[str] = Query(None, description="IANA timezone for day bucketing."),
    days: int = Query(7, ge=1, le=14),
    chars: int = Query(
        600,
        ge=100,
        le=4000,
        description="Soft target length for the AI prose summary, in characters.",
    ),
    important_limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Number of important emails to feed Claude when composing the prose.",
    ),
    digests_limit: int = Query(
        10,
        ge=1,
        le=50,
        description="Number of recent thread digests to feed Claude when composing the prose.",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Just the Claude-written prose briefing. Useful when you poll /briefing separately."""
    zone = _resolve_tz(tz)
    briefing = await _build_briefing(
        db,
        user,
        days=days,
        zone=zone,
        include_summary=True,
        important_limit=important_limit,
        digests_limit=digests_limit,
        summary_chars=chars,
    )
    return PublicBriefingSummaryResponse(
        summary=briefing.summary or "",
        model=briefing.meta.summary_model or "",
        tokens_used=briefing.meta.summary_tokens_used or 0,
        char_target=briefing.meta.summary_char_target or chars,
        generated_at=briefing.meta.generated_at,
        timezone=briefing.meta.timezone,
    )


# ── Claude-powered ask ──────────────────────────────────────────────


def _parse_sse_event(event_str: str) -> tuple[str, dict]:
    """Parse one SSE event string into (event_type, data_dict)."""
    event_type = ""
    data_blob = ""
    for line in event_str.strip().split("\n"):
        if line.startswith("event: "):
            event_type = line[7:].strip()
        elif line.startswith("data: "):
            data_blob += line[6:]
    if not data_blob:
        return event_type, {}
    try:
        return event_type, json.loads(data_blob)
    except json.JSONDecodeError:
        return event_type, {}


# Hard ceiling on /ask timeout. Any user-supplied value above this is clamped.
_ASK_MAX_TIMEOUT_SECONDS = 120


@router.post("/ask", response_model=PublicAskResponse)
@limiter.limit("20/minute")
async def ask(
    request: Request,
    body: PublicAskRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_api_user),
):
    """Ask Claude a free-form question about your emails and calendar.

    Uses the same plan->execute->verify agent as the web chat, but returns one JSON
    response instead of an SSE stream. Does not persist a chat conversation.
    """
    from backend.services.chat import ChatService
    from backend.services.ai_models import CHEAP_MODEL

    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    # Look up accounts + per-account context (mirrors backend/routers/chat.py).
    acct_result = await db.execute(
        select(GoogleAccount.id, GoogleAccount.email, GoogleAccount.description)
        .where(
            GoogleAccount.user_id == user.id,
            GoogleAccount.is_active == True,
        )
    )
    acct_rows = acct_result.all()
    account_ids = [r[0] for r in acct_rows]
    if not account_ids:
        raise HTTPException(
            status_code=400,
            detail="No email accounts connected. Connect a Google account first.",
        )
    account_contexts = [
        {"email": r[1], "description": r[2]} for r in acct_rows
    ]

    timeout = max(5, min(int(body.timeout_seconds or 60), _ASK_MAX_TIMEOUT_SECONDS))

    # If `fast`, swap the user's chat model preferences in-memory just for this call.
    # Detach the user from the session first so the swap isn't auto-flushed back to DB.
    if body.fast:
        try:
            db.expunge(user)
        except Exception:
            pass
        prefs = dict(user.ai_preferences or {})
        prefs["chat_plan_model"] = CHEAP_MODEL
        prefs["chat_execute_model"] = CHEAP_MODEL
        prefs["chat_verify_model"] = CHEAP_MODEL
        user.ai_preferences = prefs

    chat_service = ChatService()

    plan_data: list = []
    task_results: dict = {}
    final_content = ""
    clarification: Optional[str] = None
    total_tokens = 0
    model_used = ""
    started = time.monotonic()

    async def _consume() -> None:
        nonlocal plan_data, task_results, final_content, clarification, total_tokens, model_used
        async for sse_event in chat_service.run_chat(
            user_query=body.prompt.strip(),
            user=user,
            account_ids=account_ids,
            db=db,
            conversation_history=None,
            account_contexts=account_contexts,
        ):
            etype, data = _parse_sse_event(sse_event)
            if etype == "plan_ready":
                plan_data = data.get("tasks") or []
            elif etype == "task_complete":
                task_results[data.get("task_id")] = data.get("summary", "")
            elif etype == "task_failed":
                task_results[data.get("task_id")] = f"Failed: {data.get('error', '')}"
            elif etype == "content":
                final_content = data.get("text", "") or final_content
            elif etype == "clarification":
                clarification = data.get("question", "")
            elif etype == "done":
                total_tokens = int(data.get("tokens_used") or 0)
            elif etype == "model":
                model_used = data.get("model", "") or model_used

    try:
        await asyncio.wait_for(_consume(), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Claude did not respond within {timeout} seconds",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Ask endpoint failed")
        raise HTTPException(status_code=502, detail=f"Upstream AI error: {exc}")

    if not model_used:
        # Fall back to the user's verify-phase model preference for transparency.
        prefs = user.ai_preferences or {}
        from backend.services.ai_models import DEFAULT_AI_PREFERENCES
        model_used = (
            prefs.get("chat_verify_model")
            or prefs.get("chat_plan_model")
            or DEFAULT_AI_PREFERENCES.get("chat_verify_model", "")
        )

    return PublicAskResponse(
        answer=final_content if not clarification else None,
        clarification=clarification,
        plan=[
            PublicAskTask(
                id=int(t.get("id", i)),
                description=t.get("description"),
                search_strategy=t.get("search_strategy"),
                depends_on=list(t.get("depends_on") or []),
            )
            for i, t in enumerate(plan_data, start=1)
            if isinstance(t, dict)
        ],
        task_results=task_results,
        model=model_used,
        tokens_used=total_tokens,
        duration_seconds=round(time.monotonic() - started, 3),
    )
