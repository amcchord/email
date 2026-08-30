"""Cross-process account ownership for Gmail-changing work.

Both synchronization and the durable mail-action drainer use the same
PostgreSQL transaction advisory-lock namespace.  The lock lives on a
dedicated session so commits performed by the caller cannot release it early.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session


ACCOUNT_ADVISORY_LOCK_NAMESPACE = 0x4D41494C  # "MAIL"


@asynccontextmanager
async def account_advisory_lock(
    account_id: int,
    *,
    session_factory: Callable[[], AsyncSession] = async_session,
) -> AsyncIterator[bool]:
    """Try to own one account until this context exits.

    A transaction-scoped lock cannot leak into the pool.  The explicit
    rollback also closes the otherwise idle transaction before the dedicated
    session returns its connection.
    """
    async with session_factory() as lock_db:
        result = await lock_db.execute(
            text("SELECT pg_try_advisory_xact_lock(:namespace, :account_id)"),
            {
                "namespace": ACCOUNT_ADVISORY_LOCK_NAMESPACE,
                "account_id": account_id,
            },
        )
        acquired = bool(result.scalar_one())
        if not acquired:
            yield False
            return

        try:
            yield True
        finally:
            await lock_db.rollback()
