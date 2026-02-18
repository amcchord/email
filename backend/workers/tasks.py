import logging
import asyncio
from datetime import timedelta
from arq import create_pool, cron
from arq.connections import RedisSettings
from backend.config import get_settings
from backend.services.sync import EmailSyncService
from backend.services.calendar_sync import CalendarSyncService
from backend.services.ai import AIService
from backend.database import async_session
from backend.models.email import Email
from backend.models.account import GoogleAccount
from sqlalchemy import select, update

logger = logging.getLogger(__name__)
settings = get_settings()

# In-memory lock to prevent overlapping sync_all_accounts runs
_sync_lock = asyncio.Lock()


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


async def _queue_ai_for_new_emails(account_id: int, new_email_ids: list[int]):
    """Queue AI analysis for newly synced emails, in chunks of 100.

    Skips trash/spam emails before queuing.  Only queues if there are
    IDs to process.
    """
    if not new_email_ids:
        return

    # Filter out trash/spam/sent before sending to AI – sent emails are
    # the user's own outbound messages and should never be flagged as
    # "needs reply".
    from backend.models.ai import AIAnalysis
    filtered_ids = []
    async with async_session() as db:
        result = await db.execute(
            select(Email.id).where(
                Email.id.in_(new_email_ids),
                Email.is_trash == False,
                Email.is_spam == False,
                Email.is_sent == False,
                ~Email.id.in_(select(AIAnalysis.email_id)),
            )
        )
        filtered_ids = [r[0] for r in result.all()]

    if not filtered_ids:
        return

    logger.info(f"Queuing AI analysis for {len(filtered_ids)} new emails (account {account_id})")
    redis = await create_pool(parse_redis_url(settings.redis_url))
    try:
        for i in range(0, len(filtered_ids), 100):
            chunk = filtered_ids[i:i + 100]
            await redis.enqueue_job("analyze_emails_batch", chunk)
    finally:
        await redis.close()


async def _queue_sent_email_classification(account_id: int, new_email_ids: list[int]):
    """Queue lightweight AI classification for newly synced sent emails.

    Determines whether each sent email expects a reply from the recipient.
    """
    if not new_email_ids:
        return

    from backend.models.ai import AIAnalysis

    async with async_session() as db:
        result = await db.execute(
            select(Email.id).where(
                Email.id.in_(new_email_ids),
                Email.is_sent == True,
                Email.is_trash == False,
                Email.is_spam == False,
            )
        )
        sent_ids = [r[0] for r in result.all()]

    if not sent_ids:
        return

    logger.info(f"Queuing sent-email classification for {len(sent_ids)} emails (account {account_id})")
    redis = await create_pool(parse_redis_url(settings.redis_url))
    try:
        for i in range(0, len(sent_ids), 100):
            chunk = sent_ids[i:i + 100]
            await redis.enqueue_job("classify_sent_emails_batch", chunk)
    finally:
        await redis.close()


async def _clear_needs_reply_for_replied_threads(new_email_ids: list[int]):
    """When sent emails are synced, mark needs_reply=false on earlier
    emails in the same thread.

    This handles the case where a user sends a reply and the original
    received email's stale needs_reply=true flag should be cleared.
    """
    if not new_email_ids:
        return

    from backend.models.ai import AIAnalysis

    async with async_session() as db:
        # Find sent emails among the newly synced batch
        result = await db.execute(
            select(Email.gmail_thread_id, Email.account_id, Email.date)
            .where(
                Email.id.in_(new_email_ids),
                Email.is_sent == True,
                Email.gmail_thread_id.isnot(None),
            )
        )
        sent_emails = result.all()

        if not sent_emails:
            return

        cleared_total = 0
        # For each sent email, clear needs_reply on earlier thread emails
        for thread_id, account_id, sent_date in sent_emails:
            # Find email IDs in the same thread that are older
            thread_result = await db.execute(
                select(Email.id).where(
                    Email.gmail_thread_id == thread_id,
                    Email.account_id == account_id,
                    Email.date < sent_date,
                )
            )
            older_ids = [r[0] for r in thread_result.all()]

            if older_ids:
                result = await db.execute(
                    update(AIAnalysis)
                    .where(
                        AIAnalysis.email_id.in_(older_ids),
                        AIAnalysis.needs_reply == True,
                    )
                    .values(needs_reply=False)
                )
                cleared_total += result.rowcount

        await db.commit()
        if cleared_total:
            logger.info(f"Cleared needs_reply on {cleared_total} emails due to sent replies")


