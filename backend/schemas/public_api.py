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


# ── Newspaper / "what's going on" expansion ─────────────────────────


class PublicImportantEmail(PublicEmail):
    """A regular `PublicEmail` plus the AI signals that made us call it important."""
    priority: int = 0  # 0=low, 1=normal, 2=high, 3=urgent
    needs_reply: bool = False
    ai_summary: Optional[str] = None
    ai_category: Optional[str] = None


class PublicImportantEmailListResponse(BaseModel):
    emails: list[PublicImportantEmail]
    total: int


class PublicThreadDigest(BaseModel):
    id: int
    account_email: Optional[str] = None
    thread_id: str
    subject: Optional[str] = None
    conversation_type: Optional[str] = None
    summary: Optional[str] = None
    resolved_outcome: Optional[str] = None
    is_resolved: bool = False
    key_topics: list[str] = []
    message_count: int = 0
    participants: list = []
    latest_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PublicThreadDigestListResponse(BaseModel):
    digests: list[PublicThreadDigest]
    total: int


class PublicVolumeDay(BaseModel):
    date: str  # YYYY-MM-DD in the requested local timezone
    received: int
    unread: int
    sent: int


class PublicVolumeAccountRollup(BaseModel):
    account_id: int
    account_email: str
    received: int
    sent: int


class PublicVolumeResponse(BaseModel):
    days: list[PublicVolumeDay]
    by_account: list[PublicVolumeAccountRollup]
    received_total: int
    sent_total: int
    average_per_day: float
    timezone: str


class PublicWeekEvent(PublicCalendarEvent):
    """Calendar event annotated with a cheap importance heuristic."""
    is_important: bool = False
    importance_reasons: list[str] = []


class PublicWeekDay(BaseModel):
    date: str  # YYYY-MM-DD
    label: str  # "Today", "Tomorrow", "Mon May 4"
    weekday: str  # "Monday"
    events: list[PublicWeekEvent]
    busy_minutes: int  # Total non-all-day duration scheduled
    important_count: int


class PublicWeekResponse(BaseModel):
    days: list[PublicWeekDay]
    timezone: str


class PublicBriefingMeta(BaseModel):
    generated_at: datetime
    timezone: str
    days: int
    summary_included: bool
    summary_model: Optional[str] = None
    summary_tokens_used: Optional[int] = None


class PublicBriefing(BaseModel):
    meta: PublicBriefingMeta
    today: list[PublicWeekEvent]
    tomorrow: list[PublicWeekEvent]
    week_ahead: list[PublicWeekDay]
    important_emails: list[PublicImportantEmail]
    recent_digests: list[PublicThreadDigest]
    volume: PublicVolumeResponse
    unread: PublicUnreadCountResponse
    summary: Optional[str] = None  # Claude-written prose, only when ?summary=true


class PublicBriefingSummaryResponse(BaseModel):
    summary: str
    model: str
    tokens_used: int
    generated_at: datetime
    timezone: str


# ── Claude-powered ask ──────────────────────────────────────────────


class PublicAskRequest(BaseModel):
    prompt: str
    tz: Optional[str] = None
    fast: bool = False
    timeout_seconds: int = 60


class PublicAskTask(BaseModel):
    id: int
    description: Optional[str] = None
    search_strategy: Optional[str] = None
    depends_on: list[int] = []


class PublicAskResponse(BaseModel):
    answer: Optional[str] = None
    clarification: Optional[str] = None  # Set if the planner asked for clarification instead of answering
    plan: list[PublicAskTask] = []
    task_results: dict = {}
    model: str
    tokens_used: int
    duration_seconds: float
