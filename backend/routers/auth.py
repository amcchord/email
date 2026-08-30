import os
import secrets
import time
import threading
# Google often returns additional scopes (like openid); allow this without error
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
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
from backend.services.ai_models import (
    is_model_allowed_for_preference,
    is_valid_effort,
    resolve_effort,
)
from backend.utils.security import (
    verify_password, hash_password, create_access_token,
    create_refresh_token, decode_token, encrypt_value, decrypt_value,
)
from backend.services.google_oauth import build_google_flow, new_code_verifier
from backend.config import get_settings
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()
limiter = Limiter(key_func=get_remote_address)

LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


GOOGLE_LOGIN_STATE_COOKIE = "oauth_state"
GOOGLE_LOGIN_VERIFIER_COOKIE = "oauth_code_verifier"


def _google_login_redirect(error: str) -> RedirectResponse:
    response = RedirectResponse(url=f"/?login_error={error}", status_code=303)
    response.delete_cookie(GOOGLE_LOGIN_STATE_COOKIE)
    response.delete_cookie(GOOGLE_LOGIN_VERIFIER_COOKIE)
    return response


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
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    # Check admin override
    if body.username == settings.admin_username:
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

        if not verify_password(body.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
    else:
        result = await db.execute(
            select(User).where(
                (User.username == body.username) | (User.email == body.username)
            )
        )
        user = result.scalar_one_or_none()
        if not user or not user.hashed_password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        if not verify_password(body.password, user.hashed_password):
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
async def google_login_start(response: Response, db: AsyncSession = Depends(get_db)):
    """Start Google OAuth login flow."""
    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)

    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth not configured. Go to Settings > API Keys to add your Google Client ID and Secret.")

    redirect_uri = settings.google_redirect_uri
    code_verifier = new_code_verifier()
    flow = build_google_flow(
        client_id,
        client_secret,
        redirect_uri,
        LOGIN_SCOPES,
        code_verifier=code_verifier,
    )

    csrf_state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
        state=csrf_state,
    )

    is_https = "https" in settings.allowed_origins
    response = JSONResponse(content={"auth_url": auth_url})
    response.set_cookie(
        key=GOOGLE_LOGIN_STATE_COOKIE,
        value=csrf_state,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=600,
    )
    response.set_cookie(
        key=GOOGLE_LOGIN_VERIFIER_COOKIE,
        value=encrypt_value(code_verifier),
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=600,
    )
    return response


