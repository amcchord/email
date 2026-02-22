import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, update, delete
from backend.models.email import Email, Attachment, EmailLabel
from backend.models.account import GoogleAccount, SyncStatus
from backend.services.gmail import GmailService
from backend.services.credentials import get_google_credentials
from backend.utils.security import encrypt_value
from backend.database import async_session


def _extract_retry_after(error) -> datetime:
    """Extract a Retry-After timestamp from an error message. Returns None if unparseable."""
    error_str = str(error)
    match = re.search(r'[Rr]etry\s+after\s+(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)', error_str)
    if match:
        try:
            return datetime.fromisoformat(match.group(1).replace('Z', '+00:00'))
        except Exception:
            pass
    return None

logger = logging.getLogger(__name__)


class EmailSyncService:
    def __init__(self, account_id: int):
        self.account_id = account_id
        self._token_persisted = False

    async def _get_account(self, db: AsyncSession) -> GoogleAccount:
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.id == self.account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Account {self.account_id} not found")
        return account

    async def _create_gmail_service(self, db: AsyncSession, account: GoogleAccount) -> GmailService:
        """Create a GmailService with credentials resolved from the DB."""
        client_id, client_secret = await get_google_credentials(db)
        return GmailService(account, client_id=client_id, client_secret=client_secret)

    async def _persist_refreshed_token(self, gmail: GmailService):
        """Save refreshed access token back to the DB if it changed.

        Tracks a flag so the DB write only happens once per sync
        operation rather than after every single API call.
        """
        if self._token_persisted:
            return
        new_token = gmail.get_refreshed_token()
        if new_token:
            async with async_session() as db:
                account = await self._get_account(db)
                account.encrypted_access_token = encrypt_value(new_token)
                await db.commit()
                self._token_persisted = True
                logger.debug(f"Persisted refreshed token for account {self.account_id}")

    async def _update_sync_status(self, db: AsyncSession, **kwargs):
        result = await db.execute(
            select(SyncStatus).where(SyncStatus.account_id == self.account_id)
        )
        sync = result.scalar_one_or_none()
        if not sync:
            sync = SyncStatus(account_id=self.account_id)
            db.add(sync)

        for key, value in kwargs.items():
            setattr(sync, key, value)
        await db.commit()

    async def sync_labels(self):
        """Sync labels from Gmail."""
        async with async_session() as db:
            account = await self._get_account(db)
            gmail = await self._create_gmail_service(db, account)

            try:
                gmail_labels = await gmail.list_labels()
                await self._persist_refreshed_token(gmail)

                for gl in gmail_labels:
                    label_id = gl.get("id", "")
                    name = gl.get("name", label_id)
                    label_type = gl.get("type", "user")
                    color = gl.get("color", {})

                    result = await db.execute(
                        select(EmailLabel).where(
                            EmailLabel.account_id == self.account_id,
                            EmailLabel.gmail_label_id == label_id,
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.name = name
                        existing.label_type = label_type
                        existing.color_bg = color.get("backgroundColor")
                        existing.color_text = color.get("textColor")
                    else:
                        label = EmailLabel(
                            account_id=self.account_id,
                            gmail_label_id=label_id,
                            name=name,
                            label_type=label_type,
                            color_bg=color.get("backgroundColor"),
                            color_text=color.get("textColor"),
                        )
                        db.add(label)

                await db.commit()
                logger.info(f"Synced {len(gmail_labels)} labels for account {self.account_id}")

            except Exception as e:
                logger.error(f"Error syncing labels: {e}")
                raise

    async def full_sync(self) -> list[int]:
        """Perform a full email sync, skipping messages already in the DB.

        Processes pages incrementally: each page of message IDs is
        immediately filtered and fetched before moving on.  The
        page_token is checkpointed to sync_status so a worker restart
        resumes from the last saved page rather than starting over.

        Returns a list of newly inserted email IDs (DB primary keys).
        """

        # Phase 0: Setup -- create the Gmail service and check for a
        # checkpoint from a previous interrupted run.
        async with async_session() as db:
            account = await self._get_account(db)
            gmail = await self._create_gmail_service(db, account)

            result = await db.execute(
                select(SyncStatus).where(SyncStatus.account_id == self.account_id)
            )
            sync = result.scalar_one_or_none()
            resume_page_token = sync.sync_page_token if sync else None

            if resume_page_token:
                logger.info(f"Resuming full sync for account {self.account_id} from checkpoint")
            else:
                logger.info(f"Starting full sync for account {self.account_id}")

            await self._update_sync_status(
                db,
                status="syncing",
                current_phase="Syncing messages" if resume_page_token else "Starting sync",
                started_at=datetime.now(timezone.utc),
                error_message=None,
            )

        new_email_ids = []
        synced_count = 0
        skipped_count = 0
        latest_history_id = None
        page_token = resume_page_token
        total_estimate = 0
        page_count = 0
        batch_size = 100

        try:
            # Main loop: page through message IDs and fetch each page
            # immediately.  This avoids holding all IDs in memory and
            # makes the process resumable via the saved page_token.
            while True:
                # ── List one page of message IDs ─────────────────────
                messages, next_page, estimate = await gmail.list_message_ids(
                    page_token=page_token
                )
                page_ids = [m["id"] for m in messages]
                if total_estimate == 0 and estimate:
                    total_estimate = estimate
                page_count += 1

                # ── Filter out messages already in DB ────────────────
                async with async_session() as db:
                    result = await db.execute(
                        select(Email.gmail_message_id).where(
                            Email.account_id == self.account_id,
                            Email.gmail_message_id.in_(page_ids),
                        )
                    )
                    existing_in_page = set(r[0] for r in result.all())

                new_ids_in_page = [mid for mid in page_ids if mid not in existing_in_page]
                skipped_count += len(existing_in_page)

                # ── Fetch and save new messages from this page ───────
                for i in range(0, len(new_ids_in_page), batch_size):
                    batch_ids = new_ids_in_page[i:i + batch_size]
                    fetched = await gmail.batch_get_messages(batch_ids)

                    async with async_session() as db:
                        batch_ok = 0
                        for msg in fetched:
                            try:
                                async with db.begin_nested():
                                    parsed = GmailService.parse_message(msg)
                                    history_id = parsed.get("gmail_history_id", "")
                                    if history_id:
                                        if latest_history_id is None or int(history_id) > int(latest_history_id):
                                            latest_history_id = history_id

                                    email_id, is_new = await self._upsert_email(db, parsed)
                                    if is_new:
                                        new_email_ids.append(email_id)
                                batch_ok += 1
                            except Exception as msg_err:
                                msg_id = msg.get("id", "unknown")
                                logger.warning(f"Skipping message {msg_id}: {msg_err}")

                        synced_count += batch_ok
                        await db.commit()

                    # Pace between fetch batches
                    await asyncio.sleep(1)

                # ── Save checkpoint so a restart resumes from here ───
                async with async_session() as db:
                    phase_msg = f"Syncing: {synced_count} fetched, {skipped_count} skipped"
                    if total_estimate:
                        phase_msg += f" (est. {total_estimate} total)"

                    await self._update_sync_status(
                        db,
                        messages_synced=synced_count,
                        total_messages=total_estimate,
                        current_phase=phase_msg,
                        last_history_id=latest_history_id,
                        # Save the NEXT page token so we resume from
                        # the next page (this page is fully processed).
                        sync_page_token=next_page,
                        # Keep started_at fresh so stale-sync detector
                        # doesn't kill us
                        started_at=datetime.now(timezone.utc),
                    )

                if not next_page:
                    break

                page_token = next_page
                # Pace between list pages
                await asyncio.sleep(0.5)

            # Persist refreshed token once at the end of the sync
            await self._persist_refreshed_token(gmail)

            # Post-processing: search vectors, final history_id, completion
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE emails SET search_vector =
                        setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(from_name, '')), 'B') ||
                        setweight(to_tsvector('english', coalesce(from_address, '')), 'B') ||
                        setweight(to_tsvector('english', coalesce(snippet, '')), 'C') ||
                        setweight(to_tsvector('english', coalesce(left(body_text, 10000), '')), 'D')
                    WHERE account_id = :account_id AND search_vector IS NULL
                """), {"account_id": self.account_id})

                # Get the max history_id from all messages in DB
                result = await db.execute(
                    select(func.max(Email.gmail_history_id)).where(
                        Email.account_id == self.account_id,
                        Email.gmail_history_id.isnot(None),
                        Email.gmail_history_id != "",
                    )
                )
                db_max_history = result.scalar_one_or_none()
                if db_max_history:
                    if latest_history_id is None or int(db_max_history) > int(latest_history_id or 0):
                        latest_history_id = db_max_history

                # Count all messages and mark sync complete.
                # Clear sync_page_token since we're done.
                total_in_db = await db.scalar(
                    select(func.count(Email.id)).where(
                        Email.account_id == self.account_id
                    )
                ) or 0

                await self._update_sync_status(
                    db,
                    status="completed",
                    current_phase=None,
                    last_full_sync=datetime.now(timezone.utc),
                    last_history_id=latest_history_id,
                    completed_at=datetime.now(timezone.utc),
                    messages_synced=total_in_db,
                    total_messages=total_in_db,
                    sync_page_token=None,
                )

            # Sync labels
            await self.sync_labels()

            logger.info(
                f"Full sync complete: {synced_count} fetched, {skipped_count} skipped "
                f"({len(new_email_ids)} new) for account {self.account_id}"
            )
            return new_email_ids

        except Exception as e:
            logger.error(f"Full sync error for account {self.account_id}: {e}")
            retry_at = _extract_retry_after(e)
            if retry_at:
                error_msg = f"Rate limited by Gmail. Retry after {retry_at.strftime('%H:%M:%S UTC')}"
            else:
                error_msg = str(e)
            try:
                async with async_session() as db:
                    # Read current rate_limit_count to increment it
                    extra_kwargs = {}
                    if retry_at:
                        result = await db.execute(
                            select(SyncStatus).where(SyncStatus.account_id == self.account_id)
                        )
                        existing = result.scalar_one_or_none()
                        current_count = (existing.rate_limit_count if existing and existing.rate_limit_count else 0)
                        extra_kwargs["rate_limit_count"] = current_count + 1

                    # NOTE: Do NOT clear sync_page_token on error -- the
                    # checkpoint is still valid and lets the next attempt
                    # resume from where we left off.
                    await self._update_sync_status(
                        db,
                        status="rate_limited" if retry_at else "error",
                        error_message=error_msg,
                        current_phase=None,
                        completed_at=datetime.now(timezone.utc),
                        retry_after=retry_at,
                        **extra_kwargs,
                    )
            except Exception as status_err:
                # If we can't even update the status, log it loudly.
                # The stale sync detector in sync_all_accounts will
                # eventually recover this account.
                logger.error(
                    f"CRITICAL: Failed to update sync status for account "
                    f"{self.account_id} after error: {status_err}"
                )
            raise

    async def incremental_sync(self) -> list[int]:
        """Sync only changes since last sync.

        Does NOT set status to 'syncing' upfront -- incremental syncs are
        lightweight and should be invisible in the UI unless there are
        actual changes to process.

        Returns a list of newly inserted email IDs (DB primary keys).
        """
        async with async_session() as db:
            result = await db.execute(
                select(SyncStatus).where(SyncStatus.account_id == self.account_id)
            )
            sync = result.scalar_one_or_none()

            if not sync or not sync.last_history_id:
                # No previous sync, do full sync
                return await self.full_sync()

            if sync.sync_page_token:
                # An earlier full sync was interrupted and left a
                # checkpoint.  Continue from where it left off rather
                # than doing an incremental sync that would skip all
                # the un-fetched historical messages.
                logger.info(
                    f"Resuming interrupted full sync for account "
                    f"{self.account_id} (checkpoint exists)"
                )
                return await self.full_sync()

            last_history_id = sync.last_history_id

            # Create the Gmail service once for the whole incremental sync
            account = await self._get_account(db)
            gmail = await self._create_gmail_service(db, account)

        new_email_ids = []

        try:
            # Use max_retries=1 so we fail fast on rate limits rather than
            # blocking the worker with a 5-minute backoff sleep.  The cron
            # will retry next minute.  The adaptive cooldown in
            # sync_all_accounts handles escalation properly.
            history_result = await gmail.get_history(last_history_id, max_retries=1)

            if history_result is None:
                # History expired, need full sync
                logger.info("History expired, performing full sync")
                return await self.full_sync()

            history = history_result.get("history", [])
            new_history_id = history_result.get("new_history_id")

            if not history:
                # No changes -- silently update timestamp without changing status
                async with async_session() as db:
                    await self._update_sync_status(
                        db,
                        last_incremental_sync=datetime.now(timezone.utc),
                    )
                return []

            # There are actual changes -- process in a single session
            async with async_session() as db:
                change_count = len(history)
                await self._update_sync_status(
                    db,
                    status="syncing",
                    current_phase=f"Syncing {change_count} changes",
                    error_message=None,
                )

                # Process history changes
                messages_to_fetch = set()
                messages_to_delete = set()

                for entry in history:
                    for msg_added in entry.get("messagesAdded", []):
                        messages_to_fetch.add(msg_added["message"]["id"])
                    for msg_deleted in entry.get("messagesDeleted", []):
                        messages_to_delete.add(msg_deleted["message"]["id"])
                    for label_added in entry.get("labelsAdded", []):
                        messages_to_fetch.add(label_added["message"]["id"])
                    for label_removed in entry.get("labelsRemoved", []):
                        messages_to_fetch.add(label_removed["message"]["id"])

                # Remove deleted messages
                if messages_to_delete:
                    for mid in messages_to_delete:
                        result = await db.execute(
                            select(Email).where(
                                Email.gmail_message_id == mid,
                                Email.account_id == self.account_id,
                            )
                        )
                        email = result.scalar_one_or_none()
                        if email:
                            await db.delete(email)

                # Fetch and upsert changed messages
                if messages_to_fetch:
                    fetch_list = list(messages_to_fetch - messages_to_delete)
                    if fetch_list:
                        messages = await gmail.batch_get_messages(fetch_list)
                        for msg in messages:
                            try:
                                async with db.begin_nested():
                                    parsed = GmailService.parse_message(msg)
                                    email_id, is_new = await self._upsert_email(db, parsed)
                                    if is_new:
                                        new_email_ids.append(email_id)
                            except Exception as msg_err:
                                msg_id = msg.get("id", "unknown")
                                logger.warning(f"Skipping message {msg_id} in incremental sync: {msg_err}")

                if new_history_id:
                    await self._update_sync_status(
                        db,
                        last_history_id=new_history_id,
                        last_incremental_sync=datetime.now(timezone.utc),
                        status="completed",
                        current_phase=None,
                    )
                else:
                    await self._update_sync_status(
                        db,
                        last_incremental_sync=datetime.now(timezone.utc),
                        status="completed",
                        current_phase=None,
                    )

                await db.commit()
                logger.info(
                    f"Incremental sync: {len(messages_to_fetch)} updated ({len(new_email_ids)} new), "
                    f"{len(messages_to_delete)} deleted for account {self.account_id}"
                )

                # Check for emails from unsubscribed senders
                try:
                    await self._update_unsubscribe_tracking(db)
                except Exception as track_err:
                    logger.warning(f"Unsubscribe tracking update failed: {track_err}")

            # Persist refreshed token once at the end
            await self._persist_refreshed_token(gmail)

            return new_email_ids

        except Exception as e:
            logger.error(f"Incremental sync error for account {self.account_id}: {e}")
            retry_at = _extract_retry_after(e)
            if retry_at:
                error_msg = f"Rate limited by Gmail. Retry after {retry_at.strftime('%H:%M:%S UTC')}"
            else:
                error_msg = str(e)
            try:
                async with async_session() as db:
                    # Read current rate_limit_count to increment it
                    extra_kwargs = {}
                    if retry_at:
                        result = await db.execute(
                            select(SyncStatus).where(SyncStatus.account_id == self.account_id)
                        )
                        existing = result.scalar_one_or_none()
                        current_count = (existing.rate_limit_count if existing and existing.rate_limit_count else 0)
                        extra_kwargs["rate_limit_count"] = current_count + 1

                    await self._update_sync_status(
                        db,
                        status="rate_limited" if retry_at else "error",
                        error_message=error_msg,
                        current_phase=None,
                        completed_at=datetime.now(timezone.utc),
                        retry_after=retry_at,
                        **extra_kwargs,
                    )
            except Exception as status_err:
                logger.error(
                    f"CRITICAL: Failed to update sync status for account "
                    f"{self.account_id} after error: {status_err}"
                )
            raise

    async def _update_unsubscribe_tracking(self, db: AsyncSession):
        """Check newly synced emails against unsubscribe tracking records.

        If a sender domain has been unsubscribed from but new emails arrive,
        increment the counter so the UI can warn the user.
        """
        from backend.models.ai import UnsubscribeTracking

        # Get the user who owns this account
        account = await self._get_account(db)
        user_id = account.user_id

        # Get all tracked unsubscribe domains for this user
        tracking_result = await db.execute(
            select(UnsubscribeTracking).where(
                UnsubscribeTracking.user_id == user_id,
            )
        )
        tracking_records = tracking_result.scalars().all()
        if not tracking_records:
            return

        # Build a lookup of domain -> tracking record
        domain_tracking = {}
        for t in tracking_records:
            existing = domain_tracking.get(t.sender_domain)
            if not existing or t.unsubscribed_at > existing.unsubscribed_at:
                domain_tracking[t.sender_domain] = t

        # Find emails from tracked domains that arrived after the unsubscribe
        for domain, tracking in domain_tracking.items():
            count_result = await db.scalar(
                select(func.count(Email.id)).where(
                    Email.account_id == self.account_id,
                    Email.from_address.ilike(f"%@{domain}"),
                    Email.date > tracking.unsubscribed_at,
                    Email.is_trash == False,
                    Email.is_spam == False,
                )
            )
            new_count = count_result or 0

            if new_count != tracking.emails_received_after:
                tracking.emails_received_after = new_count
                if new_count > 0:
                    # Get the date of the latest email from this domain after unsubscribe
                    latest_result = await db.scalar(
                        select(func.max(Email.date)).where(
                            Email.account_id == self.account_id,
                            Email.from_address.ilike(f"%@{domain}"),
                            Email.date > tracking.unsubscribed_at,
                            Email.is_trash == False,
                            Email.is_spam == False,
                        )
                    )
                    tracking.last_email_after_at = latest_result

        await db.commit()

    async def _resolve_thread_id(self, db: AsyncSession, parsed: dict) -> tuple[str, str | None]:
        """Check if this email should be merged into an existing thread
        based on In-Reply-To / References headers.

        Returns (resolved_thread_id, original_thread_id_if_merged).
        The second value is non-None only when a merge was detected, and
        holds the original Gmail thread ID that should be retired.
        """
        gmail_thread_id = parsed["gmail_thread_id"]
        in_reply_to = parsed.get("in_reply_to")
        references = parsed.get("references_header")

        # --- Check In-Reply-To first (most direct link) ---
        if in_reply_to and in_reply_to.strip():
            result = await db.execute(
                select(Email.gmail_thread_id).where(
                    Email.message_id_header == in_reply_to.strip(),
                    Email.account_id == self.account_id,
                ).limit(1)
            )
            parent_thread_id = result.scalar_one_or_none()

            if parent_thread_id and parent_thread_id != gmail_thread_id:
                logger.info(
                    f"Thread merge: email replies to message in thread {parent_thread_id}, "
                    f"overriding Gmail thread {gmail_thread_id}"
                )
                return parent_thread_id, gmail_thread_id

        # --- Fallback: walk the References chain (most recent first) ---
        if references and references.strip():
            ref_ids = references.strip().split()
            for ref_id in reversed(ref_ids):
                ref_id = ref_id.strip()
                if not ref_id:
                    continue
                if in_reply_to and ref_id == in_reply_to.strip():
                    continue
                result = await db.execute(
                    select(Email.gmail_thread_id).where(
                        Email.message_id_header == ref_id,
                        Email.account_id == self.account_id,
                    ).limit(1)
                )
                parent_thread_id = result.scalar_one_or_none()
                if parent_thread_id and parent_thread_id != gmail_thread_id:
                    logger.info(
                        f"Thread merge (via References): email references message in "
                        f"thread {parent_thread_id}, overriding Gmail thread {gmail_thread_id}"
                    )
                    return parent_thread_id, gmail_thread_id

        return gmail_thread_id, None

    async def _upsert_email(self, db: AsyncSession, parsed: dict) -> tuple[int, bool]:
        """Insert or update an email record.

        Performs header-based thread merging before insert/update: if the
        email's In-Reply-To header points to a message stored under a
        different Gmail thread ID, the email (and any siblings already in
        the orphan thread) are migrated to the canonical thread.

        Returns (email_id, is_new) where is_new is True if this was a new insert.
        """
        # Resolve thread ID via In-Reply-To / References headers
        resolved_thread_id, orphan_thread_id = await self._resolve_thread_id(db, parsed)
        if orphan_thread_id:
            parsed["gmail_thread_id"] = resolved_thread_id

            # Migrate any other emails already stored with the orphan thread ID
            await db.execute(
                update(Email)
                .where(
                    Email.gmail_thread_id == orphan_thread_id,
                    Email.account_id == self.account_id,
                )
                .values(gmail_thread_id=resolved_thread_id)
            )

            # Delete the orphaned ThreadDigest so it gets regenerated
            # for the merged thread during the next digest pass.
            from backend.models.ai import ThreadDigest
            await db.execute(
                delete(ThreadDigest)
                .where(
                    ThreadDigest.gmail_thread_id == orphan_thread_id,
                    ThreadDigest.account_id == self.account_id,
                )
            )

        result = await db.execute(
            select(Email).where(
                Email.gmail_message_id == parsed["gmail_message_id"],
                Email.account_id == self.account_id,
            )
        )
        existing = result.scalar_one_or_none()

        attachments_data = parsed.pop("attachments", [])

        if existing:
            for key, value in parsed.items():
                setattr(existing, key, value)
            email = existing
            is_new = False
        else:
            email = Email(account_id=self.account_id, **parsed)
            db.add(email)
            await db.flush()
            is_new = True

        # Handle attachments
        if attachments_data and not existing:
            for att_data in attachments_data:
                att = Attachment(
                    email_id=email.id,
                    gmail_attachment_id=att_data.get("attachment_id", ""),
                    filename=att_data.get("filename", ""),
                    content_type=att_data.get("content_type", ""),
                    size_bytes=att_data.get("size_bytes", 0),
                    is_inline=att_data.get("is_inline", False),
                    content_id=att_data.get("content_id"),
                )
                db.add(att)

        return (email.id, is_new)
