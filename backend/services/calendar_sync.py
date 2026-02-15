import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from backend.models.calendar import CalendarEvent, CalendarSyncStatus
from backend.models.account import GoogleAccount
from backend.services.google_calendar import GoogleCalendarService
from backend.services.credentials import get_google_credentials
from backend.database import async_session
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


def _is_scope_error(error) -> bool:
    """Check if an HttpError is an insufficient-scopes / permission error."""
    if not isinstance(error, HttpError):
        return False
    status = getattr(error.resp, 'status', 0) if hasattr(error, 'resp') else 0
    if status == 403:
        msg = str(error).lower()
        if 'insufficient' in msg or 'scope' in msg or 'permission' in msg:
            return True
    return False


class CalendarSyncService:
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

    async def _create_calendar_service(self, db: AsyncSession, account: GoogleAccount) -> GoogleCalendarService:
        client_id, client_secret = await get_google_credentials(db)
        return GoogleCalendarService(account, client_id=client_id, client_secret=client_secret)

    async def _check_calendar_scope(self, account: GoogleAccount) -> bool:
        """Check if this account has the calendar.readonly scope authorized."""
        import json
        scopes_str = account.scopes or "[]"
        try:
            scopes = json.loads(scopes_str)
        except (json.JSONDecodeError, TypeError):
            scopes = []
        return "https://www.googleapis.com/auth/calendar.readonly" in scopes

    async def _update_sync_status(self, db: AsyncSession, **kwargs):
        result = await db.execute(
            select(CalendarSyncStatus).where(CalendarSyncStatus.account_id == self.account_id)
        )
        sync = result.scalar_one_or_none()
        if not sync:
            sync = CalendarSyncStatus(account_id=self.account_id)
            db.add(sync)

        for key, value in kwargs.items():
            setattr(sync, key, value)
        await db.commit()

    async def _upsert_event(self, db: AsyncSession, parsed: dict):
        """Insert or update a calendar event matching on (account_id, google_event_id)."""
        result = await db.execute(
            select(CalendarEvent).where(
                CalendarEvent.account_id == self.account_id,
                CalendarEvent.google_event_id == parsed["google_event_id"],
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in parsed.items():
                setattr(existing, key, value)
        else:
            event = CalendarEvent(**parsed)
            db.add(event)

    async def full_sync(self):
        """Full sync: fetch events from 6 months ago to 12 months ahead.

        Uses singleEvents=true to expand recurring events into instances.
        Stores the nextSyncToken for future incremental syncs.
        """
        async with async_session() as db:
            account = await self._get_account(db)

            # Check if account has calendar scope before attempting sync
            if not await self._check_calendar_scope(account):
                logger.info(
                    f"Account {self.account_id} ({account.email}) does not have "
                    f"calendar.readonly scope -- skipping calendar sync. "
                    f"Reauthorize the account to enable calendar."
                )
                await self._update_sync_status(
                    db,
                    status="error",
                    error_message="Calendar scope not authorized. Reauthorize this account to enable calendar sync.",
                    completed_at=datetime.now(timezone.utc),
                )
                return

            cal_service = await self._create_calendar_service(db, account)

            await self._update_sync_status(
                db,
                status="syncing",
                started_at=datetime.now(timezone.utc),
                error_message=None,
            )

        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=180)).isoformat()
        time_max = (now + timedelta(days=365)).isoformat()

        total_synced = 0
        next_sync_token = None
        page_token = None

        try:
            while True:
                result = await cal_service.list_events(
                    time_min=time_min,
                    time_max=time_max,
                    page_token=page_token,
                    max_results=250,
                    single_events=True,
                )

                events = result.get("items", [])

                async with async_session() as db:
                    for event_dict in events:
                        try:
                            parsed = GoogleCalendarService.parse_event(event_dict, self.account_id)
                            await self._upsert_event(db, parsed)
                            total_synced += 1
                        except Exception as e:
                            event_id = event_dict.get("id", "unknown")
                            logger.warning(f"Skipping calendar event {event_id}: {e}")
                    await db.commit()

                page_token = result.get("nextPageToken")
                next_sync_token = result.get("nextSyncToken")

                if not page_token:
                    break
                await asyncio.sleep(0.3)

            # NOTE: Do NOT persist refreshed tokens from the calendar service.
            # The Gmail service handles token persistence.  If we persist here,
            # we risk narrowing the token scopes and breaking email sync.

            async with async_session() as db:
                await self._update_sync_status(
                    db,
                    status="completed",
                    sync_token=next_sync_token,
                    last_full_sync=datetime.now(timezone.utc),
                    events_synced=total_synced,
                    completed_at=datetime.now(timezone.utc),
                    error_message=None,
                )

            logger.info(f"Calendar full sync complete: {total_synced} events for account {self.account_id}")

        except HttpError as e:
            if _is_scope_error(e):
                logger.warning(
                    f"Calendar sync for account {self.account_id}: insufficient scopes. "
                    f"Account needs reauthorization for calendar access."
                )
                try:
                    async with async_session() as db:
                        await self._update_sync_status(
                            db,
                            status="error",
                            error_message="Calendar scope not authorized. Reauthorize this account to enable calendar sync.",
                            completed_at=datetime.now(timezone.utc),
                        )
                except Exception:
                    pass
                # Don't re-raise scope errors -- they're expected for old accounts
                return
            logger.error(f"Calendar full sync error for account {self.account_id}: {e}")
            try:
                async with async_session() as db:
                    await self._update_sync_status(
                        db,
                        status="error",
                        error_message=str(e)[:500],
                        completed_at=datetime.now(timezone.utc),
                    )
            except Exception:
                pass
            raise

        except Exception as e:
            logger.error(f"Calendar full sync error for account {self.account_id}: {e}")
            try:
                async with async_session() as db:
                    await self._update_sync_status(
                        db,
                        status="error",
                        error_message=str(e)[:500],
                        completed_at=datetime.now(timezone.utc),
                    )
            except Exception:
                pass
            raise

    async def incremental_sync(self):
        """Incremental sync using the stored sync token.

        Handles 410 Gone (token invalidated) by falling back to full sync.
        Handles cancelled events by deleting them from the DB.
        Handles 403 insufficient scopes gracefully (old accounts without calendar scope).
        """
        async with async_session() as db:
            account = await self._get_account(db)

            # Check if account has calendar scope before attempting sync
            if not await self._check_calendar_scope(account):
                # Silently skip -- no need to log every 5 minutes for old accounts
                return

            result = await db.execute(
                select(CalendarSyncStatus).where(CalendarSyncStatus.account_id == self.account_id)
            )
            sync_status = result.scalar_one_or_none()

            if not sync_status or not sync_status.sync_token:
                return await self.full_sync()

            sync_token = sync_status.sync_token
            cal_service = await self._create_calendar_service(db, account)

        total_updated = 0
        total_deleted = 0
        next_sync_token = None
        page_token = None

        try:
            while True:
                try:
                    result = await cal_service.list_events(
                        sync_token=sync_token if not page_token else None,
                        page_token=page_token,
                        max_results=250,
                    )
                except HttpError as e:
                    if e.resp.status == 410:
                        logger.info(f"Calendar sync token expired for account {self.account_id}, doing full sync")
                        async with async_session() as db:
                            await self._update_sync_status(db, sync_token=None)
                        return await self.full_sync()
                    if _is_scope_error(e):
                        logger.debug(f"Calendar sync skipped for account {self.account_id}: insufficient scopes")
                        return
                    raise

                events = result.get("items", [])

                async with async_session() as db:
                    for event_dict in events:
                        try:
                            if event_dict.get("status") == "cancelled":
                                del_result = await db.execute(
                                    select(CalendarEvent).where(
                                        CalendarEvent.account_id == self.account_id,
                                        CalendarEvent.google_event_id == event_dict.get("id", ""),
                                    )
                                )
                                existing = del_result.scalar_one_or_none()
                                if existing:
                                    await db.delete(existing)
                                    total_deleted += 1
                            else:
                                parsed = GoogleCalendarService.parse_event(event_dict, self.account_id)
                                await self._upsert_event(db, parsed)
                                total_updated += 1
                        except Exception as e:
                            event_id = event_dict.get("id", "unknown")
                            logger.warning(f"Skipping calendar event {event_id} in incremental sync: {e}")
                    await db.commit()

                page_token = result.get("nextPageToken")
                next_sync_token = result.get("nextSyncToken")

                if not page_token:
                    break
                await asyncio.sleep(0.3)

            # NOTE: Do NOT persist refreshed tokens here -- let Gmail handle it.

            async with async_session() as db:
                update_kwargs = {
                    "last_incremental_sync": datetime.now(timezone.utc),
                    "status": "completed",
                    "error_message": None,
                }
                if next_sync_token:
                    update_kwargs["sync_token"] = next_sync_token
                if total_updated > 0 or total_deleted > 0:
                    count = await db.scalar(
                        select(func.count(CalendarEvent.id)).where(
                            CalendarEvent.account_id == self.account_id
                        )
                    )
                    update_kwargs["events_synced"] = count or 0
                    update_kwargs["completed_at"] = datetime.now(timezone.utc)

                await self._update_sync_status(db, **update_kwargs)

            if total_updated > 0 or total_deleted > 0:
                logger.info(
                    f"Calendar incremental sync: {total_updated} updated, "
                    f"{total_deleted} deleted for account {self.account_id}"
                )

        except HttpError as e:
            if _is_scope_error(e):
                logger.debug(f"Calendar sync skipped for account {self.account_id}: insufficient scopes")
                return
            logger.error(f"Calendar incremental sync error for account {self.account_id}: {e}")
            try:
                async with async_session() as db:
                    await self._update_sync_status(
                        db,
                        status="error",
                        error_message=str(e)[:500],
                        completed_at=datetime.now(timezone.utc),
                    )
            except Exception:
                pass
            raise

        except Exception as e:
            logger.error(f"Calendar incremental sync error for account {self.account_id}: {e}")
            try:
                async with async_session() as db:
                    await self._update_sync_status(
                        db,
                        status="error",
                        error_message=str(e)[:500],
                        completed_at=datetime.now(timezone.utc),
                    )
            except Exception:
                pass
            raise
