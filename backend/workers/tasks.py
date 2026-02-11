import logging
import asyncio
from arq import create_pool
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
    """Incremental sync for all active accounts."""
    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.is_active == True)
        )
        accounts = result.scalars().all()

    for account in accounts:
        try:
            sync_service = EmailSyncService(account.id)
            await sync_service.incremental_sync()
        except Exception as e:
            logger.error(f"Sync error for account {account.id}: {e}")


async def analyze_emails_batch(ctx, email_ids: list[int]):
    """Batch AI analysis of emails."""
    ai_service = AIService()
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
        ai_service = AIService()
        await ai_service.batch_categorize(email_ids)
        logger.info(f"Analyzed {len(email_ids)} emails for account {account_id}")


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
