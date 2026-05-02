"""Stable response schemas for the public read-only API at /api/v1/...

Independent of internal schemas so we can refactor internals freely.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PublicAccount(BaseModel):
    id: int
    email: str


class PublicMeResponse(BaseModel):
    id: int
    email: Optional[str] = None
    display_name: Optional[str] = None
    accounts: list[PublicAccount] = []


class PublicEmail(BaseModel):
    id: int
    gmail_message_id: str
    gmail_thread_id: str
    account_email: Optional[str] = None
    subject: Optional[str] = None
    from_name: Optional[str] = None
    from_address: Optional[str] = None
    date: Optional[datetime] = None
    snippet: Optional[str] = None
    is_read: bool = False
    is_starred: bool = False
    has_attachments: bool = False
    labels: list[str] = []


class PublicEmailListResponse(BaseModel):
    emails: list[PublicEmail]
    total: int


class PublicCalendarEvent(BaseModel):
    id: int
    account_email: Optional[str] = None
    google_event_id: str
    calendar_id: str = "primary"
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    timezone: Optional[str] = None
    is_all_day: bool = False
    status: str = "confirmed"
    html_link: Optional[str] = None
    hangout_link: Optional[str] = None
    organizer_email: Optional[str] = None
    organizer_name: Optional[str] = None
    attendees: Optional[list] = None


class PublicCalendarListResponse(BaseModel):
    events: list[PublicCalendarEvent]
    total: int


class PublicUnreadByAccount(BaseModel):
    account_id: int
    account_email: str
    unread: int


class PublicUnreadCountResponse(BaseModel):
    unread: int
    by_account: list[PublicUnreadByAccount]
