import os
# Google often returns additional scopes (like openid); allow this without error
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.models.settings import Setting
from backend.schemas.auth import (
    LoginRequest, TokenResponse, UserResponse, RefreshRequest,
    AIPreferencesResponse, AIPreferencesUpdate,
    DEFAULT_AI_PREFERENCES,
)
from backend.utils.security import (
    verify_password, hash_password, create_access_token,
    create_refresh_token, decode_token,
)
from backend.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _build_google_flow(client_id: str, client_secret: str, redirect_uri: str, scopes: list):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=scopes,
        redirect_uri=redirect_uri,
    )


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    is_https = "https" in settings.allowed_origins
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=settings.access_token_expire_minutes * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=settings.refresh_token_expire_days * 86400,
    )


async def _check_allowed(email: str, db: AsyncSession) -> bool:
    """Check if an email is in the allowed accounts list. Returns True if allowed."""
    result = await db.execute(
        select(Setting).where(Setting.key == "allowed_accounts")
    )
    allowed_setting = result.scalar_one_or_none()
    if not allowed_setting or not allowed_setting.value:
        # No allowlist configured = allow everyone
        return True

    allowed_list = [
        entry.strip().lower()
        for entry in allowed_setting.value.split(",")
        if entry.strip()
    ]
    email_lower = email.lower()
    email_domain = email_lower.split("@")[-1] if "@" in email_lower else ""

    for entry in allowed_list:
        if entry.startswith("@"):
            if email_domain == entry[1:]:
                return True
        else:
            if email_lower == entry:
                return True
    return False


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ── Admin password login (fallback) ─────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    # Check admin override
    if request.username == settings.admin_username:
        result = await db.execute(
            select(User).where(User.username == settings.admin_username)
        )
        user = result.scalar_one_or_none()

        if not user:
            # Create admin user on first login
            user = User(
                username=settings.admin_username,
                display_name="Admin",
                is_admin=True,
                hashed_password=hash_password(settings.admin_password),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        if not verify_password(request.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
    else:
        result = await db.execute(
            select(User).where(
                (User.username == request.username) | (User.email == request.username)
            )
        )
        user = result.scalar_one_or_none()
        if not user or not user.hashed_password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        if not verify_password(request.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    _set_auth_cookies(response, access_token, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


# ── Google OAuth login ──────────────────────────────────────────────

@router.get("/google/login")
async def google_login_start(db: AsyncSession = Depends(get_db)):
    """Start Google OAuth login flow."""
    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)

    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth not configured. Go to Settings > API Keys to add your Google Client ID and Secret.")

    redirect_uri = settings.google_redirect_uri
    flow = _build_google_flow(client_id, client_secret, redirect_uri, LOGIN_SCOPES)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
    )
    return {"auth_url": auth_url}


@router.get("/google/callback")
async def google_login_callback(
    code: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth login callback. Creates or finds user, issues JWT."""
    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)

    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    import asyncio
    from googleapiclient.discovery import build

    loop = asyncio.get_event_loop()
    redirect_uri = settings.google_redirect_uri
    flow = _build_google_flow(client_id, client_secret, redirect_uri, LOGIN_SCOPES)
    await loop.run_in_executor(None, lambda: flow.fetch_token(code=code))
    credentials = flow.credentials

    # Get user info from Google (synchronous API, run in thread)
    def _get_user_info():
        service = build("oauth2", "v2", credentials=credentials)
        return service.userinfo().get().execute()

    user_info = await loop.run_in_executor(None, _get_user_info)
    email = user_info.get("email")
    name = user_info.get("name", email)
    avatar = user_info.get("picture")

    if not email:
        return RedirectResponse(url="/?login_error=no_email")

    # Check allowlist
    is_allowed = await _check_allowed(email, db)
    if not is_allowed:
        return RedirectResponse(url="/?login_error=not_allowed")

    # Find or create user by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        # Update profile info from Google
        user.display_name = name
        user.avatar_url = avatar
    else:
        # First time login -- create a new user
        user = User(
            email=email,
            display_name=name,
            avatar_url=avatar,
            is_admin=False,
            is_active=True,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    # Issue tokens
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    # Set cookies and redirect to app
    redirect = RedirectResponse(url="/", status_code=302)
    _set_auth_cookies(redirect, access_token, refresh_token)
    return redirect


# ── Token refresh / logout / me ─────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request_obj: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # Read refresh token from cookie first, fall back to request body
    token = request_obj.cookies.get("refresh_token")
    if not token:
        # Try to parse from JSON body
        try:
            body_json = await request_obj.json()
            if isinstance(body_json, dict):
                token = body_json.get("refresh_token")
        except Exception:
            pass
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token provided")

    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token({"sub": str(user.id)})
    new_refresh = create_refresh_token({"sub": str(user.id)})

    _set_auth_cookies(response, access_token, new_refresh)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return UserResponse.model_validate(user)


# ── AI Preferences ──────────────────────────────────────────────────

@router.get("/ai-preferences", response_model=AIPreferencesResponse)
async def get_ai_preferences(user: User = Depends(get_current_user)):
    """Return the current user's AI model preferences with defaults filled in."""
    prefs = user.ai_preferences or {}
    return AIPreferencesResponse(
        chat_plan_model=prefs.get("chat_plan_model", DEFAULT_AI_PREFERENCES["chat_plan_model"]),
        chat_execute_model=prefs.get("chat_execute_model", DEFAULT_AI_PREFERENCES["chat_execute_model"]),
        chat_verify_model=prefs.get("chat_verify_model", DEFAULT_AI_PREFERENCES["chat_verify_model"]),
        agentic_model=prefs.get("agentic_model", DEFAULT_AI_PREFERENCES["agentic_model"]),
    )


@router.put("/ai-preferences", response_model=AIPreferencesResponse)
async def update_ai_preferences(
    body: AIPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the current user's AI model preferences."""
    current = user.ai_preferences or {}
    if body.chat_plan_model is not None:
        current["chat_plan_model"] = body.chat_plan_model
    if body.chat_execute_model is not None:
        current["chat_execute_model"] = body.chat_execute_model
    if body.chat_verify_model is not None:
        current["chat_verify_model"] = body.chat_verify_model
    if body.agentic_model is not None:
        current["agentic_model"] = body.agentic_model
    user.ai_preferences = current
    # Force SQLAlchemy to detect JSONB mutation
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, "ai_preferences")
    await db.commit()
    await db.refresh(user)

    prefs = user.ai_preferences or {}
    return AIPreferencesResponse(
        chat_plan_model=prefs.get("chat_plan_model", DEFAULT_AI_PREFERENCES["chat_plan_model"]),
        chat_execute_model=prefs.get("chat_execute_model", DEFAULT_AI_PREFERENCES["chat_execute_model"]),
        chat_verify_model=prefs.get("chat_verify_model", DEFAULT_AI_PREFERENCES["chat_verify_model"]),
        agentic_model=prefs.get("agentic_model", DEFAULT_AI_PREFERENCES["agentic_model"]),
    )
