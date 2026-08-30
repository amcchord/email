from datetime import datetime, timedelta, timezone
import json
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, cast, Date, case
from backend.database import get_db
from backend.models.user import User
from backend.models.settings import Setting
from backend.models.account import GoogleAccount, SyncStatus
from backend.models.email import Email
from backend.models.ai import AIAnalysis
from backend.schemas.admin import (
    SettingResponse, SettingUpdate, CalendarSyncHealthResponse,
    GoogleAccountResponse, SyncStatusResponse, DashboardStats,
)
from backend.routers.auth import require_admin, get_current_user
from backend.utils.security import encrypt_value, decrypt_value

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Default values for feature flags
FEATURE_FLAG_DEFAULTS = {
    "desktop_app_enabled": "false",
    "tui_enabled": "true",
}


@router.get("/feature-flags")
async def get_feature_flags(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return feature flags. Accessible to any authenticated user."""
    result = await db.execute(
        select(Setting).where(
            Setting.key.in_(list(FEATURE_FLAG_DEFAULTS.keys()))
        )
    )
    settings_map = {s.key: s.value for s in result.scalars().all()}

    flags = {}
    for key, default in FEATURE_FLAG_DEFAULTS.items():
        raw = settings_map.get(key, default)
        flags[key] = raw.lower() in ("true", "1", "yes")

    return flags


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    accounts_count = await db.scalar(select(func.count(GoogleAccount.id)))
    emails_count = await db.scalar(select(func.count(Email.id)))
    unread_count = await db.scalar(
        select(func.count(Email.id)).where(Email.is_read == False)
    )
    syncing = await db.scalar(
        select(func.count(SyncStatus.id)).where(SyncStatus.status == "syncing")
    )
    ai_count = await db.scalar(select(func.count(AIAnalysis.id)))

    return DashboardStats(
        total_accounts=accounts_count or 0,
        total_emails=emails_count or 0,
        total_unread=unread_count or 0,
        sync_active=(syncing or 0) > 0,
        ai_analyses_count=ai_count or 0,
    )


@router.get("/settings", response_model=list[SettingResponse])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    result = await db.execute(select(Setting).order_by(Setting.key))
    settings_list = result.scalars().all()
    response = []
    for s in settings_list:
        val = s.value
        if s.is_secret and val:
            try:
                decrypted = decrypt_value(val)
                # Mask the value for display
                if len(decrypted) > 8:
                    val = decrypted[:4] + "****" + decrypted[-4:]
                else:
                    val = "****"
            except Exception:
                val = "****"
        response.append(SettingResponse(
            id=s.id,
            key=s.key,
            value=val,
            is_secret=s.is_secret,
            description=s.description,
            updated_at=s.updated_at,
        ))
    return response


@router.put("/settings", response_model=SettingResponse)
async def update_setting(
    data: SettingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    result = await db.execute(select(Setting).where(Setting.key == data.key))
    setting = result.scalar_one_or_none()

    stored_value = data.value
    if data.is_secret and stored_value:
        stored_value = encrypt_value(stored_value)

    if setting:
        setting.value = stored_value
        setting.is_secret = data.is_secret
        if data.description:
            setting.description = data.description
    else:
        setting = Setting(
            key=data.key,
            value=stored_value,
            is_secret=data.is_secret,
            description=data.description,
        )
        db.add(setting)

    await db.commit()
    await db.refresh(setting)

    display_value = data.value
    if data.is_secret and display_value and len(display_value) > 8:
        display_value = display_value[:4] + "****" + display_value[-4:]

    return SettingResponse(
        id=setting.id,
        key=setting.key,
        value=display_value,
        is_secret=setting.is_secret,
        description=setting.description,
        updated_at=setting.updated_at,
    )


@router.delete("/settings/{key}")
async def delete_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    await db.delete(setting)
    await db.commit()
    return {"message": f"Setting '{key}' deleted"}


@router.get("/accounts", response_model=list[GoogleAccountResponse])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(GoogleAccount)
        .options(
            selectinload(GoogleAccount.sync_status),
            selectinload(GoogleAccount.calendar_sync_status),
        )
        .order_by(GoogleAccount.email)
    )
    accounts = result.scalars().all()
    response = []
    for acct in accounts:
        sync = None
        if acct.sync_status:
            sync = SyncStatusResponse.model_validate(acct.sync_status)
        calendar_sync = None
        if acct.calendar_sync_status:
            calendar_sync = CalendarSyncHealthResponse.model_validate(acct.calendar_sync_status)
        try:
            scopes = json.loads(acct.scopes or "[]")
        except (json.JSONDecodeError, TypeError):
            scopes = []
        response.append(GoogleAccountResponse(
            id=acct.id,
            email=acct.email,
            display_name=acct.display_name,
            is_active=acct.is_active,
            created_at=acct.created_at,
            sync_status=sync,
            calendar_sync_status=calendar_sync,
            has_calendar_scope="https://www.googleapis.com/auth/calendar.readonly" in scopes,
        ))
    return response


@router.delete("/accounts/{account_id}")
async def remove_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(account)
    await db.commit()
    return {"message": f"Account '{account.email}' removed"}


@router.get("/stats")
async def get_stats(
    days: int = Query(30, ge=7, le=365),
    account_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get detailed email statistics for charts and dashboards."""
    # Get user's account IDs
    acct_result = await db.execute(
        select(GoogleAccount.id).where(GoogleAccount.user_id == user.id)
    )
    account_ids = [r[0] for r in acct_result.all()]
    if account_id is not None:
        if account_id not in account_ids:
            raise HTTPException(status_code=404, detail="Account not found")
        account_ids = [account_id]

    if not account_ids:
        return {
            "volume_by_day": [],
            "top_senders": [],
            "read_vs_unread": {"read": 0, "unread": 0},
            "category_distribution": [],
            "emails_per_day_avg": 0,
            "total_emails": 0,
            "total_unread": 0,
            "total_starred": 0,
            "total_with_attachments": 0,
        }

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)
    # Exclude malformed future message dates while allowing a small timezone
    # tolerance for messages received near midnight.
    period_end = now + timedelta(days=1)
    account_filter = Email.account_id.in_(account_ids)
    reporting_filter = (
        account_filter,
        Email.date >= period_start,
        Email.date < period_end,
    )

    # Total counts
    total_emails = await db.scalar(
        select(func.count(Email.id)).where(*reporting_filter)
    ) or 0
    total_unread = await db.scalar(
        select(func.count(Email.id)).where(*reporting_filter, Email.is_read == False)
    ) or 0
    total_starred = await db.scalar(
        select(func.count(Email.id)).where(*reporting_filter, Email.is_starred == True)
    ) or 0
    total_attachments = await db.scalar(
        select(func.count(Email.id)).where(*reporting_filter, Email.has_attachments == True)
    ) or 0

    # Volume by day for the requested reporting window.
    volume_result = await db.execute(
        select(
            cast(Email.date, Date).label("day"),
            func.count(Email.id).label("count"),
        )
        .where(*reporting_filter)
        .group_by("day")
        .order_by("day")
    )
    volume_by_day = [
        {"date": str(row.day), "count": row.count}
        for row in volume_result.all()
    ]

    # Average emails per day
    emails_per_day_avg = 0
    if volume_by_day:
        total_in_period = sum(d["count"] for d in volume_by_day)
        emails_per_day_avg = round(total_in_period / days, 1)

    # Top 10 senders
    senders_result = await db.execute(
        select(
            func.lower(func.trim(Email.from_address)).label("address"),
            func.max(Email.from_name).label("name"),
            func.count(Email.id).label("count"),
        )
        .where(
            *reporting_filter,
            Email.from_address.isnot(None),
            func.trim(Email.from_address) != "",
        )
        .group_by(func.lower(func.trim(Email.from_address)))
        .order_by(func.count(Email.id).desc())
        .limit(10)
    )
    top_senders = [
        {"address": row.address, "name": row.name or row.address, "count": row.count}
        for row in senders_result.all()
    ]

    # Read vs unread
    read_count = total_emails - total_unread

    # AI category distribution
    cat_result = await db.execute(
        select(
            AIAnalysis.category,
            func.count(AIAnalysis.id).label("count"),
        )
        .join(Email, Email.id == AIAnalysis.email_id)
        .where(
            Email.account_id.in_(account_ids),
            Email.date >= period_start,
            Email.date < period_end,
        )
        .group_by(AIAnalysis.category)
        .order_by(func.count(AIAnalysis.id).desc())
    )
    category_distribution = [
        {"category": row.category, "count": row.count}
        for row in cat_result.all()
    ]

    return {
        "volume_by_day": volume_by_day,
        "top_senders": top_senders,
        "read_vs_unread": {"read": read_count, "unread": total_unread},
        "category_distribution": category_distribution,
        "emails_per_day_avg": emails_per_day_avg,
        "total_emails": total_emails,
        "total_unread": total_unread,
        "total_starred": total_starred,
        "total_with_attachments": total_attachments,
        "filters": {
            "days": days,
            "account_id": account_id,
            "start": period_start.date().isoformat(),
            "end": now.date().isoformat(),
        },
    }