@router.get("/google/callback")
async def google_login_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth login callback. Creates or finds user, issues JWT."""
    cookie_state = request.cookies.get(GOOGLE_LOGIN_STATE_COOKIE, "") if request else ""
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _google_login_redirect("invalid_state")

    if error or not code:
        return _google_login_redirect(
            "access_denied" if error == "access_denied" else "authorization_failed"
        )

    encrypted_verifier = request.cookies.get(GOOGLE_LOGIN_VERIFIER_COOKIE, "") if request else ""
    try:
        code_verifier = decrypt_value(encrypted_verifier)
    except Exception:
        code_verifier = ""
    if not code_verifier:
        return _google_login_redirect("invalid_state")

    from backend.services.credentials import get_google_credentials
    client_id, client_secret = await get_google_credentials(db)

    if not client_id or not client_secret:
        return _google_login_redirect("configuration_error")

    import asyncio
    from googleapiclient.discovery import build

    loop = asyncio.get_running_loop()
    redirect_uri = settings.google_redirect_uri
    flow = build_google_flow(
        client_id,
        client_secret,
        redirect_uri,
        LOGIN_SCOPES,
        code_verifier=code_verifier,
    )
    try:
        await loop.run_in_executor(None, lambda: flow.fetch_token(code=code))
    except Exception:
        return _google_login_redirect("token_exchange_failed")
    credentials = flow.credentials

    # Get user info from Google (synchronous API, run in thread)
    def _get_user_info():
        service = build("oauth2", "v2", credentials=credentials)
        return service.userinfo().get().execute()

    try:
        user_info = await loop.run_in_executor(None, _get_user_info)
    except Exception:
        return _google_login_redirect("profile_lookup_failed")
    email = user_info.get("email")
    name = user_info.get("name", email)
    avatar = user_info.get("picture")

    if not email:
        return _google_login_redirect("no_email")

    # Check allowlist
    is_allowed = await _check_allowed(email, db)
    if not is_allowed:
        return _google_login_redirect("not_allowed")

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
    redirect = RedirectResponse(url="/", status_code=303)
    _set_auth_cookies(redirect, access_token, refresh_token)
    redirect.delete_cookie(GOOGLE_LOGIN_STATE_COOKIE)
    redirect.delete_cookie(GOOGLE_LOGIN_VERIFIER_COOKIE)
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

def _resolve_model_pref(prefs: dict, key: str) -> str:
    """Return the user's preference for *key*, falling back to the default
    if the stored value is missing or refers to a retired model."""
    val = prefs.get(key)
    if val and is_model_allowed_for_preference(val, key):
        return val
    return DEFAULT_AI_PREFERENCES[key]


def _resolve_effort_pref(prefs: dict, model_key: str, model: str) -> str:
    effort_key = model_key.removesuffix("_model") + "_effort"
    stored_model = prefs.get(model_key)
    if stored_model and not is_model_allowed_for_preference(stored_model, model_key):
        return DEFAULT_AI_PREFERENCES[effort_key]
    return resolve_effort(model, prefs.get(effort_key) or DEFAULT_AI_PREFERENCES[effort_key])


def _build_ai_preferences_response(prefs: dict) -> AIPreferencesResponse:
    values: dict[str, str] = {}
    for model_key in (
        "chat_plan_model",
        "chat_execute_model",
        "chat_verify_model",
        "agentic_model",
        "custom_prompt_model",
        "unsubscribe_model",
    ):
        model = _resolve_model_pref(prefs, model_key)
        effort_key = model_key.removesuffix("_model") + "_effort"
        values[model_key] = model
        values[effort_key] = _resolve_effort_pref(prefs, model_key, model)
    return AIPreferencesResponse(**values)


@router.get("/ai-preferences", response_model=AIPreferencesResponse)
async def get_ai_preferences(user: User = Depends(get_current_user)):
    """Return the current user's AI model preferences with defaults filled in."""
    return _build_ai_preferences_response(user.ai_preferences or {})


@router.put("/ai-preferences", response_model=AIPreferencesResponse)
async def update_ai_preferences(
    body: AIPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the current user's AI model preferences."""
    current = dict(user.ai_preferences or {})
    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        current[key] = value

    # Validate partial updates against the effective model/effort pair too.
    # The Pydantic model can only validate fields submitted together; this
    # catches an effort-only update that conflicts with the stored model.
    for model_key in (
        "chat_plan_model",
        "chat_execute_model",
        "chat_verify_model",
        "agentic_model",
        "custom_prompt_model",
        "unsubscribe_model",
    ):
        model = _resolve_model_pref(current, model_key)
        effort_key = model_key.removesuffix("_model") + "_effort"
        if model_key in updates and effort_key not in updates:
            current[effort_key] = resolve_effort(model, current.get(effort_key))
        effort = current.get(effort_key)
        if effort and not is_valid_effort(model, effort):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{effort} effort is not supported by {model}",
            )
    user.ai_preferences = current
    # Force SQLAlchemy to detect JSONB mutation
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, "ai_preferences")
    await db.commit()
    await db.refresh(user)

    return _build_ai_preferences_response(user.ai_preferences or {})


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


# ── API Tokens (read-only public API, /api/v1/...) ──────────────────

