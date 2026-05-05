import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from backend.models.calendar import CalendarEvent, CalendarSyncStatus
from backend.models.account import GoogleAccount
from backend.services.google_calendar import GoogleCalendarService
from backend.services.credentials import get_google_credentials
from backend.database import async_session
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

logger = logging.getLogger(__name__)

# How recently must we have synced for a transient failure to be considered
# "blip-y" enough to suppress the UI error?  The cron tick runs every 5 minutes,
# so 30 minutes covers ~6 ticks worth of intermittent failures.
RECENT_SUCCESS_WINDOW = timedelta(minutes=30)

REAUTH_MESSAGE = (
    "Calendar scope not authorized. Reauthorize this account to enable calendar sync."
)
TRANSIENT_MESSAGE = "Calendar sync temporarily failing -- will retry."


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


def _is_auth_error(error) -> bool:
    """Return True for errors that genuinely require the user to reauthorize.

    Includes:
      * scope errors (handled separately for messaging, but classified here too)
      * google.auth RefreshError (refresh token revoked / expired / invalid_grant)
      * HttpError 401 (unauthenticated)
    """
    if _is_scope_error(error):
        return True
    if isinstance(error, RefreshError):
        return True
    if isinstance(error, HttpError):
        status = getattr(error.resp, 'status', 0) if hasattr(error, 'resp') else 0
        if status == 401:
            return True
    return False


