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
    AboutMeResponse, AboutMeUpdate,
    KeyboardShortcutsResponse, KeyboardShortcutsUpdate,
    UIPreferencesResponse, UIPreferencesUpdate,
    DEFAULT_AI_PREFERENCES, DEFAULT_UI_PREFERENCES,
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
        custom_prompt_model=prefs.get("custom_prompt_model", DEFAULT_AI_PREFERENCES["custom_prompt_model"]),
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
    if body.custom_prompt_model is not None:
        current["custom_prompt_model"] = body.custom_prompt_model
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
        custom_prompt_model=prefs.get("custom_prompt_model", DEFAULT_AI_PREFERENCES["custom_prompt_model"]),
    )


# ── About Me ────────────────────────────────────────────────────────

@router.get("/about-me", response_model=AboutMeResponse)
async def get_about_me(user: User = Depends(get_current_user)):
    """Return the current user's about-me text."""
    return AboutMeResponse(about_me=user.about_me)


@router.put("/about-me", response_model=AboutMeResponse)
async def update_about_me(
    body: AboutMeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the current user's about-me text."""
    user.about_me = body.about_me
    await db.commit()
    await db.refresh(user)
    return AboutMeResponse(about_me=user.about_me)


# ── Keyboard Shortcuts ──────────────────────────────────────────────

@router.get("/keyboard-shortcuts", response_model=KeyboardShortcutsResponse)
async def get_keyboard_shortcuts(user: User = Depends(get_current_user)):
    """Return the current user's keyboard shortcut overrides."""
    overrides = user.keyboard_shortcuts or {}
    return KeyboardShortcutsResponse(shortcuts=overrides)


@router.put("/keyboard-shortcuts", response_model=KeyboardShortcutsResponse)
async def update_keyboard_shortcuts(
    body: KeyboardShortcutsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the current user's keyboard shortcut overrides (merge)."""
    current = user.keyboard_shortcuts or {}
    for action_id, key_combo in body.shortcuts.items():
        if key_combo == "":
            current.pop(action_id, None)
        else:
            current[action_id] = key_combo
    user.keyboard_shortcuts = current
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, "keyboard_shortcuts")
    await db.commit()
    await db.refresh(user)
    return KeyboardShortcutsResponse(shortcuts=user.keyboard_shortcuts or {})


# ── UI Preferences ──────────────────────────────────────────────────

@router.get("/ui-preferences", response_model=UIPreferencesResponse)
async def get_ui_preferences(user: User = Depends(get_current_user)):
    """Return the current user's UI preferences with defaults filled in."""
    prefs = user.ui_preferences or {}
    return UIPreferencesResponse(
        thread_order=prefs.get("thread_order", DEFAULT_UI_PREFERENCES["thread_order"]),
        theme=prefs.get("theme", DEFAULT_UI_PREFERENCES["theme"]),
        color_scheme=prefs.get("color_scheme", DEFAULT_UI_PREFERENCES["color_scheme"]),
    )


@router.put("/ui-preferences", response_model=UIPreferencesResponse)
async def update_ui_preferences(
    body: UIPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the current user's UI preferences."""
    current = user.ui_preferences or {}
    if body.thread_order is not None:
        current["thread_order"] = body.thread_order
    if body.theme is not None:
        current["theme"] = body.theme
    if body.color_scheme is not None:
        current["color_scheme"] = body.color_scheme
    user.ui_preferences = current
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, "ui_preferences")
    await db.commit()
    await db.refresh(user)

    prefs = user.ui_preferences or {}
    return UIPreferencesResponse(
        thread_order=prefs.get("thread_order", DEFAULT_UI_PREFERENCES["thread_order"]),
        theme=prefs.get("theme", DEFAULT_UI_PREFERENCES["theme"]),
        color_scheme=prefs.get("color_scheme", DEFAULT_UI_PREFERENCES["color_scheme"]),
    )


# ── TUI / CLI Password ────────────────────────────────────────────

@router.put("/tui-password")
async def set_tui_password(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Set a password for TUI/SSH access.

    Google OAuth users don't have a password by default. This lets them
    set one so they can log into the TUI via SSH using their email + this password.
    """
    password = body.get("password", "")
    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters",
        )
    user.hashed_password = hash_password(password)
    await db.commit()
    return {"status": "ok", "message": "TUI password set. Log in with your email and this password."}


# ── Device-Code Auth Flow (for TUI) ─────────────────────────────

import secrets
import time as _time

# In-memory store: { device_code: { user_code, created_at, status, tokens } }
# status: "pending" | "authorized" | "expired"
_device_codes: dict[str, dict] = {}
_DEVICE_CODE_TTL = 600  # 10 minutes


def _clean_expired_codes():
    """Remove expired device codes from the store."""
    now = _time.time()
    expired = [k for k, v in _device_codes.items() if now - v["created_at"] > _DEVICE_CODE_TTL]
    for k in expired:
        del _device_codes[k]


@router.post("/device/start")
async def device_start():
    """Start a device-code auth flow.

    Returns a device_code (secret, for polling), user_code (short, human-readable),
    and a verification URL. The TUI shows the user_code and URL, then polls
    /device/status with the device_code until authorized.
    """
    _clean_expired_codes()

    device_code = secrets.token_urlsafe(32)
    # Generate a short human-friendly code: XXXX-XXXX
    raw = secrets.token_hex(4).upper()
    user_code = f"{raw[:4]}-{raw[4:]}"

    allowed_origins = settings.allowed_origins or "https://email.mcchord.net"
    base_url = allowed_origins.split(",")[0].strip()
    verification_url = f"{base_url}/auth/device?code={user_code}"

    _device_codes[device_code] = {
        "user_code": user_code,
        "created_at": _time.time(),
        "status": "pending",
        "tokens": None,
    }

    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_url": verification_url,
        "expires_in": _DEVICE_CODE_TTL,
        "interval": 5,
    }


@router.get("/device/status")
async def device_status(device_code: str):
    """Poll for device-code authorization status.

    Returns:
      - {"status": "pending"} while waiting
      - {"status": "authorized", "access_token": ..., "refresh_token": ..., "user": ...} on success
      - {"status": "expired"} if timed out
    """
    _clean_expired_codes()

    entry = _device_codes.get(device_code)
    if not entry:
        return {"status": "expired"}

    if _time.time() - entry["created_at"] > _DEVICE_CODE_TTL:
        del _device_codes[device_code]
        return {"status": "expired"}

    if entry["status"] == "authorized" and entry["tokens"]:
        tokens = entry["tokens"]
        del _device_codes[device_code]
        return {
            "status": "authorized",
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "user": tokens.get("user", {}),
        }

    return {"status": "pending"}


@router.post("/device/authorize")
async def device_authorize(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Authorize a device code from the web app.

    The logged-in user submits the user_code they see on the TUI.
    This generates tokens for that user and marks the device code as authorized.
    """
    user_code = (body.get("user_code") or "").strip().upper()
    if not user_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_code is required",
        )

    # Find the matching device code entry
    matched_device_code = None
    for dc, entry in _device_codes.items():
        if entry["user_code"] == user_code and entry["status"] == "pending":
            if _time.time() - entry["created_at"] <= _DEVICE_CODE_TTL:
                matched_device_code = dc
                break

    if not matched_device_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired code",
        )

    # Generate tokens for this user
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    _device_codes[matched_device_code]["status"] = "authorized"
    _device_codes[matched_device_code]["tokens"] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "display_name": user.display_name,
            "is_admin": user.is_admin,
        },
    }

    return {"status": "ok", "message": f"TUI session authorized for {user.email}"}