async def _refresh_digests_for_replied_threads(new_email_ids: list[int]):
    """Regenerate thread digests for threads that received new sent emails.

    When a user sends a reply, the existing thread digest (summary,
    is_resolved, resolved_outcome) may be stale.  This function finds
    threads that already have a digest and got a new sent email, then
    regenerates those digests so the conversation status is up to date.
    """
    if not new_email_ids:
        return

    from backend.models.ai import ThreadDigest

    async with async_session() as db:
        # Find sent emails among the newly synced batch
        result = await db.execute(
            select(Email.gmail_thread_id, Email.account_id)
            .where(
                Email.id.in_(new_email_ids),
                Email.is_sent == True,
                Email.gmail_thread_id.isnot(None),
            )
            .distinct()
        )
        sent_thread_pairs = [(r[0], r[1]) for r in result.all()]

        if not sent_thread_pairs:
            return

        # Find which of these threads already have a digest (only those
        # need regeneration -- threads without a digest will get one
        # during the normal digest generation flow)
        threads_needing_refresh = []
        for thread_id, account_id in sent_thread_pairs:
            existing = await db.scalar(
                select(ThreadDigest.id).where(
                    ThreadDigest.gmail_thread_id == thread_id,
                    ThreadDigest.account_id == account_id,
                )
            )
            if existing:
                threads_needing_refresh.append((account_id, thread_id))

    if not threads_needing_refresh:
        return

    logger.info(
        f"Refreshing {len(threads_needing_refresh)} thread digests "
        f"due to new sent replies"
    )

    # Resolve model/context from the first account
    first_account_id = threads_needing_refresh[0][0]
    model = await _resolve_model_for_account(first_account_id)
    user_id = await _resolve_user_id_for_account(first_account_id)
    user_context = await _resolve_user_context(user_id)
    acct_ids = list(set(aid for aid, _ in threads_needing_refresh))
    acct_descs = await _resolve_account_descriptions(acct_ids)

    ai_service = AIService(model=model)
    for account_id, thread_id in threads_needing_refresh:
        try:
            acct_desc = acct_descs.get(account_id)
            await ai_service.generate_thread_digest(
                thread_id,
                account_id,
                user_context=user_context,
                account_description=acct_desc,
            )
        except Exception as e:
            logger.error(
                f"Failed to refresh digest for thread {thread_id}: {e}"
            )


async def _check_llm_thread_merges(account_id: int, new_email_ids: list[int]):
    """Use LLM to detect thread merges that header-based logic missed.

    Targets new single-message "threads" whose subjects look like replies
    (Re:, Fwd:, etc.) but were not caught by In-Reply-To header matching.
    For each candidate, finds recent threads with similar subjects and asks
    the LLM whether they should be merged.
    """
    if not new_email_ids:
        return

    import re as _re
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from sqlalchemy import func as sqla_func, delete as sqla_delete

    REPLY_PREFIX_RE = _re.compile(r'^(Re|Fwd|Fw)\s*:\s*', _re.IGNORECASE)
    CONFIDENCE_THRESHOLD = 0.8

    async with async_session() as db:
        # Find new emails that started their own thread (thread_id == message_id)
        # and whose subjects suggest they are replies
        result = await db.execute(
            select(Email).where(
                Email.id.in_(new_email_ids),
                Email.gmail_thread_id == Email.gmail_message_id,
                Email.is_trash == False,
                Email.is_spam == False,
            )
        )
        lone_emails = result.scalars().all()

        if not lone_emails:
            return

        # Filter to those with reply-like subjects
        candidates = []
        for email in lone_emails:
            subj = email.subject or ""
            if REPLY_PREFIX_RE.search(subj):
                candidates.append(email)

        if not candidates:
            return

        logger.info(
            f"LLM thread merge: checking {len(candidates)} reply-like "
            f"lone emails for account {account_id}"
        )

        ai_service = AIService()
        merged_count = 0

        for email in candidates:
            try:
                subj = email.subject or ""
                # Strip reply prefixes and ticket numbers for fuzzy matching
                stripped = REPLY_PREFIX_RE.sub("", subj).strip()
                # Also strip common ticket patterns like [Ticket:123456]
                stripped = _re.sub(r'\[Ticket:\d+\]', '', stripped).strip()

                if not stripped:
                    continue

                # Find recent threads (last 7 days) with similar subjects
                cutoff = email.date - _td(days=7) if email.date else _dt.now(_tz.utc) - _td(days=7)

                # Use a LIKE query on subject after stripping prefixes.
                # We search for threads that contain the core subject text.
                search_term = f"%{stripped[:80]}%"
                result = await db.execute(
                    select(
                        Email.gmail_thread_id,
                        sqla_func.max(Email.subject).label("subject"),
                        sqla_func.max(Email.snippet).label("snippet"),
                        sqla_func.count(Email.id).label("msg_count"),
                    )
                    .where(
                        Email.account_id == email.account_id,
                        Email.gmail_thread_id != email.gmail_thread_id,
                        Email.date >= cutoff,
                        Email.is_trash == False,
                        Email.is_spam == False,
                        Email.subject.ilike(search_term),
                    )
                    .group_by(Email.gmail_thread_id)
                    .having(sqla_func.count(Email.id) >= 1)
                    .limit(3)
                )
                candidate_threads = result.all()

                if not candidate_threads:
                    continue

                # Get participants for each candidate thread
                for ct in candidate_threads:
                    part_result = await db.execute(
                        select(Email.from_address)
                        .where(
                            Email.gmail_thread_id == ct.gmail_thread_id,
                            Email.account_id == email.account_id,
                        )
                        .distinct()
                    )
                    participants = [r[0] for r in part_result.all() if r[0]]

                    merge_result = await ai_service.check_thread_merge(
                        email_subject=subj,
                        email_from=email.from_address or "",
                        email_snippet=email.snippet or "",
                        candidate_subject=ct.subject or "",
                        candidate_participants=participants,
                        candidate_snippet=ct.snippet or "",
                    )

                    should_merge = merge_result.get("should_merge", False)
                    confidence = merge_result.get("confidence", 0.0)

                    if should_merge and confidence >= CONFIDENCE_THRESHOLD:
                        target_thread_id = ct.gmail_thread_id
                        orphan_thread_id = email.gmail_thread_id
                        reason = merge_result.get("reason", "")

                        logger.info(
                            f"LLM thread merge: merging thread {orphan_thread_id} "
                            f"into {target_thread_id} (confidence={confidence:.2f}, "
                            f"reason={reason!r})"
                        )

                        # Migrate all emails from the orphan thread
                        await db.execute(
                            update(Email)
                            .where(
                                Email.gmail_thread_id == orphan_thread_id,
                                Email.account_id == email.account_id,
                            )
                            .values(gmail_thread_id=target_thread_id)
                        )

                        # Delete orphaned ThreadDigest
                        from backend.models.ai import ThreadDigest
                        await db.execute(
                            sqla_delete(ThreadDigest)
                            .where(
                                ThreadDigest.gmail_thread_id == orphan_thread_id,
                                ThreadDigest.account_id == email.account_id,
                            )
                        )

                        merged_count += 1
                        break  # Merged; stop checking other candidates

            except Exception as e:
                logger.warning(
                    f"LLM thread merge check failed for email {email.id}: {e}"
                )

        if merged_count:
            await db.commit()
            logger.info(
                f"LLM thread merge: merged {merged_count} threads for account {account_id}"
            )


