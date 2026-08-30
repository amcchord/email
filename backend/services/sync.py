import asyncio
import base64
import binascii
import json
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
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


class IncrementalSyncCheckpointConflict(RuntimeError):
    """Raised when another incremental sync advances the checkpoint first."""


class FullSyncCheckpointConflict(RuntimeError):
    """Raised when a full-sync checkpoint no longer matches durable state."""


@dataclass(frozen=True)
class FullSyncCheckpoint:
    baseline_history_id: str
    phase: str
    page_token: str | None = None


_FULL_SYNC_CHECKPOINT_PREFIX = "gmail-full:v1:"
_SYNC_ADVISORY_LOCK_NAMESPACE = 0x4D41494C  # "MAIL"


def _validate_history_transition(expected_history_id: str, new_history_id: str):
    try:
        expected_numeric = int(expected_history_id)
        new_numeric = int(new_history_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Gmail history IDs must be numeric") from exc
    if expected_numeric < 0 or new_numeric < expected_numeric:
        raise RuntimeError("Gmail history checkpoint cannot move backwards")


def _normalized_history_id(value) -> str | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return str(numeric) if numeric >= 0 else None


def _encode_full_sync_checkpoint(checkpoint: FullSyncCheckpoint) -> str:
    _validate_history_transition(
        checkpoint.baseline_history_id,
        checkpoint.baseline_history_id,
    )
    if checkpoint.phase not in {"scan", "replay"}:
        raise ValueError("Invalid full sync checkpoint phase")
    if checkpoint.phase == "replay" and checkpoint.page_token is not None:
        raise ValueError("Replay checkpoints cannot contain a page token")
    if checkpoint.page_token is not None and (
        not isinstance(checkpoint.page_token, str) or not checkpoint.page_token
    ):
        raise ValueError("Invalid full sync page token")

    payload = json.dumps(
        {
            "baseline": checkpoint.baseline_history_id,
            "page": checkpoint.page_token,
            "phase": checkpoint.phase,
            "version": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{_FULL_SYNC_CHECKPOINT_PREFIX}{encoded}"


def _decode_full_sync_checkpoint(value: str | None) -> FullSyncCheckpoint | None:
    if not isinstance(value, str) or not value.startswith(_FULL_SYNC_CHECKPOINT_PREFIX):
        return None
    encoded = value.removeprefix(_FULL_SYNC_CHECKPOINT_PREFIX)
    try:
        padded = encoded + ("=" * (-len(encoded) % 4))
        payload = json.loads(base64.b64decode(
            padded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        ))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return None
        checkpoint = FullSyncCheckpoint(
            baseline_history_id=str(payload["baseline"]),
            phase=payload["phase"],
            page_token=payload.get("page"),
        )
        # Re-encoding validates types, numeric baseline, phase, and page shape.
        _encode_full_sync_checkpoint(checkpoint)
        return checkpoint
    except (
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        return None


def _require_complete_message_batch(
    requested_ids: list[str],
    messages: list[dict],
) -> list[dict]:
    """Return messages in request order, or fail if Gmail returned a partial batch."""
    requested = list(requested_ids)
    requested_set = set(requested)
    messages_by_id = {
        str(message.get("id")): message
        for message in messages
        if isinstance(message, dict) and message.get("id")
    }
    returned_ids = set(messages_by_id)
    missing_count = len(requested_set - returned_ids)
    unexpected_count = len(returned_ids - requested_set)
    duplicate_or_malformed_count = len(messages) - len(messages_by_id)

    if (
        len(requested) != len(requested_set)
        or missing_count
        or unexpected_count
        or duplicate_or_malformed_count
    ):
        raise RuntimeError(
            "Gmail message batch incomplete: "
            f"missing {missing_count}, unexpected {unexpected_count}, "
            f"duplicate or malformed {duplicate_or_malformed_count}"
        )

    return [messages_by_id[message_id] for message_id in requested]


class EmailSyncService:
    def __init__(self, account_id: int):
        self.account_id = account_id
        self._token_persisted = False

    @asynccontextmanager
    async def _account_sync_lock(self):
        """Hold one PostgreSQL transaction advisory lock for the whole sync."""
        async with async_session() as lock_db:
            result = await lock_db.execute(
                text(
                    "SELECT pg_try_advisory_xact_lock(:namespace, :account_id)"
                ),
                {
                    "namespace": _SYNC_ADVISORY_LOCK_NAMESPACE,
                    "account_id": self.account_id,
                },
            )
            acquired = bool(result.scalar_one())
            if not acquired:
                yield False
                return

            try:
                yield True
            finally:
                # Ending this dedicated transaction releases the xact lock
                # before the connection can return to the pool.
                await lock_db.rollback()

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

    async def _commit_incremental_checkpoint(
        self,
        db: AsyncSession,
        *,
        expected_history_id: str,
        new_history_id: str,
        mark_completed: bool,
    ):
        """Commit mail changes only if this sync still owns its starting checkpoint."""
        _validate_history_transition(expected_history_id, new_history_id)

        values = {
            "last_history_id": new_history_id,
            "last_incremental_sync": datetime.now(timezone.utc),
        }
        if mark_completed:
            values.update(status="completed", current_phase=None)

        result = await db.execute(
            update(SyncStatus)
            .where(
                SyncStatus.account_id == self.account_id,
                SyncStatus.last_history_id == expected_history_id,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise IncrementalSyncCheckpointConflict(
                "Incremental sync checkpoint changed during processing"
            )
        await db.commit()

    async def _cas_full_checkpoint(
        self,
        db: AsyncSession,
        *,
        expected_baseline: str | None,
        expected_checkpoint: str | None,
        values: dict,
    ):
        """Update a full-sync checkpoint only while its exact owner still matches."""
        result = await db.execute(
            update(SyncStatus)
            .where(
                SyncStatus.account_id == self.account_id,
                SyncStatus.last_history_id == expected_baseline,
                SyncStatus.sync_page_token == expected_checkpoint,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise FullSyncCheckpointConflict(
                "Full sync checkpoint changed during processing"
            )
        await db.commit()

    async def _mark_incremental_syncing(
        self,
        db: AsyncSession,
        *,
        expected_history_id: str,
        change_count: int,
    ):
        """Publish progress only while the starting checkpoint is still current."""
        result = await db.execute(
            update(SyncStatus)
            .where(
                SyncStatus.account_id == self.account_id,
                SyncStatus.last_history_id == expected_history_id,
            )
            .values(
                status="syncing",
                current_phase=f"Syncing {change_count} changes",
                error_message=None,
            )
        )
        if result.rowcount != 1:
            raise IncrementalSyncCheckpointConflict(
                "Incremental sync checkpoint changed before processing"
            )
        await db.commit()

    async def _apply_history_changes(
        self,
        db: AsyncSession,
        gmail: GmailService,
        history: list[dict],
        new_email_ids: list[int],
        *,
        context: str,
    ) -> tuple[int, int]:
        """Apply one complete Gmail history replay without committing."""
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

        for message_id in sorted(messages_to_delete):
            result = await db.execute(
                select(Email).where(
                    Email.gmail_message_id == message_id,
                    Email.account_id == self.account_id,
                )
            )
            email = result.scalar_one_or_none()
            if email:
                await db.delete(email)

        fetch_list = sorted(messages_to_fetch - messages_to_delete)
        if fetch_list:
            messages = await gmail.batch_get_messages(fetch_list)
            messages = _require_complete_message_batch(fetch_list, messages)
            for message_id, message in zip(fetch_list, messages):
                try:
                    async with db.begin_nested():
                        parsed = GmailService.parse_message(message)
                        email_id, is_new = await self._upsert_email(db, parsed)
                        if is_new:
                            new_email_ids.append(email_id)
                except Exception as message_error:
                    logger.warning(
                        "%s could not process message %s: %s",
                        context,
                        message_id,
                        message_error,
                    )
                    raise RuntimeError(
                        f"{context} incomplete: a changed message could not be processed"
                    ) from message_error

        return len(fetch_list), len(messages_to_delete)

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
        """Run a full sync when this process owns the account-wide DB lock."""
        async with self._account_sync_lock() as acquired:
            if not acquired:
                logger.info(
                    "Skipping full sync for account %s; another sync owns the lock",
                    self.account_id,
                )
                return []
            return await self._full_sync_locked()

    async def _full_sync_locked(self) -> list[int]:
        """Scan all messages, then reconcile changes since the owned baseline."""
        try:
            async with async_session() as db:
                account = await self._get_account(db)
                gmail = await self._create_gmail_service(db, account)
                result = await db.execute(
                    select(SyncStatus).where(
                        SyncStatus.account_id == self.account_id
                    )
                )
                sync = result.scalar_one_or_none()
                raw_checkpoint = sync.sync_page_token if sync else None
                checkpoint = _decode_full_sync_checkpoint(raw_checkpoint)
                safe_resume = bool(
                    checkpoint
                    and sync
                    and _normalized_history_id(sync.last_history_id)
                    == checkpoint.baseline_history_id
                )

                if safe_resume:
                    checkpoint_value = raw_checkpoint
                    await self._cas_full_checkpoint(
                        db,
                        expected_baseline=checkpoint.baseline_history_id,
                        expected_checkpoint=checkpoint_value,
                        values={
                            "status": "syncing",
                            "current_phase": (
                                "Reconciling changes"
                                if checkpoint.phase == "replay"
                                else "Syncing messages"
                            ),
                            "started_at": datetime.now(timezone.utc),
                            "error_message": None,
                        },
                    )
                    logger.info(
                        "Resuming full sync for account %s from %s checkpoint",
                        self.account_id,
                        checkpoint.phase,
                    )
                else:
                    existing_baseline = (
                        _normalized_history_id(sync.last_history_id)
                        if sync and raw_checkpoint is None
                        else None
                    )
                    baseline = (
                        existing_baseline
                        or await gmail.get_profile_history_id()
                    )
                    checkpoint = FullSyncCheckpoint(
                        baseline_history_id=baseline,
                        phase="scan",
                    )
                    checkpoint_value = _encode_full_sync_checkpoint(checkpoint)
                    values = {
                        "last_history_id": baseline,
                        "sync_page_token": checkpoint_value,
                        "status": "syncing",
                        "current_phase": "Starting sync",
                        "started_at": datetime.now(timezone.utc),
                        "error_message": None,
                        "messages_synced": 0,
                    }
                    if sync:
                        await self._cas_full_checkpoint(
                            db,
                            expected_baseline=sync.last_history_id,
                            expected_checkpoint=raw_checkpoint,
                            values=values,
                        )
                    else:
                        db.add(SyncStatus(account_id=self.account_id, **values))
                        await db.commit()
                    logger.info(
                        "Starting full sync for account %s at history %s",
                        self.account_id,
                        baseline,
                    )

            new_email_ids = []
            synced_count = (
                int(sync.messages_synced or 0)
                if safe_resume and sync
                else 0
            )
            total_estimate = (
                int(sync.total_messages or 0)
                if safe_resume and sync
                else 0
            )
            batch_size = 100

            while True:
                if checkpoint.phase == "scan":
                    messages, next_page, estimate = await gmail.list_message_ids(
                        page_token=checkpoint.page_token
                    )
                    page_ids = [message["id"] for message in messages]
                    if not total_estimate and estimate:
                        total_estimate = estimate

                    # Refresh every listed row, including messages already in
                    # the database. This makes a resumed page idempotent and
                    # repairs stale labels, bodies, and attachment metadata.
                    for offset in range(0, len(page_ids), batch_size):
                        batch_ids = page_ids[offset:offset + batch_size]
                        fetched = await gmail.batch_get_messages(batch_ids)
                        fetched = _require_complete_message_batch(batch_ids, fetched)

                        async with async_session() as db:
                            for message_id, message in zip(batch_ids, fetched):
                                try:
                                    async with db.begin_nested():
                                        parsed = GmailService.parse_message(message)
                                        email_id, is_new = await self._upsert_email(db, parsed)
                                        if is_new:
                                            new_email_ids.append(email_id)
                                except Exception as message_error:
                                    logger.warning(
                                        "Full sync could not process message %s: %s",
                                        message_id,
                                        message_error,
                                    )
                                    raise RuntimeError(
                                        "Full sync incomplete: a requested message "
                                        "could not be processed"
                                    ) from message_error
                            await db.commit()
                        synced_count += len(batch_ids)
                        await asyncio.sleep(1)

                    next_checkpoint = FullSyncCheckpoint(
                        baseline_history_id=checkpoint.baseline_history_id,
                        phase="scan" if next_page else "replay",
                        page_token=next_page,
                    )
                    next_checkpoint_value = _encode_full_sync_checkpoint(next_checkpoint)
                    phase_message = f"Syncing: {synced_count} messages refreshed"
                    if total_estimate:
                        phase_message += f" (est. {total_estimate} total)"
                    async with async_session() as db:
                        await self._cas_full_checkpoint(
                            db,
                            expected_baseline=checkpoint.baseline_history_id,
                            expected_checkpoint=checkpoint_value,
                            values={
                                "sync_page_token": next_checkpoint_value,
                                "messages_synced": synced_count,
                                "total_messages": total_estimate,
                                "current_phase": (
                                    "Reconciling changes"
                                    if next_checkpoint.phase == "replay"
                                    else phase_message
                                ),
                                "started_at": datetime.now(timezone.utc),
                            },
                        )
                    checkpoint = next_checkpoint
                    checkpoint_value = next_checkpoint_value
                    if checkpoint.phase == "scan":
                        await asyncio.sleep(0.5)
                        continue

                history_result = await gmail.get_history(
                    checkpoint.baseline_history_id,
                    max_retries=1,
                )
                if history_result is None:
                    # The owned baseline expired while scanning. Capture a
                    # fresh baseline, retain an encoded owner, and safely
                    # restart from page one.
                    fresh_baseline = await gmail.get_profile_history_id()
                    restart_checkpoint = FullSyncCheckpoint(
                        baseline_history_id=fresh_baseline,
                        phase="scan",
                    )
                    restart_value = _encode_full_sync_checkpoint(restart_checkpoint)
                    async with async_session() as db:
                        await self._cas_full_checkpoint(
                            db,
                            expected_baseline=checkpoint.baseline_history_id,
                            expected_checkpoint=checkpoint_value,
                            values={
                                "last_history_id": fresh_baseline,
                                "sync_page_token": restart_value,
                                "status": "syncing",
                                "current_phase": "Restarting full sync",
                                "started_at": datetime.now(timezone.utc),
                                "messages_synced": 0,
                            },
                        )
                    checkpoint = restart_checkpoint
                    checkpoint_value = restart_value
                    synced_count = 0
                    total_estimate = 0
                    continue

                history = history_result.get("history", [])
                high_water = (
                    history_result.get("new_history_id")
                    or checkpoint.baseline_history_id
                )
                _validate_history_transition(
                    checkpoint.baseline_history_id,
                    high_water,
                )

                await self._persist_refreshed_token(gmail)
                await self.sync_labels()

                async with async_session() as db:
                    updated_count, deleted_count = await self._apply_history_changes(
                        db,
                        gmail,
                        history,
                        new_email_ids,
                        context="Full sync replay",
                    )
                    await db.flush()
                    await db.execute(text("""
                        UPDATE emails SET search_vector =
                            setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
                            setweight(to_tsvector('english', coalesce(from_name, '')), 'B') ||
                            setweight(to_tsvector('english', coalesce(from_address, '')), 'B') ||
                            setweight(to_tsvector('english', coalesce(snippet, '')), 'C') ||
                            setweight(to_tsvector('english', coalesce(left(body_text, 10000), '')), 'D')
                        WHERE account_id = :account_id AND search_vector IS NULL
                    """), {"account_id": self.account_id})
                    total_in_db = await db.scalar(
                        select(func.count(Email.id)).where(
                            Email.account_id == self.account_id
                        )
                    ) or 0
                    await self._cas_full_checkpoint(
                        db,
                        expected_baseline=checkpoint.baseline_history_id,
                        expected_checkpoint=checkpoint_value,
                        values={
                            "status": "completed",
                            "current_phase": None,
                            "last_full_sync": datetime.now(timezone.utc),
                            "last_history_id": high_water,
                            "completed_at": datetime.now(timezone.utc),
                            "messages_synced": total_in_db,
                            "total_messages": total_in_db,
                            "sync_page_token": None,
                        },
                    )

                logger.info(
                    "Full sync complete: %s scanned, %s replayed, %s deleted "
                    "(%s new) for account %s",
                    synced_count,
                    updated_count,
                    deleted_count,
                    len(new_email_ids),
                    self.account_id,
                )
                return new_email_ids

        except FullSyncCheckpointConflict:
            logger.info(
                "Full sync checkpoint conflict for account %s; stale work stopped",
                self.account_id,
            )
            raise
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
        """Run an incremental sync under the account-wide DB lock."""
        async with self._account_sync_lock() as acquired:
            if not acquired:
                logger.info(
                    "Skipping incremental sync for account %s; another sync owns the lock",
                    self.account_id,
                )
                return []
            return await self._incremental_sync_locked()

    async def _incremental_sync_locked(self) -> list[int]:
        """Sync only changes since last sync.

        Does NOT set status to 'syncing' upfront -- incremental syncs are
        lightweight and should be invisible in the UI unless there are
        actual changes to process.

        Returns a list of newly inserted email IDs (DB primary keys).
        """
        resume_full_sync = False
        async with async_session() as db:
            result = await db.execute(
                select(SyncStatus).where(SyncStatus.account_id == self.account_id)
            )
            sync = result.scalar_one_or_none()

            if not sync or not sync.last_history_id:
                resume_full_sync = True
            elif sync.sync_page_token:
                # An earlier full sync was interrupted and left a
                # checkpoint.  Continue from where it left off rather
                # than doing an incremental sync that would skip all
                # the un-fetched historical messages.
                logger.info(
                    f"Resuming interrupted full sync for account "
                    f"{self.account_id} (checkpoint exists)"
                )
                resume_full_sync = True

            if not resume_full_sync:
                last_history_id = sync.last_history_id
                # Create the Gmail service once for the whole incremental sync
                account = await self._get_account(db)
                gmail = await self._create_gmail_service(db, account)

        if resume_full_sync:
            return await self._full_sync_locked()

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
                return await self._full_sync_locked()

            history = history_result.get("history", [])
            new_history_id = history_result.get("new_history_id")

            if not history:
                # A complete empty response can still carry a newer Gmail
                # high-water. Advance it atomically without fetching mail.
                async with async_session() as db:
                    await self._commit_incremental_checkpoint(
                        db,
                        expected_history_id=last_history_id,
                        new_history_id=new_history_id or last_history_id,
                        mark_completed=False,
                    )
                return []

            # There are actual changes -- process in a single session
            async with async_session() as db:
                change_count = len(history)
                await self._mark_incremental_syncing(
                    db,
                    expected_history_id=last_history_id,
                    change_count=change_count,
                )

                updated_count, deleted_count = await self._apply_history_changes(
                    db,
                    gmail,
                    history,
                    new_email_ids,
                    context="Incremental sync",
                )

                await self._commit_incremental_checkpoint(
                    db,
                    expected_history_id=last_history_id,
                    new_history_id=new_history_id or last_history_id,
                    mark_completed=True,
                )
                logger.info(
                    f"Incremental sync: {updated_count} updated ({len(new_email_ids)} new), "
                    f"{deleted_count} deleted for account {self.account_id}"
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
            if isinstance(e, IncrementalSyncCheckpointConflict):
                logger.info(
                    "Incremental sync checkpoint conflict for account %s; "
                    "mail changes were rolled back",
                    self.account_id,
                )
                raise
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