def _recently_succeeded(sync_status: CalendarSyncStatus,
                        threshold: timedelta = RECENT_SUCCESS_WINDOW) -> bool:
    """True if the account has had a successful sync within `threshold`.

    Used to suppress UI-visible errors for short-lived transient failures
    when we know calendar updates are still flowing.
    """
    if sync_status is None:
        return False
    candidates = []
    if sync_status.last_incremental_sync is not None:
        candidates.append(sync_status.last_incremental_sync)
    if sync_status.last_full_sync is not None:
        candidates.append(sync_status.last_full_sync)
    if not candidates:
        return False
    most_recent = max(candidates)
    if most_recent.tzinfo is None:
        most_recent = most_recent.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - most_recent) <= threshold


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

    async def _mark_calendar_scope_lost(self):
        """Remove calendar.readonly from the account's local scopes record.

        Called after Google returns a 403 insufficient-scope error so that
        the next 5-minute cron tick short-circuits via `_check_calendar_scope`
        instead of repeatedly hitting Google with a token that no longer
        carries the calendar grant.  The OAuth reauthorize callback will
        restore the full scope list once the user re-grants permission.
        """
        import json
        async with async_session() as db:
            account = await self._get_account(db)
            try:
                scopes = json.loads(account.scopes or "[]")
            except (json.JSONDecodeError, TypeError):
                scopes = []
            cal_scope = "https://www.googleapis.com/auth/calendar.readonly"
            if cal_scope in scopes:
                scopes = [s for s in scopes if s != cal_scope]
                account.scopes = json.dumps(scopes)
                await db.commit()
                logger.info(
                    f"Removed calendar scope from local record for account "
                    f"{self.account_id} -- reauth required to resume calendar sync"
                )

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

    async def _handle_sync_exception(self, error: Exception, sync_kind: str) -> None:
        """Persist sync error state, distinguishing auth vs transient failures.

        Auth errors (scope loss / RefreshError / 401) flip ``needs_reauth=True``
        so the UI shows the Reauthorize banner.  Other errors are treated as
        transient: if the account synced successfully within
        :data:`RECENT_SUCCESS_WINDOW`, we log only and leave the existing
        (likely "completed") status untouched so the UI stays clean.  If the
        last successful sync is older than the window, we surface a generic
        "temporarily failing" message without claiming reauth is needed.
        """
        if _is_auth_error(error):
            logger.warning(
                f"Calendar {sync_kind} sync auth error for account "
                f"{self.account_id}: {error}. Reauthorization required."
            )
            try:
                async with async_session() as db:
                    await self._update_sync_status(
                        db,
                        status="error",
                        error_message=REAUTH_MESSAGE,
                        needs_reauth=True,
                        completed_at=datetime.now(timezone.utc),
                    )
            except Exception:
                pass
            if _is_scope_error(error):
                try:
                    await self._mark_calendar_scope_lost()
                except Exception as exc:
                    logger.warning(
                        f"Failed to clear local calendar scope for account "
                        f"{self.account_id}: {exc}"
                    )
            return

        try:
            async with async_session() as db:
                result = await db.execute(
                    select(CalendarSyncStatus).where(
                        CalendarSyncStatus.account_id == self.account_id
                    )
                )
                sync_status = result.scalar_one_or_none()
        except Exception:
            sync_status = None

        if _recently_succeeded(sync_status):
            logger.warning(
                f"Calendar {sync_kind} sync transient error for account "
                f"{self.account_id} (recent success within "
                f"{int(RECENT_SUCCESS_WINDOW.total_seconds() / 60)}m, "
                f"suppressing UI error): {error}"
            )
            return

        logger.error(
            f"Calendar {sync_kind} sync error for account {self.account_id}: {error}"
        )
        try:
            async with async_session() as db:
                await self._update_sync_status(
                    db,
                    status="error",
                    error_message=TRANSIENT_MESSAGE,
                    needs_reauth=False,
                    completed_at=datetime.now(timezone.utc),
                )
        except Exception:
            pass

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
                    error_message=REAUTH_MESSAGE,
                    needs_reauth=True,
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
        window_start = now - timedelta(days=180)
        window_end = now + timedelta(days=365)
        time_min = window_start.isoformat()
        time_max = window_end.isoformat()
        window_start_date_str = window_start.strftime("%Y-%m-%d")
        window_end_date_str = window_end.strftime("%Y-%m-%d")

        total_synced = 0
        next_sync_token = None
        page_token = None
        synced_google_ids = set()

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
                            google_id = event_dict.get("id", "")
                            if google_id:
                                synced_google_ids.add(google_id)
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

            # Prune events in the synced time window that Google no longer
            # returned -- these have been deleted on the remote side.
            total_deleted = 0
            if synced_google_ids:
                async with async_session() as db:
                    timed_condition = and_(
                        CalendarEvent.account_id == self.account_id,
                        CalendarEvent.is_all_day == False,
                        CalendarEvent.start_time >= window_start,
                        CalendarEvent.start_time <= window_end,
                        CalendarEvent.google_event_id.notin_(synced_google_ids),
                    )
                    allday_condition = and_(
                        CalendarEvent.account_id == self.account_id,
                        CalendarEvent.is_all_day == True,
                        CalendarEvent.start_date >= window_start_date_str,
                        CalendarEvent.start_date <= window_end_date_str,
                        CalendarEvent.google_event_id.notin_(synced_google_ids),
                    )
                    orphan_result = await db.execute(
                        select(CalendarEvent).where(or_(timed_condition, allday_condition))
                    )
                    orphans = orphan_result.scalars().all()
                    for orphan in orphans:
                        await db.delete(orphan)
                        total_deleted += 1
                    if total_deleted > 0:
                        await db.commit()
                        logger.info(
                            f"Calendar full sync pruned {total_deleted} deleted events "
                            f"for account {self.account_id}"
                        )

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
                    needs_reauth=False,
                )

            logger.info(
                f"Calendar full sync complete: {total_synced} events synced, "
                f"{total_deleted} deleted for account {self.account_id}"
            )

        except Exception as e:
            await self._handle_sync_exception(e, "full")
            if _is_auth_error(e):
                # Auth errors are expected for old accounts -- don't propagate.
                return
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
                    "needs_reauth": False,
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

        except Exception as e:
            await self._handle_sync_exception(e, "incremental")
            if _is_auth_error(e):
                return
            raise
