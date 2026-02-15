from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CalendarEventResponse(BaseModel):
    id: int
    account_id: int
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

    recurring_event_id: Optional[str] = None
    recurrence_rule: Optional[dict] = None

    status: str = "confirmed"
    html_link: Optional[str] = None
    hangout_link: Optional[str] = None

    organizer_email: Optional[str] = None
    organizer_name: Optional[str] = None
    organizer_self: bool = False

    attendees: Optional[list] = None

    visibility: Optional[str] = None
    transparency: Optional[str] = None
    reminders: Optional[dict] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CalendarEventListResponse(BaseModel):
    events: list[CalendarEventResponse]
    total: int


class CalendarSyncStatusResponse(BaseModel):
    account_id: int
    account_email: Optional[str] = None
    status: str = "idle"
    sync_token: Optional[str] = None
    last_full_sync: Optional[datetime] = None
    last_incremental_sync: Optional[datetime] = None
    error_message: Optional[str] = None
    events_synced: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