async def sync_account_full(ctx, account_id: int):
    """Full sync for an account."""
    logger.info(f"Starting full sync task for account {account_id}")
    sync_service = EmailSyncService(account_id)
    new_email_ids = await sync_service.full_sync()
    logger.info(f"Full sync task completed for account {account_id}")

    # Auto-analyze new emails (for full sync, we don't auto-analyze
    # since there could be thousands -- use backfill for that)


async def sync_account_incremental(ctx, account_id: int):
    """Incremental sync for an account."""
    logger.info(f"Starting incremental sync for account {account_id}")
    sync_service = EmailSyncService(account_id)
    new_email_ids = await sync_service.incremental_sync()
    logger.info(f"Incremental sync completed for account {account_id}")

    # Auto-analyze any new emails that arrived
    try:
        await _queue_ai_for_new_emails(account_id, new_email_ids)
    except Exception as e:
        logger.warning(f"Failed to queue AI analysis after sync for account {account_id}: {e}")

    # Classify sent emails for expects_reply
    try:
        await _queue_sent_email_classification(account_id, new_email_ids)
    except Exception as e:
        logger.warning(f"Failed to queue sent-email classification after sync for account {account_id}: {e}")

    # Clear stale needs_reply flags for threads where the user sent a reply
    try:
        await _clear_needs_reply_for_replied_threads(new_email_ids)
    except Exception as e:
        logger.warning(f"Failed to clear needs_reply after sync for account {account_id}: {e}")

    # Refresh thread digests for threads that received sent replies
    try:
        await _refresh_digests_for_replied_threads(new_email_ids)
    except Exception as e:
        logger.warning(f"Failed to refresh digests after sync for account {account_id}: {e}")

    # LLM-based thread merge for reply-like emails that header matching missed
    try:
        await _check_llm_thread_merges(account_id, new_email_ids)
    except Exception as e:
        logger.warning(f"Failed LLM thread merge check after sync for account {account_id}: {e}")


def _is_rate_limit_exception(exc: Exception) -> bool:
    """Check if an exception looks like a Gmail rate-limit / quota error."""
    msg = str(exc).lower()
    if "429" in msg:
        return True
    if "rate" in msg and "limit" in msg:
        return True
    if "quota" in msg:
        return True
    return False


def _adaptive_cooldown(rate_limit_count: int) -> timedelta:
    """Return an escalating cooldown based on consecutive rate-limit hits.

    1st hit  ->  5 min
    2nd hit  -> 15 min
    3rd hit  -> 30 min
    4th+     -> 60 min (cap)
    """
    tiers = [5, 15, 30, 60]
    idx = min(rate_limit_count, len(tiers)) - 1
    if idx < 0:
        idx = 0
    return timedelta(minutes=tiers[idx])


