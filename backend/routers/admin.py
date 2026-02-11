from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from backend.database import get_db
from backend.models.user import User
from backend.models.settings import Setting
from backend.models.account import GoogleAccount, SyncStatus
from backend.models.email import Email
from backend.models.ai import AIAnalysis
from backend.schemas.admin import (
    SettingResponse, SettingUpdate, GoogleAccountResponse,
    SyncStatusResponse, DashboardStats,
)
from backend.routers.auth import require_admin
from backend.utils.security import encrypt_value, decrypt_value

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
    result = await db.execute(
        select(GoogleAccount).order_by(GoogleAccount.email)
    )
    accounts = result.scalars().all()
    response = []
    for acct in accounts:
        sync = None
        if acct.sync_status:
            sync = SyncStatusResponse.model_validate(acct.sync_status)
        response.append(GoogleAccountResponse(
            id=acct.id,
            email=acct.email,
            display_name=acct.display_name,
            is_active=acct.is_active,
            created_at=acct.created_at,
            sync_status=sync,
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
