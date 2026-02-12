import logging
import asyncio
from arq import create_pool, cron
from arq.connections import RedisSettings
from backend.config import get_settings
from backend.services.sync import EmailSyncService
from backend.services.ai import AIService
from backend.database import async_session
from backend.models.email import Email
from backend.models.account import GoogleAccount
from sqlalchemy import select

logger = logging.getLogger(__name__)
settings = get_settings()


def parse_redis_url(url: str) -> RedisSettings:
    """Parse redis URL into RedisSettings."""
    # redis://localhost:6379/0
    url = url.replace("redis://", "")
    parts = url.split("/")
    host_port = parts[0]
    database = int(parts[1]) if len(parts) > 1 else 0
    host_parts = host_port.split(":")
    host = host_parts[0]
    port = int(host_parts[1]) if len(host_parts) > 1 else 6379
    return RedisSettings(host=host, port=port, database=database)


async def sync_account_full(ctx, account_id: int):
    """Full sync for an account."""
    logger.info(f"Starting full sync task for account {account_id}")
    sync_service = EmailSyncService(account_id)
    await sync_service.full_sync()
    logger.info(f"Full sync task completed for account {account_id}")


async def sync_account_incremental(ctx, account_id: int):
    """Incremental sync for an account."""
    logger.info(f"Starting incremental sync for account {account_id}")
    sync_service = EmailSyncService(account_id)
    await sync_service.incremental_sync()
    logger.info(f"Incremental sync completed for account {account_id}")


async def sync_all_accounts(ctx):
    """Incremental sync for all active accounts.

    Skips accounts that are already syncing or recently errored (10 min cooldown).
    """
    from backend.models.account import SyncStatus
    from datetime import datetime, timezone, timedelta

    ERROR_COOLDOWN = timedelta(minutes=10)

    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.is_active == True)
        )
        accounts = result.scalars().all()

    for account in accounts:
        async with async_session() as db:
            result = await db.execute(
                select(SyncStatus).where(SyncStatus.account_id == account.id)
            )
            sync = result.scalar_one_or_none()

            # Skip if already syncing
            if sync and sync.status == "syncing":
                logger.debug(f"Skipping account {account.id} - already syncing")
                continue

            # Skip if recently errored (cooldown to avoid hammering rate limits)
            if sync and sync.status == "error" and sync.completed_at:
                age = datetime.now(timezone.utc) - sync.completed_at
                if age < ERROR_COOLDOWN:
                    remaining = int((ERROR_COOLDOWN - age).total_seconds())
                    logger.debug(f"Skipping account {account.id} - error cooldown ({remaining}s remaining)")
                    continue

        try:
            sync_service = EmailSyncService(account.id)
            await sync_service.incremental_sync()
        except Exception as e:
            logger.error(f"Sync error for account {account.id}: {e}")


async def _resolve_model_for_account(account_id: int) -> str:
    """Look up the agentic model for the user who owns this account."""
    from backend.services.ai import get_model_for_user

    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount.user_id).where(GoogleAccount.id == account_id)
        )
        row = result.first()
        if row:
            return await get_model_for_user(row[0])

    from backend.schemas.auth import DEFAULT_AI_PREFERENCES
    return DEFAULT_AI_PREFERENCES["agentic_model"]


async def _resolve_model_for_emails(email_ids: list[int]) -> str:
    """Look up the agentic model from the owner of the first email's account."""
    from backend.services.ai import get_model_for_user

    if not email_ids:
        from backend.schemas.auth import DEFAULT_AI_PREFERENCES
        return DEFAULT_AI_PREFERENCES["agentic_model"]

    async with async_session() as db:
        result = await db.execute(
            select(Email.account_id).where(Email.id == email_ids[0])
        )
        row = result.first()
        if row:
            acct_result = await db.execute(
                select(GoogleAccount.user_id).where(GoogleAccount.id == row[0])
            )
            acct_row = acct_result.first()
            if acct_row:
                return await get_model_for_user(acct_row[0])

    from backend.schemas.auth import DEFAULT_AI_PREFERENCES
    return DEFAULT_AI_PREFERENCES["agentic_model"]


async def analyze_emails_batch(ctx, email_ids: list[int]):
    """Batch AI analysis of emails."""
    model = await _resolve_model_for_emails(email_ids)
    ai_service = AIService(model=model)
    await ai_service.batch_categorize(email_ids)


async def analyze_recent_unanalyzed(ctx, account_id: int, limit: int = 50):
    """Analyze recent emails that haven't been analyzed yet."""
    from backend.models.ai import AIAnalysis
    from sqlalchemy import desc

    async with async_session() as db:
        subquery = select(AIAnalysis.email_id)
        result = await db.execute(
            select(Email.id).where(
                Email.account_id == account_id,
                ~Email.id.in_(subquery),
            ).order_by(desc(Email.date)).limit(limit)
        )
        email_ids = [r[0] for r in result.all()]

    if email_ids:
        model = await _resolve_model_for_account(account_id)
        ai_service = AIService(model=model)
        await ai_service.batch_categorize(email_ids)
        logger.info(f"Analyzed {len(email_ids)} emails for account {account_id}")


async def auto_categorize_account(ctx, account_id: int, limit: int = 1000):
    """Auto-categorize the newest `limit` emails for an account."""
    model = await _resolve_model_for_account(account_id)
    logger.info(f"Starting auto-categorization for account {account_id} (limit={limit}, model={model})")
    ai_service = AIService(model=model)
    analyzed = await ai_service.auto_categorize_newest(account_id, limit=limit)
    logger.info(f"Auto-categorization complete for account {account_id}: {analyzed} emails analyzed")


async def startup(ctx):
    """Worker startup."""
    logger.info("ARQ worker started")


async def shutdown(ctx):
    """Worker shutdown."""
    logger.info("ARQ worker shutting down")


class WorkerSettings:
    """ARQ worker settings."""
    redis_settings = parse_redis_url(settings.redis_url)
    functions = [
        sync_account_full,
        sync_account_incremental,
        sync_all_accounts,
        analyze_emails_batch,
        analyze_recent_unanalyzed,
        auto_categorize_account,
    ]
    # Schedule periodic incremental sync for all accounts every 2 minutes
    cron_jobs = [
        cron(sync_all_accounts, minute={i for i in range(0, 60, 2)}, run_at_startup=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 5
    job_timeout = 7200  # 2 hours for full sync


async def queue_sync(account_id: int, full: bool = False):
    """Queue a sync job."""
    redis = await create_pool(parse_redis_url(settings.redis_url))
    if full:
        await redis.enqueue_job("sync_account_full", account_id)
    else:
        await redis.enqueue_job("sync_account_incremental", account_id)
    await redis.close()


async def queue_analysis(email_ids: list[int]):
    """Queue an analysis job."""
    redis = await create_pool(parse_redis_url(settings.redis_url))
    await redis.enqueue_job("analyze_emails_batch", email_ids)
    await redis.close()


async def queue_auto_categorize(account_id: int, limit: int = 1000):
    """Queue an auto-categorize job for an account."""
    redis = await create_pool(parse_redis_url(settings.redis_url))
    await redis.enqueue_job("auto_categorize_account", account_id, limit)
    await redis.close()