async def sync_all_accounts(ctx):
    """Incremental sync for all active accounts.

    Uses an in-memory lock so overlapping cron ticks don't pile up.
    Accounts are sorted by least-recently-synced first (round-robin
    fairness) and a small delay is inserted between each account.

    Key improvements over the naive loop:
      - Circuit breaker: if ANY account hits a 429, stop processing
        the remaining accounts for this tick (quota is per-project).
      - Adaptive cooldown: consecutive rate-limit hits cause escalating
        backoff (5 / 15 / 30 / 60 min) instead of a fixed 5 min.
      - Account staggering: 2 s pause between accounts to spread load.
    """
    if _sync_lock.locked():
        # Previous sync still in progress -- skip this tick entirely
        return

    async with _sync_lock:
        from backend.models.account import SyncStatus
        from datetime import datetime, timezone, timedelta

        ERROR_COOLDOWN = timedelta(minutes=5)
        STALE_SYNC_THRESHOLD = timedelta(minutes=10)
        INTER_ACCOUNT_DELAY = 2  # seconds between accounts

        async with async_session() as db:
            result = await db.execute(
                select(GoogleAccount).where(GoogleAccount.is_active == True)
            )
            accounts = result.scalars().all()

        now = datetime.now(timezone.utc)

        # ── Gather sync statuses and separate incremental vs full sync ──
        incremental_accounts = []  # Have history_id -> quick incremental sync
        full_sync_accounts = []     # No history_id -> expensive full sync
        for account in accounts:
            async with async_session() as db:
                result = await db.execute(
                    select(SyncStatus).where(SyncStatus.account_id == account.id)
                )
                sync = result.scalar_one_or_none()
                if sync and sync.last_history_id:
                    incremental_accounts.append((account, sync))
                else:
                    full_sync_accounts.append((account, sync))

        # Sort each group so the account that hasn't been synced in the
        # longest time goes first.  Process ALL incremental accounts
        # first (they're quick and cheap), then at most ONE full-sync
        # account at the end (they're expensive and can eat the quota).
        _min_dt = datetime.min.replace(tzinfo=timezone.utc)
        incremental_accounts.sort(
            key=lambda pair: (pair[1].last_incremental_sync if pair[1] and pair[1].last_incremental_sync else _min_dt)
        )
        full_sync_accounts.sort(
            key=lambda pair: (pair[1].last_incremental_sync if pair[1] and pair[1].last_incremental_sync else _min_dt)
        )

        # Process incremental accounts first, then at most one full-sync account
        accounts_with_sync = incremental_accounts + full_sync_accounts[:1]
        if len(full_sync_accounts) > 1:
            skipped = [a.email for a, _ in full_sync_accounts[1:]]
            logger.debug(f"Deferring full sync for {skipped} -- only one full sync per tick")

        rate_limit_hits = 0  # Track how many accounts hit 429 this tick

        for account, sync in accounts_with_sync:
            async with async_session() as db:
                # Re-fetch sync inside transaction so changes are visible
                result = await db.execute(
                    select(SyncStatus).where(SyncStatus.account_id == account.id)
                )
                sync = result.scalar_one_or_none()

                # Detect stale "syncing" status from a dead/crashed sync job.
                if sync and sync.status == "syncing" and sync.started_at:
                    age = now - sync.started_at
                    if age > STALE_SYNC_THRESHOLD:
                        logger.warning(
                            f"Account {account.id} stuck in 'syncing' for {age}. "
                            f"Resetting to 'error' so it can be retried."
                        )
                        sync.status = "error"
                        sync.error_message = f"Sync stalled (no progress for {int(age.total_seconds() // 60)}m). Will retry."
                        sync.completed_at = now
                        await db.commit()
                    else:
                        # Recently started -- another job may be handling it
                        continue

                # Skip if still marked as syncing (freshly started by another job)
                if sync and sync.status == "syncing":
                    continue

                # Skip if rate limited -- use adaptive cooldown
                if sync and sync.status == "rate_limited":
                    # Respect retry_after with a 60-second buffer so we don't
                    # hit Google right at the boundary and extend their window.
                    RETRY_AFTER_BUFFER = timedelta(seconds=60)
                    if sync.retry_after and now < (sync.retry_after + RETRY_AFTER_BUFFER):
                        remaining = int(((sync.retry_after + RETRY_AFTER_BUFFER) - now).total_seconds())
                        logger.debug(f"Skipping account {account.id} - rate limited ({remaining}s remaining)")
                        continue
                    # Compute adaptive cooldown from consecutive rate-limit hits
                    rl_count = sync.rate_limit_count if sync.rate_limit_count else 1
                    cooldown = _adaptive_cooldown(rl_count)
                    if sync.completed_at:
                        since_error = now - sync.completed_at
                        if since_error < cooldown:
                            remaining = int((cooldown - since_error).total_seconds())
                            logger.debug(
                                f"Skipping account {account.id} - rate limit cooldown "
                                f"(tier {rl_count}, {remaining}s remaining)"
                            )
                            continue
                    # Cooldown passed -- clear and try
                    sync.retry_after = None
                    sync.status = "completed"
                    sync.error_message = None
                    # Don't reset rate_limit_count yet -- only reset on success
                    await db.commit()

                # Skip if generic error with cooldown
                if sync and sync.status == "error" and sync.completed_at:
                    age = now - sync.completed_at
                    if age < ERROR_COOLDOWN:
                        continue

            try:
                sync_service = EmailSyncService(account.id)
                new_email_ids = await sync_service.incremental_sync()

                # Success -- reset the rate_limit_count so the next failure
                # starts from tier 1 again.
                async with async_session() as db:
                    result = await db.execute(
                        select(SyncStatus).where(SyncStatus.account_id == account.id)
                    )
                    sync = result.scalar_one_or_none()
                    if sync and sync.rate_limit_count:
                        sync.rate_limit_count = 0
                        await db.commit()

                # Auto-analyze any new emails that arrived
                try:
                    await _queue_ai_for_new_emails(account.id, new_email_ids)
                except Exception as ai_err:
                    logger.warning(f"Failed to queue AI analysis after sync for account {account.id}: {ai_err}")

                # Clear stale needs_reply flags for threads where the user sent a reply
                try:
                    await _clear_needs_reply_for_replied_threads(new_email_ids)
                except Exception as nr_err:
                    logger.warning(f"Failed to clear needs_reply after sync for account {account.id}: {nr_err}")

                # Refresh thread digests for threads that received sent replies
                try:
                    await _refresh_digests_for_replied_threads(new_email_ids)
                except Exception as dig_err:
                    logger.warning(f"Failed to refresh digests after sync for account {account.id}: {dig_err}")

                # LLM-based thread merge for reply-like emails that header matching missed
                try:
                    await _check_llm_thread_merges(account.id, new_email_ids)
                except Exception as llm_err:
                    logger.warning(f"Failed LLM thread merge check after sync for account {account.id}: {llm_err}")

            except Exception as e:
                logger.error(f"Sync error for account {account.id}: {e}")

                # ── Circuit breaker ──────────────────────────────────
                # A single 429 might be a per-user rate limit (only
                # affects this one Gmail account).  Continue to the
                # next account instead of stopping immediately.  Only
                # break if 2+ accounts hit rate limits in the same tick
                # -- that indicates a project-wide quota issue.
                #
                # NOTE: Do NOT bump rate_limit_count here -- the sync
                # service (incremental_sync / full_sync) already
                # incremented it before re-raising.  Bumping again would
                # double-count each event and escalate cooldown tiers
                # twice as fast as intended.
                if _is_rate_limit_exception(e):
                    rate_limit_hits += 1
                    if rate_limit_hits >= 2:
                        logger.warning(
                            "Rate limit hit on %d accounts this tick -- "
                            "stopping sync loop (likely project-wide quota issue)",
                            rate_limit_hits,
                        )
                        break
                    logger.warning(
                        "Rate limit hit on account %s -- continuing to "
                        "next account (may be per-user limit)",
                        account.id,
                    )

            # Breathing room between accounts to spread API load
            await asyncio.sleep(INTER_ACCOUNT_DELAY)


