import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from backend.models.email import Email, Attachment, EmailLabel
from backend.models.account import GoogleAccount, SyncStatus
from backend.services.gmail import GmailService
from backend.services.credentials import get_google_credentials
from backend.utils.security import encrypt_value
from backend.database import async_session

logger = logging.getLogger(__name__)


class EmailSyncService:
    def __init__(self, account_id: int):
        self.account_id = account_id

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
        """Save refreshed access token back to the DB if it changed."""
        new_token = gmail.get_refreshed_token()
        if new_token:
            async with async_session() as db:
                account = await self._get_account(db)
                account.encrypted_access_token = encrypt_value(new_token)
                await db.commit()
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

    async def full_sync(self):
        """Perform a full email sync, skipping messages already in the DB."""
        async with async_session() as db:
            account = await self._get_account(db)

            await self._update_sync_status(
                db,
                status="syncing",
                current_phase="Collecting message IDs",
                started_at=datetime.now(timezone.utc),
                error_message=None,
            )

        try:
            # Phase 1: Collect all message IDs from Gmail
            all_message_ids = []
            page_token = None
            total_estimate = 0

            logger.info(f"Starting full sync for account {self.account_id}")

            while True:
                async with async_session() as db:
                    account = await self._get_account(db)
                    gmail = await self._create_gmail_service(db, account)
                    messages, next_page, estimate = await gmail.list_message_ids(
                        page_token=page_token
                    )
                    await self._persist_refreshed_token(gmail)

                all_message_ids.extend([m["id"] for m in messages])
                if total_estimate == 0:
                    total_estimate = estimate
                page_token = next_page

                async with async_session() as db:
                    await self._update_sync_status(
                        db,
                        current_phase=f"Collecting IDs: {len(all_message_ids)} found",
                    )

                if not page_token:
                    break

                # Pace between list pages to respect quota
                await asyncio.sleep(1)

            logger.info(f"Found {len(all_message_ids)} total messages in Gmail for account {self.account_id}")

            # Phase 1.5: Filter out messages we already have in the DB
            async with async_session() as db:
                result = await db.execute(
                    select(Email.gmail_message_id).where(
                        Email.account_id == self.account_id
                    )
                )
                existing_ids = set(r[0] for r in result.all())

            new_message_ids = [mid for mid in all_message_ids if mid not in existing_ids]
            skipped_count = len(all_message_ids) - len(new_message_ids)
            total_to_fetch = len(new_message_ids)

            logger.info(f"Skipping {skipped_count} already-synced messages, "
                         f"fetching {total_to_fetch} new messages")

            async with async_session() as db:
                await self._update_sync_status(
                    db,
                    total_messages=total_to_fetch,
                    messages_synced=0,
                    current_phase=f"Fetching {total_to_fetch} new emails (skipped {skipped_count} existing)",
                )

            # Phase 2: Fetch only new messages in batches
            synced_count = 0
            batch_size = 25
            latest_history_id = None

            for i in range(0, len(new_message_ids), batch_size):
                batch_ids = new_message_ids[i:i + batch_size]

                async with async_session() as db:
                    account = await self._get_account(db)
                    gmail = await self._create_gmail_service(db, account)
                    messages = await gmail.batch_get_messages(batch_ids)
                    await self._persist_refreshed_token(gmail)

                async with async_session() as db:
                    batch_ok = 0
                    for msg in messages:
                        try:
                            parsed = GmailService.parse_message(msg)
                            history_id = parsed.get("gmail_history_id", "")
                            if history_id:
                                if latest_history_id is None or int(history_id) > int(latest_history_id):
                                    latest_history_id = history_id

                            await self._upsert_email(db, parsed)
                            batch_ok += 1
                        except Exception as msg_err:
                            msg_id = msg.get("id", "unknown")
                            logger.warning(f"Skipping message {msg_id}: {msg_err}")
                            await db.rollback()

                    synced_count += batch_ok
                    await self._update_sync_status(
                        db,
                        messages_synced=synced_count,
                        total_messages=total_to_fetch,
                        current_phase=f"Fetching emails: {synced_count}/{total_to_fetch}",
                    )
                    await db.commit()

                # Pace between outer batches to stay under per-minute quota
                await asyncio.sleep(3)

            # Update search vectors
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
                await db.commit()

            # Get the max history_id from all messages in DB (including previously synced)
            async with async_session() as db:
                from sqlalchemy import func as sa_func
                result = await db.execute(
                    select(sa_func.max(Email.gmail_history_id)).where(
                        Email.account_id == self.account_id,
                        Email.gmail_history_id.isnot(None),
                        Email.gmail_history_id != "",
                    )
                )
                db_max_history = result.scalar_one_or_none()
                if db_max_history:
                    if latest_history_id is None or int(db_max_history) > int(latest_history_id or 0):
                        latest_history_id = db_max_history

            # Mark sync complete -- count all messages in the DB for this account
            async with async_session() as db:
                from sqlalchemy import func as sa_count
                total_in_db = await db.scalar(
                    select(sa_count.count(Email.id)).where(
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
                )

            # Sync labels
            await self.sync_labels()

            logger.info(f"Full sync complete: {synced_count} messages for account {self.account_id}")

        except Exception as e:
            logger.error(f"Full sync error for account {self.account_id}: {e}")
            async with async_session() as db:
                await self._update_sync_status(
                    db,
                    status="error",
                    error_message=str(e),
                    current_phase=None,
                    completed_at=datetime.now(timezone.utc),
                )
            raise

    async def incremental_sync(self):
        """Sync only changes since last sync."""
        async with async_session() as db:
            result = await db.execute(
                select(SyncStatus).where(SyncStatus.account_id == self.account_id)
            )
            sync = result.scalar_one_or_none()

            if not sync or not sync.last_history_id:
                # No previous sync, do full sync
                await self.full_sync()
                return

            last_history_id = sync.last_history_id

        # Set status to syncing
        async with async_session() as db:
            await self._update_sync_status(
                db,
                status="syncing",
                current_phase="Incremental sync",
                error_message=None,
            )

        try:
            async with async_session() as db:
                account = await self._get_account(db)
                gmail = await self._create_gmail_service(db, account)

                history_result = await gmail.get_history(last_history_id)
                await self._persist_refreshed_token(gmail)

                if history_result is None:
                    # History expired, need full sync
                    logger.info("History expired, performing full sync")
                    await self.full_sync()
                    return

                history = history_result.get("history", [])
                new_history_id = history_result.get("new_history_id")

                if not history:
                    # No changes
                    await self._update_sync_status(
                        db,
                        status="completed",
                        current_phase=None,
                        last_incremental_sync=datetime.now(timezone.utc),
                    )
                    return

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
                        await self._persist_refreshed_token(gmail)
                        for msg in messages:
                            try:
                                parsed = GmailService.parse_message(msg)
                                await self._upsert_email(db, parsed)
                            except Exception as msg_err:
                                msg_id = msg.get("id", "unknown")
                                logger.warning(f"Skipping message {msg_id} in incremental sync: {msg_err}")
                                await db.rollback()

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
                    f"Incremental sync: {len(messages_to_fetch)} updated, "
                    f"{len(messages_to_delete)} deleted for account {self.account_id}"
                )

        except Exception as e:
            logger.error(f"Incremental sync error for account {self.account_id}: {e}")
            async with async_session() as db:
                await self._update_sync_status(
                    db,
                    status="error",
                    error_message=str(e),
                    current_phase=None,
                )
            raise

    async def _upsert_email(self, db: AsyncSession, parsed: dict):
        """Insert or update an email record."""
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
        else:
            email = Email(account_id=self.account_id, **parsed)
            db.add(email)
            await db.flush()

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
