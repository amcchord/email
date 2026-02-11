from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.models.account import GoogleAccount, SyncStatus
from backend.schemas.admin import GoogleAccountResponse, SyncStatusResponse, GoogleOAuthStart
from backend.routers.auth import get_current_user
from backend.utils.security import encrypt_value
from backend.config import get_settings
import json

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
settings = get_settings()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


@router.get("/", response_model=list[GoogleAccountResponse])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.user_id == user.id).order_by(GoogleAccount.email)
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


@router.get("/oauth/start", response_model=GoogleOAuthStart)
async def start_oauth(
    user: User = Depends(get_current_user),
):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in admin settings.",
        )

    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = settings.google_redirect_uri

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return GoogleOAuthStart(auth_url=auth_url)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = settings.google_redirect_uri
    flow.fetch_token(code=code)

    credentials = flow.credentials

    # Get user info
    service = build("oauth2", "v2", credentials=credentials)
    user_info = service.userinfo().get().execute()
    email = user_info.get("email")
    name = user_info.get("name", email)

    # Find or create user (for now, associate with first admin user)
    result = await db.execute(select(User).where(User.is_admin == True))
    admin_user = result.scalar_one_or_none()
    if not admin_user:
        raise HTTPException(status_code=500, detail="No admin user found")

    # Check if account already exists
    result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.email == email)
    )
    account = result.scalar_one_or_none()

    if account:
        account.encrypted_access_token = encrypt_value(credentials.token)
        account.encrypted_refresh_token = encrypt_value(credentials.refresh_token or "")
        account.token_expiry = credentials.expiry
        account.scopes = json.dumps(SCOPES)
        account.is_active = True
    else:
        account = GoogleAccount(
            user_id=admin_user.id,
            email=email,
            display_name=name,
            encrypted_access_token=encrypt_value(credentials.token),
            encrypted_refresh_token=encrypt_value(credentials.refresh_token or ""),
            token_expiry=credentials.expiry,
            scopes=json.dumps(SCOPES),
            is_active=True,
        )
        db.add(account)
        await db.flush()

        # Create sync status
        sync_status = SyncStatus(account_id=account.id)
        db.add(sync_status)

    await db.commit()

    # Redirect to frontend accounts page
    return RedirectResponse(url="/?page=admin&tab=accounts&connected=true")


@router.post("/{account_id}/sync")
async def trigger_sync(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Queue sync task
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