async def _resolve_user_id_for_account(account_id: int) -> int | None:
    """Look up the user_id who owns this account."""
    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount.user_id).where(GoogleAccount.id == account_id)
        )
        row = result.first()
        if row:
            return row[0]
    return None


async def _resolve_user_id_for_emails(email_ids: list[int]) -> int | None:
    """Look up the user_id who owns the first email's account."""
    if not email_ids:
        return None
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
                return acct_row[0]
    return None


async def _resolve_model_for_account(account_id: int) -> str:
    """Look up the agentic model for the user who owns this account."""
    from backend.services.ai import get_model_for_user

    user_id = await _resolve_user_id_for_account(account_id)
    if user_id:
        return await get_model_for_user(user_id)

    from backend.schemas.auth import DEFAULT_AI_PREFERENCES
    return DEFAULT_AI_PREFERENCES["agentic_model"]


async def _resolve_model_for_emails(email_ids: list[int]) -> str:
    """Look up the agentic model from the owner of the first email's account."""
    from backend.services.ai import get_model_for_user

    user_id = await _resolve_user_id_for_emails(email_ids)
    if user_id:
        return await get_model_for_user(user_id)

    from backend.schemas.auth import DEFAULT_AI_PREFERENCES
    return DEFAULT_AI_PREFERENCES["agentic_model"]


async def _resolve_user_context(user_id: int | None) -> str | None:
    """Load the about_me text for a user, if any."""
    if not user_id:
        return None
    from backend.models.user import User
    async with async_session() as db:
        result = await db.execute(
            select(User.about_me).where(User.id == user_id)
        )
        row = result.first()
        if row and row[0]:
            return row[0]
    return None


