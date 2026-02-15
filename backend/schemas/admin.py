from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SettingResponse(BaseModel):
    id: int
    key: str
    value: Optional[str] = None
    is_secret: bool = False
    description: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    key: str
    value: str
    is_secret: bool = False
    description: Optional[str] = None


class GoogleAccountResponse(BaseModel):
    id: int
    email: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    short_label: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    sync_status: Optional["SyncStatusResponse"] = None
    has_calendar_scope: bool = False

    model_config = {"from_attributes": True}


class SyncStatusResponse(BaseModel):
    status: str = "idle"
    messages_synced: int = 0
    total_messages: int = 0
    current_phase: Optional[str] = None
    error_message: Optional[str] = None
    last_full_sync: Optional[datetime] = None
    last_incremental_sync: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_after: Optional[datetime] = None

    model_config = {"from_attributes": True}


class GoogleOAuthStart(BaseModel):
    auth_url: str


class DashboardStats(BaseModel):
    total_accounts: int = 0
    total_emails: int = 0
    total_unread: int = 0
    sync_active: bool = False
    ai_analyses_count: int = 0
    storage_used_bytes: int = 0
