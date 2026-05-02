"""API token authentication for the public read-only `/api/v1/...` API.

Independent of the cookie/JWT-based session auth used by the web UI:
- Reads an opaque token from `Authorization: Bearer <token>` or `X-API-Key`.
- Looks up by `sha256(raw)` against the `api_tokens` table.
- Best-effort updates `last_used_at`.
- Never falls back to cookies.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.api_token import ApiToken
from backend.models.user import User

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "mk_"
TOKEN_RANDOM_BYTES = 32


def generate_api_token() -> tuple[str, str, str]:
    """Mint a new API token.

    Returns (raw_token, token_hash, display_prefix).
    The raw token is what we hand to the user once; only the hash is stored.
    """
    raw = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)
    token_hash = hash_api_token(raw)
    prefix = raw[:12]
    return raw, token_hash, prefix


def hash_api_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        candidate = auth[7:].strip()
        if candidate:
            return candidate
    api_key = request.headers.get("X-API-Key")
    if api_key:
        candidate = api_key.strip()
        if candidate:
            return candidate
    return None


async def get_api_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency: resolve an `ApiToken` to its owning `User`.

    Raises 401 on missing/invalid/revoked tokens or inactive users.
    """
    raw = _extract_token(request)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = hash_api_token(raw)
    result = await db.execute(
        select(ApiToken).where(ApiToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if not token or token.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_result = await db.execute(select(User).where(User.id == token.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    try:
        await db.execute(
            update(ApiToken)
            .where(ApiToken.id == token.id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to update api_token.last_used_at: %s", exc)

    request.state.api_token_hash = token_hash
    return user


def api_token_rate_limit_key(request: Request) -> str:
    """Rate-limit key for slowapi: prefer the token hash, fall back to IP."""
    raw = _extract_token(request)
    if raw:
        return f"token:{hash_api_token(raw)}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"