async def _resolve_account_descriptions(account_ids: list[int]) -> dict[int, str]:
    """Load descriptions for a list of account IDs. Returns {account_id: description}."""
    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount.id, GoogleAccount.description)
            .where(
                GoogleAccount.id.in_(account_ids),
                GoogleAccount.description.isnot(None),
            )
        )
        return {r[0]: r[1] for r in result.all() if r[1]}


async def _resolve_account_emails(account_ids: list[int]) -> dict[int, str]:
    """Load email addresses for a list of account IDs. Returns {account_id: email}."""
    async with async_session() as db:
        result = await db.execute(
            select(GoogleAccount.id, GoogleAccount.email)
            .where(GoogleAccount.id.in_(account_ids))
        )
        return {r[0]: r[1] for r in result.all() if r[1]}


async def analyze_emails_batch(ctx, email_ids: list[int]):
    """Batch AI analysis of emails."""
    model = await _resolve_model_for_emails(email_ids)
    ai_service = AIService(model=model)

    # Build progress callback if a user can be resolved
    on_progress = None
    user_id = await _resolve_user_id_for_emails(email_ids)
    if user_id:
        from backend.routers.ai import increment_ai_progress

        async def on_progress():
            await increment_ai_progress(user_id)

    # Load user context and account descriptions for smarter analysis
    user_context = await _resolve_user_context(user_id)
    # Find account IDs for these emails
    acct_ids = set()
    async with async_session() as db:
        result = await db.execute(
            select(Email.account_id).where(Email.id.in_(email_ids)).distinct()
        )
        acct_ids = {r[0] for r in result.all()}
    acct_descs = await _resolve_account_descriptions(list(acct_ids)) if acct_ids else {}
    acct_emails = await _resolve_account_emails(list(acct_ids)) if acct_ids else {}

    await ai_service.batch_categorize(
        email_ids,
        on_progress=on_progress,
        user_context=user_context,
        account_descriptions=acct_descs,
        account_emails=acct_emails,
    )

    # After analysis, generate thread digests for multi-message threads
    try:
        await _generate_digests_for_emails(email_ids, model, user_context, acct_descs)
    except Exception as e:
        logger.warning(f"Failed to generate thread digests after batch analysis: {e}")

    # After analysis, queue bundle generation for the user
    if user_id:
        try:
            redis = await create_pool(parse_redis_url(settings.redis_url))
            try:
                await redis.enqueue_job("generate_bundles_for_user", user_id, model)
            finally:
                await redis.close()
        except Exception as e:
            logger.warning(f"Failed to queue bundle generation for user {user_id}: {e}")


async def classify_sent_emails_batch(ctx, email_ids: list[int]):
    """Classify a batch of sent emails for expects_reply using a lightweight AI call."""
    ai_service = AIService()
    for email_id in email_ids:
        try:
            await ai_service.classify_sent_email(email_id)
        except Exception as e:
            logger.error(f"Failed to classify sent email {email_id}: {e}")
    logger.info(f"Classified {len(email_ids)} sent emails for expects_reply")


async def analyze_recent_unanalyzed(ctx, account_id: int, limit: int = 50):
    """Analyze recent emails that haven't been analyzed yet."""
    from backend.models.ai import AIAnalysis
    from sqlalchemy import desc

    async with async_session() as db:
        subquery = select(AIAnalysis.email_id)
        result = await db.execute(
            select(Email.id).where(
                Email.account_id == account_id,
                Email.is_sent == False,
                Email.is_trash == False,
                Email.is_spam == False,
                ~Email.id.in_(subquery),
            ).order_by(desc(Email.date)).limit(limit)
        )
        email_ids = [r[0] for r in result.all()]

    if email_ids:
        model = await _resolve_model_for_account(account_id)
        ai_service = AIService(model=model)

        # Load user context, account description, and account email
        user_id = await _resolve_user_id_for_account(account_id)
        user_context = await _resolve_user_context(user_id)
        acct_descs = await _resolve_account_descriptions([account_id])
        acct_emails = await _resolve_account_emails([account_id])

        await ai_service.batch_categorize(
            email_ids,
            user_context=user_context,
            account_descriptions=acct_descs,
            account_emails=acct_emails,
        )
        logger.info(f"Analyzed {len(email_ids)} emails for account {account_id}")