@router.get("/api-tokens")
async def list_api_tokens(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the current user's API tokens (no secrets returned)."""
    from backend.models.api_token import ApiToken
    from backend.schemas.api_token import ApiTokenSummary

    result = await db.execute(
        select(ApiToken)
        .where(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return [ApiTokenSummary.model_validate(t) for t in tokens]


@router.post("/api-tokens")
async def create_api_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mint a new API token. Returns the raw token EXACTLY ONCE."""
    from backend.models.api_token import ApiToken
    from backend.schemas.api_token import ApiTokenCreateRequest, ApiTokenCreatedResponse
    from backend.utils.api_auth import generate_api_token

    body = await request.json()
    payload = ApiTokenCreateRequest.model_validate(body)

    raw, token_hash, prefix = generate_api_token()

    token = ApiToken(
        user_id=user.id,
        name=payload.name.strip(),
        token_hash=token_hash,
        prefix=prefix,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    return ApiTokenCreatedResponse(
        id=token.id,
        name=token.name,
        prefix=token.prefix,
        token=raw,
        created_at=token.created_at,
    )


@router.delete("/api-tokens/{token_id}")
async def revoke_api_token(
    token_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Soft-revoke an API token by setting `revoked_at`."""
    from backend.models.api_token import ApiToken
    from datetime import datetime, timezone

    result = await db.execute(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.user_id == user.id,
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    if token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    return {"message": "Token revoked"}


# ── Device Code Auth Flow (for TUI / CLI clients) ───────────────────

_device_codes: dict[str, dict] = {}
_device_codes_lock = threading.Lock()

DEVICE_CODE_EXPIRY = 600
DEVICE_CODE_INTERVAL = 5


def _generate_user_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part1 = "".join(secrets.choice(chars) for _ in range(4))
    part2 = "".join(secrets.choice(chars) for _ in range(4))
    return f"{part1}-{part2}"


def _clean_expired_codes():
    now = time.time()
    with _device_codes_lock:
        expired = [k for k, v in _device_codes.items() if now > v["expires_at"]]
        for k in expired:
            del _device_codes[k]


def _get_public_base_url(request: Request) -> str:
    """Get the public-facing base URL for device auth verification links.

    Derives from allowed_origins config (which has the real public URL like
    https://email.mcchord.net), falling back to X-Forwarded headers
    or request.base_url as last resort.
    """
    origins = settings.allowed_origins
    if origins:
        first_origin = origins.split(",")[0].strip()
        if first_origin and first_origin.startswith("http"):
            return first_origin.rstrip("/")

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

    return str(request.base_url).rstrip("/")


@router.post("/device/start")
async def device_start(request: Request):
    """Start the device code authorization flow.

    Returns a device_code (for polling), user_code (for display),
    and verification_url (where the user should go to authorize).
    """
    _clean_expired_codes()

    device_code = secrets.token_urlsafe(32)
    user_code = _generate_user_code()

    origin = _get_public_base_url(request)
    verification_url = f"{origin}/auth/device?code={user_code}"

    now = time.time()
    with _device_codes_lock:
        _device_codes[device_code] = {
            "user_code": user_code,
            "verification_url": verification_url,
            "status": "pending",
            "created_at": now,
            "expires_at": now + DEVICE_CODE_EXPIRY,
            "access_token": None,
            "refresh_token": None,
            "user": None,
        }

    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_url": verification_url,
        "expires_in": DEVICE_CODE_EXPIRY,
        "interval": DEVICE_CODE_INTERVAL,
    }


@router.get("/device/status/{device_code}")
async def device_status(device_code: str):
    """Poll for the status of a device code authorization.

    Returns status: pending, authorized, or expired.
    When authorized, includes access_token, refresh_token, and user.
    """
    _clean_expired_codes()

    with _device_codes_lock:
        entry = _device_codes.get(device_code)

    if not entry:
        return {"status": "expired"}

    if time.time() > entry["expires_at"]:
        with _device_codes_lock:
            _device_codes.pop(device_code, None)
        return {"status": "expired"}

    if entry["status"] == "authorized":
        with _device_codes_lock:
            _device_codes.pop(device_code, None)
        return {
            "status": "authorized",
            "access_token": entry["access_token"],
            "refresh_token": entry["refresh_token"],
            "user": entry["user"],
        }

    return {"status": "pending"}


@router.post("/device/authorize")
async def device_authorize(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Authorize a device code (called from the web UI by an authenticated user).

    Expects JSON body: {"user_code": "XXXX-XXXX"}
    """
    body = await request.json()
    user_code = body.get("user_code", "").strip().upper()
    if not user_code:
        raise HTTPException(status_code=400, detail="user_code is required")

    with _device_codes_lock:
        target = None
        for dc, entry in _device_codes.items():
            if entry["user_code"] == user_code and entry["status"] == "pending":
                target = dc
                break

    if not target:
        raise HTTPException(status_code=404, detail="Invalid or expired code")

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    with _device_codes_lock:
        if target in _device_codes:
            _device_codes[target]["status"] = "authorized"
            _device_codes[target]["access_token"] = access_token
            _device_codes[target]["refresh_token"] = refresh_token
            _device_codes[target]["user"] = {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "is_admin": user.is_admin,
            }

    return {"message": "Device authorized"}
