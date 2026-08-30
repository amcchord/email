from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.models.account import GoogleAccount, SyncStatus
from backend.models.settings import Setting
from backend.schemas.admin import CalendarSyncHealthResponse, GoogleAccountResponse, SyncStatusResponse, GoogleOAuthStart
from backend.schemas.auth import AccountDescriptionUpdate
from backend.routers.auth import get_current_user, _check_allowed
from backend.utils.security import encrypt_value, decrypt_value, sign_oauth_state, verify_oauth_state
from backend.config import get_settings
from backend.services.google_oauth import build_google_flow, new_code_verifier
import json
import logging
import secrets
from urllib.parse import urlencode

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
settings = get_settings()
logger = logging.getLogger(__name__)

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
REQUIRED_GMAIL_SCOPES = {
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
}

# The "connect account" callback is a separate redirect URI from the login callback
CONNECT_REDIRECT_URI_PATH = "/api/accounts/oauth/callback"
ACCOUNT_OAUTH_NONCE_COOKIE = "account_oauth_nonce"


def _get_connect_redirect_uri():
    """Build the connect-account redirect URI from the allowed origin."""
    origin = settings.allowed_origins.split(",")[0].strip().rstrip("/")
    return origin + CONNECT_REDIRECT_URI_PATH


def _account_oauth_state(
    user_id: int,
    code_verifier: str,
    *,
    nonce: str,
    account_id: int | None = None,
    return_page: str = "admin",
) -> str:
    payload = {
        "user_id": user_id,
        "pkce": encrypt_value(code_verifier),
        "nonce": nonce,
        "return_page": "calendar" if return_page == "calendar" else "admin",
    }
    if account_id is not None:
        payload["account_id"] = account_id
    return sign_oauth_state(payload)


def _account_oauth_redirect(
    state_data: dict | None,
    *,
    result: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    return_page = state_data.get("return_page") if state_data else None
    params = {"page": "calendar"} if return_page == "calendar" else {
        "page": "admin",
        "tab": "profile",
    }
    if result:
        params["oauth"] = result
    if error:
        params["oauth_error"] = error
    response = RedirectResponse(url=f"/?{urlencode(params)}", status_code=303)
    response.delete_cookie(ACCOUNT_OAUTH_NONCE_COOKIE)
    return response


def _set_account_oauth_nonce(response: Response, nonce: str) -> None:
    response.set_cookie(
        key=ACCOUNT_OAUTH_NONCE_COOKIE,
        value=nonce,
        httponly=True,
        samesite="lax",
        secure="https" in settings.allowed_origins,
        max_age=600,
    )


def _restore_account_code_verifier(state_data: dict) -> str | None:
    encrypted_verifier = state_data.get("pkce")
    if not encrypted_verifier:
        return None
    try:
        return decrypt_value(encrypted_verifier)
    except Exception:
        return None


def _credential_scopes(credentials) -> list[str]:
    granted = getattr(credentials, "granted_scopes", None)
    scopes = granted if granted is not None else getattr(credentials, "scopes", None)
    return sorted(set(scopes or []))


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
        .options(
            selectinload(GoogleAccount.sync_status),
            selectinload(GoogleAccount.calendar_sync_status),
        )
        .where(GoogleAccount.user_id == user.id)
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
            calendar_sync_status=calendar_sync,
            has_calendar_scope=has_cal,
        ))
    return response


# ── Connect a Gmail account (OAuth) ─────────────────────────────────