async def auto_categorize_account(ctx, account_id: int, days: int = None):
    """Auto-categorize unanalyzed emails for an account.

    If days is provided, only process emails from the last N days.
    Otherwise, process all unanalyzed emails.
    """
    model = await _resolve_model_for_account(account_id)
    logger.info(f"Starting auto-categorization for account {account_id} (days={days}, model={model})")
    ai_service = AIService(model=model)

    # Build progress callback if a user can be resolved
    on_progress = None
    user_id = await _resolve_user_id_for_account(account_id)
    if user_id:
        from backend.routers.ai import increment_ai_progress

        async def on_progress():
            await increment_ai_progress(user_id)

    # Load user context, account description, and account email for smarter analysis
    user_context = await _resolve_user_context(user_id)
    acct_descs = await _resolve_account_descriptions([account_id])
    acct_desc = acct_descs.get(account_id)
    acct_emails = await _resolve_account_emails([account_id])
    acct_email = acct_emails.get(account_id)

    since_date = None
    if days is not None and days > 0:
        from datetime import datetime, timezone, timedelta
        since_date = datetime.now(timezone.utc) - timedelta(days=days)

    analyzed = await ai_service.auto_categorize_newest(
        account_id,
        since_date=since_date,
        on_progress=on_progress,
        user_context=user_context,
        account_description=acct_desc,
        account_email=acct_email,
    )
    logger.info(f"Auto-categorization complete for account {account_id}: {analyzed} emails analyzed")

    # After categorization, queue digest and bundle generation
    if analyzed > 0:
        try:
            redis = await create_pool(parse_redis_url(settings.redis_url))
            try:
                await redis.enqueue_job("generate_digests_for_account", account_id)
                if user_id:
                    await redis.enqueue_job("generate_bundles_for_user", user_id, model)
            finally:
                await redis.close()
        except Exception as e:
            logger.warning(f"Failed to queue digest/bundle generation for account {account_id}: {e}")


async def _generate_digests_for_emails(
    email_ids: list[int],
    model: str,
    user_context: str | None,
    acct_descs: dict[int, str],
):
    """Generate thread digests for threads that the given emails belong to.

    Only processes threads with 2+ messages.
    """
    from sqlalchemy import func as sqla_func

    async with async_session() as db:
        # Find unique (account_id, gmail_thread_id) pairs for these emails
        result = await db.execute(
            select(Email.account_id, Email.gmail_thread_id)
            .where(Email.id.in_(email_ids))
            .distinct()
        )
        thread_pairs = [(r[0], r[1]) for r in result.all() if r[1]]

        if not thread_pairs:
            return

        # Filter to threads that have 2+ messages
        qualifying = []
        for account_id, thread_id in thread_pairs:
            count = await db.scalar(
                select(sqla_func.count(Email.id)).where(
                    Email.account_id == account_id,
                    Email.gmail_thread_id == thread_id,
                    Email.is_trash == False,
                    Email.is_spam == False,
                )
            )
            if count and count >= 2:
                qualifying.append((account_id, thread_id))

    if not qualifying:
        return

    logger.info(f"Generating thread digests for {len(qualifying)} threads")
    ai_service = AIService(model=model)

    for account_id, thread_id in qualifying:
        try:
            acct_desc = acct_descs.get(account_id)
            await ai_service.generate_thread_digest(
                thread_id,
                account_id,
                user_context=user_context,
                account_description=acct_desc,
            )
        except Exception as e:
            logger.error(f"Failed to generate digest for thread {thread_id}: {e}")


async def generate_digests_for_account(ctx, account_id: int, max_digests: int = 50):
    """Generate thread digests for recently-analyzed multi-message threads.

    Only processes threads that:
      - Have 2+ messages
      - Have at least one recently-analyzed email (AIAnalysis exists)
      - Don't already have an up-to-date ThreadDigest

    Caps at max_digests per run to avoid runaway API costs.
    """
    from sqlalchemy import func as sqla_func
    from backend.models.ai import AIAnalysis, ThreadDigest

    model = await _resolve_model_for_account(account_id)
    user_id = await _resolve_user_id_for_account(account_id)
    user_context = await _resolve_user_context(user_id)
    acct_descs = await _resolve_account_descriptions([account_id])
    acct_desc = acct_descs.get(account_id)

    async with async_session() as db:
        # Find threads with 2+ messages that have AI analysis
        # and DON'T already have an up-to-date digest.
        # Order by latest email date so newest conversations come first.
        analyzed_threads_q = (
            select(
                Email.gmail_thread_id,
                sqla_func.count(Email.id).label("msg_count"),
                sqla_func.max(Email.date).label("latest_date"),
            )
            .join(AIAnalysis, AIAnalysis.email_id == Email.id)
            .where(
                Email.account_id == account_id,
                Email.is_trash == False,
                Email.is_spam == False,
            )
            .group_by(Email.gmail_thread_id)
            .having(sqla_func.count(Email.id) >= 2)
        ).subquery()

        # Left join with existing digests to find threads needing a digest
        existing_digest_q = (
            select(ThreadDigest.gmail_thread_id)
            .where(ThreadDigest.account_id == account_id)
        ).subquery()

        result = await db.execute(
            select(analyzed_threads_q.c.gmail_thread_id)
            .outerjoin(
                existing_digest_q,
                existing_digest_q.c.gmail_thread_id == analyzed_threads_q.c.gmail_thread_id,
            )
            .where(existing_digest_q.c.gmail_thread_id.is_(None))
            .order_by(analyzed_threads_q.c.latest_date.desc())
            .limit(max_digests)
        )
        thread_ids = [r[0] for r in result.all() if r[0]]

    if not thread_ids:
        logger.info(f"No threads needing digests for account {account_id}")
        return

    logger.info(f"Generating thread digests for {len(thread_ids)} threads in account {account_id}")
    ai_service = AIService(model=model)

    for thread_id in thread_ids:
        try:
            await ai_service.generate_thread_digest(
                thread_id,
                account_id,
                user_context=user_context,
                account_description=acct_desc,
            )
        except Exception as e:
            logger.error(f"Failed to generate digest for thread {thread_id}: {e}")


