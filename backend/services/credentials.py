"""
Runtime credential resolution.

Checks the database `settings` table first, falls back to .env values.
This allows API keys entered via the admin UI to take effect immediately
without restarting the server.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models.settings import Setting
from backend.utils.security import decrypt_value
from backend.config import get_settings

_settings = get_settings()


async def get_google_credentials(db: AsyncSession) -> tuple[str, str]:
    """Return (client_id, client_secret) from DB or env."""
    client_id = _settings.google_client_id
    client_secret = _settings.google_client_secret

    # Check DB for overrides
    result = await db.execute(
        select(Setting).where(Setting.key.in_(["google_client_id", "google_client_secret"]))
    )
    for row in result.scalars().all():
        val = row.value or ""
        if row.is_secret and val:
            try:
                val = decrypt_value(val)
            except Exception:
                pass
        if row.key == "google_client_id" and val:
            client_id = val
        elif row.key == "google_client_secret" and val:
            client_secret = val

    return client_id, client_secret


async def get_claude_api_key(db: AsyncSession) -> str:
    """Return Claude API key from DB or env."""
    key = _settings.claude_api_key

    result = await db.execute(
        select(Setting).where(Setting.key == "claude_api_key")
    )
    row = result.scalar_one_or_none()
    if row and row.value:
        try:
            val = decrypt_value(row.value) if row.is_secret else row.value
            if val:
                key = val
        except Exception:
            pass

    return key