@router.get("/oauth/start", response_model=GoogleOAuthStart)
async def start_oauth(
    response: Response,
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

    redirect_uri = _get_connect_redirect_uri()
    code_verifier = new_code_verifier()
    flow = build_google_flow(
        client_id,
        client_secret,
        redirect_uri,
        GMAIL_SCOPES,
        code_verifier=code_verifier,
    )

    nonce = secrets.token_urlsafe(32)
    state = _account_oauth_state(user.id, code_verifier, nonce=nonce)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    _set_account_oauth_nonce(response, nonce)
    return GoogleOAuthStart(auth_url=auth_url)


@router.get("/{account_id}/reauthorize", response_model=GoogleOAuthStart)
async def reauthorize_account(
    account_id: int,
    response: Response,
    return_page: str = Query("admin", pattern="^(admin|calendar)$"),
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

    redirect_uri = _get_connect_redirect_uri()
    code_verifier = new_code_verifier()
    flow = build_google_flow(
        client_id,
        client_secret,
        redirect_uri,
        GMAIL_SCOPES,
        code_verifier=code_verifier,
    )

    nonce = secrets.token_urlsafe(32)
    state = _account_oauth_state(
        user.id,
        code_verifier,
        nonce=nonce,
        account_id=account.id,
        return_page=return_page,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        login_hint=account.email,
    )
    _set_account_oauth_nonce(response, nonce)
    return GoogleOAuthStart(auth_url=auth_url)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback for connecting a Gmail account."""
    state_data = verify_oauth_state(state)
    if not state_data:
        return _account_oauth_redirect(None, error="invalid_state")

    user_id = state_data.get("user_id")
    cookie_nonce = request.cookies.get(ACCOUNT_OAUTH_NONCE_COOKIE, "") if request else ""
    state_nonce = state_data.get("nonce", "")
    if (
        not user_id
        or not cookie_nonce
        or not state_nonce
        or not secrets.compare_digest(cookie_nonce, state_nonce)
    ):
        return _account_oauth_redirect(state_data, error="invalid_state")

    user_result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        return _account_oauth_redirect(state_data, error="session_expired")

    if error or not code:
        return _account_oauth_redirect(
            state_data,
            error="access_denied" if error == "access_denied" else "authorization_failed",
        )

    code_verifier = _restore_account_code_verifier(state_data)
    if not code_verifier:
        return _account_oauth_redirect(state_data, error="invalid_state")

    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)
    if not client_id or not client_secret:
        return _account_oauth_redirect(state_data, error="configuration_error")

    from googleapiclient.discovery import build

    redirect_uri = _get_connect_redirect_uri()
    flow = build_google_flow(
        client_id,
        client_secret,
        redirect_uri,
        GMAIL_SCOPES,
        code_verifier=code_verifier,
    )
    import asyncio
    loop = asyncio.get_running_loop()

    try:
        await loop.run_in_executor(None, lambda: flow.fetch_token(code=code))
    except Exception as exc:
        logger.warning(
            "Google account OAuth token exchange failed for user_id=%s: %s",
            user.id,
            type(exc).__name__,
        )
        return _account_oauth_redirect(state_data, error="token_exchange_failed")
    credentials = flow.credentials

    # Get account info (synchronous Google API, run in thread)
    def _get_user_info():
        service = build("oauth2", "v2", credentials=credentials)
        return service.userinfo().get().execute()

    try:
        user_info = await loop.run_in_executor(None, _get_user_info)
    except Exception as exc:
        logger.warning(
            "Google account OAuth profile lookup failed for user_id=%s: %s",
            user.id,
            type(exc).__name__,
        )
        return _account_oauth_redirect(state_data, error="profile_lookup_failed")
    email = user_info.get("email")
    name = user_info.get("name", email)

    if not email:
        return _account_oauth_redirect(state_data, error="no_email")

    if not await _check_allowed(email, db):
        return _account_oauth_redirect(state_data, error="not_allowed")

    actual_scopes = _credential_scopes(credentials)
    calendar_scope = "https://www.googleapis.com/auth/calendar.readonly"
    if calendar_scope not in actual_scopes:
        return _account_oauth_redirect(state_data, error="calendar_scope_missing")
    if not REQUIRED_GMAIL_SCOPES.issubset(actual_scopes):
        return _account_oauth_redirect(state_data, error="required_scopes_missing")

    expected_account_id = state_data.get("account_id")
    if expected_account_id is not None:
        result = await db.execute(
            select(GoogleAccount).where(
                GoogleAccount.id == expected_account_id,
                GoogleAccount.user_id == user_id,
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            return _account_oauth_redirect(state_data, error="account_not_found")
        if account.email.casefold() != email.casefold():
            return _account_oauth_redirect(state_data, error="account_mismatch")
    else:
        # Check if this Gmail account is already connected to ANY user.
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.email == email)
        )
        account = result.scalar_one_or_none()

    try:
        if account:
            if account.user_id != user_id:
                # This Gmail is connected to a different user
                return _account_oauth_redirect(state_data, error="account_taken")
            stored_refresh_available = False
            if account.encrypted_refresh_token:
                try:
                    stored_refresh_available = bool(decrypt_value(account.encrypted_refresh_token))
                except Exception:
                    stored_refresh_available = False
            if not credentials.refresh_token and not stored_refresh_available:
                return _account_oauth_redirect(state_data, error="refresh_token_missing")
            # Update tokens for existing connection
            account.encrypted_access_token = encrypt_value(credentials.token)
            # Google may omit refresh_token on a repeat consent callback. Keep the
            # known-good token instead of replacing it with an encrypted empty value.
            if credentials.refresh_token:
                account.encrypted_refresh_token = encrypt_value(credentials.refresh_token)
            account.token_expiry = credentials.expiry
            account.scopes = json.dumps(actual_scopes)
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
            if cal_sync:
                cal_sync.needs_reauth = False
        else:
            if not credentials.refresh_token:
                return _account_oauth_redirect(state_data, error="refresh_token_missing")
            # New connection -- associate with the logged-in user
            account = GoogleAccount(
                user_id=user_id,
                email=email,
                display_name=name,
                encrypted_access_token=encrypt_value(credentials.token),
                encrypted_refresh_token=encrypt_value(credentials.refresh_token),
                token_expiry=credentials.expiry,
                scopes=json.dumps(actual_scopes),
                is_active=True,
            )
            db.add(account)
            await db.flush()

            # Create sync status records only after the account has an id.
            db.add(SyncStatus(account_id=account.id))
            from backend.models.calendar import CalendarSyncStatus
            db.add(CalendarSyncStatus(account_id=account.id))

        await db.commit()
    except Exception as exc:
        try:
            await db.rollback()
        except Exception as rollback_exc:
            logger.error(
                "Google account OAuth rollback failed for user_id=%s error_type=%s",
                user.id,
                type(rollback_exc).__name__,
            )
        logger.error(
            "Google account OAuth persistence failed for user_id=%s error_type=%s",
            user.id,
            type(exc).__name__,
        )
        return _account_oauth_redirect(state_data, error="account_update_failed")

    oauth_result = "reauthorized" if expected_account_id is not None else "connected"
    return _account_oauth_redirect(state_data, result=oauth_result)


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
    account_result = await db.execute(
        select(GoogleAccount.id).where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    if account_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Account not found")

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