async def generate_digests_for_threads(
    ctx,
    thread_account_pairs: list[list],
):
    """Generate thread digests for specific thread+account pairs.

    Called as a background job when the awaiting-response endpoint finds
    threads that lack a ThreadDigest.  Only processes threads with 2+
    messages (the digest requirement).

    thread_account_pairs: list of [gmail_thread_id, account_id] pairs
    (arq serialises tuples as lists).
    """
    if not thread_account_pairs:
        return

    # Group by account so we can resolve context once per account
    from collections import defaultdict
    by_account = defaultdict(list)
    for pair in thread_account_pairs:
        thread_id, account_id = pair[0], pair[1]
        by_account[account_id].append(thread_id)

    for account_id, thread_ids in by_account.items():
        model = await _resolve_model_for_account(account_id)
        user_id = await _resolve_user_id_for_account(account_id)
        user_context = await _resolve_user_context(user_id)
        acct_descs = await _resolve_account_descriptions([account_id])
        acct_desc = acct_descs.get(account_id)

        ai_service = AIService(model=model)
        for thread_id in thread_ids:
            try:
                await ai_service.generate_thread_digest(
                    thread_id,
                    account_id,
                    user_context=user_context,
                    account_description=acct_desc,
                )
            except Exception as e:
                logger.error(
                    f"Failed to generate digest for awaiting thread {thread_id}: {e}"
                )

    logger.info(
        f"Finished generating digests for {len(thread_account_pairs)} awaiting-response threads"
    )


async def generate_bundles_for_user(ctx, user_id: int, model: str = None):
    """Generate topic bundles for a user across all their accounts."""
    from backend.services.bundler import bundle_by_topics

    logger.info(f"Generating topic bundles for user {user_id}")
    count = await bundle_by_topics(user_id, model=model)
    logger.info(f"Generated/updated {count} topic bundles for user {user_id}")


_calendar_sync_lock = asyncio.Lock()


async def sync_calendar_full(ctx, account_id: int):
    """Full calendar sync for an account."""
    logger.info(f"Starting full calendar sync for account {account_id}")
    sync_service = CalendarSyncService(account_id)
    await sync_service.full_sync()
    logger.info(f"Full calendar sync completed for account {account_id}")


async def sync_calendar_incremental(ctx, account_id: int):
    """Incremental calendar sync for an account."""
    logger.info(f"Starting incremental calendar sync for account {account_id}")
    sync_service = CalendarSyncService(account_id)
    await sync_service.incremental_sync()
    logger.info(f"Incremental calendar sync completed for account {account_id}")


async def sync_all_calendars(ctx):
    """Incremental calendar sync for all active accounts.

    Runs every 5 minutes. Uses an in-memory lock to prevent overlapping runs.
    """
    if _calendar_sync_lock.locked():
        return

    async with _calendar_sync_lock:
        async with async_session() as db:
            result = await db.execute(
                select(GoogleAccount).where(GoogleAccount.is_active == True)
            )
            accounts = result.scalars().all()

        for account in accounts:
            try:
                sync_service = CalendarSyncService(account.id)
                await sync_service.incremental_sync()
            except Exception as e:
                logger.error(f"Calendar sync error for account {account.id}: {e}")
            await asyncio.sleep(1)


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
        classify_sent_emails_batch,
        analyze_recent_unanalyzed,
        auto_categorize_account,
        generate_digests_for_account,
        generate_digests_for_threads,
        generate_bundles_for_user,
        sync_calendar_full,
        sync_calendar_incremental,
        sync_all_calendars,
    ]
    # Schedule periodic incremental sync for all accounts every minute.
    # Deliberately NOT using run_at_startup to avoid a burst of API calls
    # when the worker boots.  The first tick will fire within 60 seconds.
    # Calendar sync runs every 5 minutes (less frequent than email).
    cron_jobs = [
        cron(sync_all_accounts, minute={i for i in range(0, 60)}),
        cron(sync_all_calendars, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
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


async def queue_auto_categorize(account_id: int, days: int = None):
    """Queue an auto-categorize job for an account.

    If days is provided, only process emails from the last N days.
    """
    redis = await create_pool(parse_redis_url(settings.redis_url))
    await redis.enqueue_job("auto_categorize_account", account_id, days)
    await redis.close()
