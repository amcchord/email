from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.models.account import GoogleAccount, SyncStatus
from backend.models.settings import Setting
from backend.schemas.admin import GoogleAccountResponse, SyncStatusResponse, GoogleOAuthStart
from backend.schemas.auth import AccountDescriptionUpdate
from backend.routers.auth import get_current_user
from backend.utils.security import encrypt_value, decrypt_value
from backend.config import get_settings
import json
import base64

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
settings = get_settings()

GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# The "connect account" callback is a separate redirect URI from the login callback
CONNECT_REDIRECT_URI_PATH = "/api/accounts/oauth/callback"


def _get_connect_redirect_uri():
    """Build the connect-account redirect URI from the allowed origin."""
    origin = settings.allowed_origins.split(",")[0].strip()
    return origin + CONNECT_REDIRECT_URI_PATH


# ── Allowed accounts ────────────────────────────────────────────────

@router.get("/allowed")
async def get_allowed_accounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Setting).where(Setting.key == "allowed_accounts")
    )
    setting = result.scalar_one_or_none()
    value = setting.value if setting else ""
    return {"allowed_accounts": value}


@router.put("/allowed")
async def set_allowed_accounts(
    data: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    value = data.get("allowed_accounts", "")
    result = await db.execute(
        select(Setting).where(Setting.key == "allowed_accounts")
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = Setting(
            key="allowed_accounts",
            value=value,
            is_secret=False,
            description="Comma-separated list of allowed emails and @domains for Google OAuth",
        )
        db.add(setting)
    await db.commit()
    return {"allowed_accounts": value}


# ── Account listing ─────────────────────────────────────────────────

@router.get("/", response_model=list[GoogleAccountResponse])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(GoogleAccount)
        .options(selectinload(GoogleAccount.sync_status))
        .where(GoogleAccount.user_id == user.id)
        .order_by(GoogleAccount.email)
    )
    accounts = result.scalars().all()
    response = []
    for acct in accounts:
        sync = None
        if acct.sync_status:
            sync = SyncStatusResponse.model_validate(acct.sync_status)
        # Check if the account has calendar.readonly scope
        has_cal = False
        if acct.scopes:
            try:
                scopes = json.loads(acct.scopes)
                has_cal = "https://www.googleapis.com/auth/calendar.readonly" in scopes
            except (json.JSONDecodeError, TypeError):
                pass
        response.append(GoogleAccountResponse(
            id=acct.id,
            email=acct.email,
            display_name=acct.display_name,
            description=acct.description,
            short_label=acct.short_label,
            is_active=acct.is_active,
            created_at=acct.created_at,
            sync_status=sync,
            has_calendar_scope=has_cal,
        ))
    return response


# ── Connect a Gmail account (OAuth) ─────────────────────────────────

@router.get("/oauth/start", response_model=GoogleOAuthStart)
async def start_oauth(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start OAuth flow to connect a Gmail account. Requires being logged in."""
    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Go to Settings > API Keys to add your Google Client ID and Secret.",
        )

    from google_auth_oauthlib.flow import Flow

    redirect_uri = _get_connect_redirect_uri()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )

    # Encode the user ID in the state so the callback knows who is connecting
    state_data = json.dumps({"user_id": user.id})
    state = base64.urlsafe_b64encode(state_data.encode()).decode()

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return GoogleOAuthStart(auth_url=auth_url)


@router.get("/{account_id}/reauthorize", response_model=GoogleOAuthStart)
async def reauthorize_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start OAuth flow to reauthorize an existing account with updated scopes."""
    # Verify the account belongs to this user
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Go to Settings > API Keys to add your Google Client ID and Secret.",
        )

    from google_auth_oauthlib.flow import Flow

    redirect_uri = _get_connect_redirect_uri()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )

    state_data = json.dumps({"user_id": user.id})
    state = base64.urlsafe_b64encode(state_data.encode()).decode()

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        login_hint=account.email,
    )
    return GoogleOAuthStart(auth_url=auth_url)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str,
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback for connecting a Gmail account."""
    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)

    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    # Decode the user ID from state
    user_id = None
    if state:
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state).decode())
            user_id = state_data.get("user_id")
        except Exception:
            pass

    if not user_id:
        return RedirectResponse(url="/?page=admin&tab=accounts&error=invalid_state")

    # Verify the user exists
    result = await db.execute(select(User).where(User.id == user_id))
    owner = result.scalar_one_or_none()
    if not owner:
        return RedirectResponse(url="/?page=admin&tab=accounts&error=invalid_user")

    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    redirect_uri = _get_connect_redirect_uri()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )
    import asyncio
    loop = asyncio.get_event_loop()

    await loop.run_in_executor(None, lambda: flow.fetch_token(code=code))
    credentials = flow.credentials

    # Get account info (synchronous Google API, run in thread)
    def _get_user_info():
        service = build("oauth2", "v2", credentials=credentials)
        return service.userinfo().get().execute()

    user_info = await loop.run_in_executor(None, _get_user_info)
    email = user_info.get("email")
    name = user_info.get("name", email)

    # Check if this Gmail account is already connected to ANY user
    result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.email == email)
    )
    account = result.scalar_one_or_none()

    if account:
        if account.user_id != user_id:
            # This Gmail is connected to a different user
            return RedirectResponse(
                url="/?page=admin&tab=accounts&error=account_taken"
            )
        # Update tokens for existing connection
        account.encrypted_access_token = encrypt_value(credentials.token)
        account.encrypted_refresh_token = encrypt_value(credentials.refresh_token or "")
        account.token_expiry = credentials.expiry
        account.scopes = json.dumps(GMAIL_SCOPES)
        account.is_active = True

        # Clear calendar sync error so it retries with the new token
        from backend.models.calendar import CalendarSyncStatus
        cal_result = await db.execute(
            select(CalendarSyncStatus).where(CalendarSyncStatus.account_id == account.id)
        )
        cal_sync = cal_result.scalar_one_or_none()
        if cal_sync and cal_sync.status == "error":
            cal_sync.status = "idle"
            cal_sync.error_message = None
    else:
        # New connection -- associate with the logged-in user
        account = GoogleAccount(
            user_id=user_id,
            email=email,
            display_name=name,
            encrypted_access_token=encrypt_value(credentials.token),
            encrypted_refresh_token=encrypt_value(credentials.refresh_token or ""),
            token_expiry=credentials.expiry,
            scopes=json.dumps(GMAIL_SCOPES),
            is_active=True,
        )
        db.add(account)
        await db.flush()

        # Create sync status record
        sync_status = SyncStatus(account_id=account.id)
        db.add(sync_status)

        # Create calendar sync status record
        from backend.models.calendar import CalendarSyncStatus
        cal_sync_status = CalendarSyncStatus(account_id=account.id)
        db.add(cal_sync_status)

    await db.commit()

    return RedirectResponse(url="/?page=admin&tab=accounts&connected=true")


# ── Sync management ─────────────────────────────────────────────────

@router.post("/{account_id}/sync")
async def trigger_sync(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # ── Dedup: skip if already syncing or recently synced ────────────
    sync_result = await db.execute(
        select(SyncStatus).where(SyncStatus.account_id == account_id)
    )
    sync = sync_result.scalar_one_or_none()

    if sync and sync.status == "syncing":
        return {"message": f"Sync already in progress for {account.email}"}

    if sync and sync.last_incremental_sync:
        now = datetime.now(timezone.utc)
        since = (now - sync.last_incremental_sync).total_seconds()
        if since < 30:
            return {"message": f"Recently synced {account.email} ({int(since)}s ago), skipping"}

    from backend.workers.tasks import queue_sync
    await queue_sync(account_id)

    return {"message": f"Sync triggered for {account.email}"}


@router.get("/{account_id}/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SyncStatus).where(SyncStatus.account_id == account_id)
    )
    sync = result.scalar_one_or_none()
    if not sync:
        return SyncStatusResponse()
    return SyncStatusResponse.model_validate(sync)


@router.delete("/{account_id}")
async def remove_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a connected Gmail account. Users can remove their own accounts."""
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    email = account.email
    await db.delete(account)
    await db.commit()
    return {"message": f"Account '{email}' removed"}


# ── Account description ─────────────────────────────────────────────

@router.put("/{account_id}/description")
async def update_account_description(
    account_id: int,
    body: AccountDescriptionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the description/purpose for a connected Gmail account."""
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.description = body.description

    # Generate a short 1-2 word label using AI
    if body.description:
        try:
            from backend.services.ai import AIService
            ai = AIService()
            account.short_label = await ai.generate_short_label(body.description)
        except Exception:
            # Fallback: use first two words of description
            words = body.description.split()
            account.short_label = " ".join(words[:2])
    else:
        account.short_label = None

    await db.commit()
    await db.refresh(account)
    return {"description": account.description, "short_label": account.short_label}
