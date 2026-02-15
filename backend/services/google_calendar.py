import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.models.account import GoogleAccount
from backend.utils.security import decrypt_value
from backend.config import get_settings
from backend.services.rate_limiter import gmail_rate_limiter, COST_DEFAULT

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_RETRIES = 5
BASE_BACKOFF = 3.0
MAX_BACKOFF = 120.0
PAGE_PAUSE = 0.3


def _is_rate_limit_error(error):
    if not isinstance(error, HttpError):
        return False
    status = error.resp.status if hasattr(error, 'resp') else 0
    if status == 429:
        return True
    if status == 403:
        error_str = str(error).lower()
        if "quota" in error_str or "rate" in error_str or "limit" in error_str:
            return True
    return False


class GoogleCalendarService:
    """Wrapper around the Google Calendar API v3."""

    def __init__(self, account: GoogleAccount, client_id: str = None, client_secret: str = None):
        self.account = account
        self._service = None
        self._creds = None
        self._original_token = None
        self._client_id = client_id or settings.google_client_id
        self._client_secret = client_secret or settings.google_client_secret

    def _get_credentials(self) -> Credentials:
        access_token = decrypt_value(self.account.encrypted_access_token)
        refresh_token = decrypt_value(self.account.encrypted_refresh_token)
        self._original_token = access_token
        # IMPORTANT: list ALL scopes the account was authorized with, not just
        # calendar.  When google-auth refreshes the token it requests these
        # scopes -- if we only list calendar.readonly, the new token loses
        # Gmail access and breaks email sync.
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.labels",
                "https://www.googleapis.com/auth/calendar.readonly",
            ],
        )
        self._creds = creds
        return creds

    def _get_service(self):
        if self._service is None:
            creds = self._get_credentials()
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def get_refreshed_token(self) -> Optional[str]:
        if self._creds is None:
            return None
        current_token = self._creds.token
        if current_token and current_token != self._original_token:
            return current_token
        return None

    async def _execute_with_retry(self, request_builder, context: str = "",
                                   max_retries: int = None, quota_cost: int = COST_DEFAULT):
        import random
        retries = max_retries if max_retries is not None else MAX_RETRIES
        loop = asyncio.get_event_loop()
        for attempt in range(retries):
            try:
                await gmail_rate_limiter.acquire(quota_cost)
                return await loop.run_in_executor(None, request_builder.execute)
            except HttpError as e:
                if _is_rate_limit_error(e) and attempt < retries - 1:
                    gmail_rate_limiter.drain()
                    delay = min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 2), MAX_BACKOFF)
                    logger.warning(f"Calendar API rate limited ({context}), backing off {delay:.1f}s "
                                   f"(attempt {attempt + 1}/{retries})")
                    await asyncio.sleep(delay)
                    continue
                raise

    async def list_events(
        self,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        page_token: Optional[str] = None,
        sync_token: Optional[str] = None,
        max_results: int = 250,
        single_events: bool = True,
    ) -> dict:
        """List events from the primary calendar.

        Returns raw API response dict with 'items', 'nextPageToken', 'nextSyncToken'.
        """
        service = self._get_service()
        kwargs = {
            "calendarId": "primary",
            "maxResults": max_results,
            "singleEvents": single_events,
        }
        if sync_token:
            kwargs["syncToken"] = sync_token
            # When using syncToken, don't set timeMin/timeMax/singleEvents
            kwargs.pop("singleEvents", None)
        else:
            if time_min:
                kwargs["timeMin"] = time_min
            if time_max:
                kwargs["timeMax"] = time_max
            if single_events:
                kwargs["orderBy"] = "startTime"

        if page_token:
            kwargs["pageToken"] = page_token

        return await self._execute_with_retry(
            service.events().list(**kwargs),
            context="list_events",
        )

    @staticmethod
    def parse_event(event_dict: dict, account_id: int) -> dict:
        """Normalize a Google Calendar event dict into a flat dict for DB storage."""
        # Determine if all-day or timed event
        start = event_dict.get("start", {})
        end = event_dict.get("end", {})

        is_all_day = "date" in start and "dateTime" not in start
        start_time = None
        end_time = None
        start_date = None
        end_date = None
        tz = start.get("timeZone") or end.get("timeZone")

        if is_all_day:
            start_date = start.get("date")
            end_date = end.get("date")
        else:
            start_dt_str = start.get("dateTime")
            end_dt_str = end.get("dateTime")
            if start_dt_str:
                start_time = datetime.fromisoformat(start_dt_str)
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
            if end_dt_str:
                end_time = datetime.fromisoformat(end_dt_str)
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)

        # Organizer
        organizer = event_dict.get("organizer", {})

        # Attendees
        attendees_raw = event_dict.get("attendees", [])
        attendees = []
        for a in attendees_raw:
            attendees.append({
                "email": a.get("email", ""),
                "name": a.get("displayName", ""),
                "response_status": a.get("responseStatus", "needsAction"),
                "self": a.get("self", False),
            })

        # Updated at from Google
        updated_str = event_dict.get("updated")
        updated_at_google = None
        if updated_str:
            try:
                updated_at_google = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Recurrence
        recurrence = event_dict.get("recurrence")
        recurrence_rule = recurrence if recurrence else None

        # Hangout / conference link
        hangout_link = event_dict.get("hangoutLink")
        if not hangout_link:
            conf_data = event_dict.get("conferenceData", {})
            for ep in conf_data.get("entryPoints", []):
                if ep.get("entryPointType") == "video":
                    hangout_link = ep.get("uri")
                    break

        return {
            "account_id": account_id,
            "google_event_id": event_dict.get("id", ""),
            "calendar_id": "primary",
            "summary": event_dict.get("summary"),
            "description": event_dict.get("description"),
            "location": event_dict.get("location"),
            "start_time": start_time,
            "end_time": end_time,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": tz,
            "is_all_day": is_all_day,
            "recurring_event_id": event_dict.get("recurringEventId"),
            "recurrence_rule": recurrence_rule,
            "status": event_dict.get("status", "confirmed"),
            "html_link": event_dict.get("htmlLink"),
            "hangout_link": hangout_link,
            "organizer_email": organizer.get("email"),
            "organizer_name": organizer.get("displayName"),
            "organizer_self": organizer.get("self", False),
            "attendees": attendees if attendees else None,
            "visibility": event_dict.get("visibility"),
            "transparency": event_dict.get("transparency"),
            "reminders": event_dict.get("reminders"),
            "etag": event_dict.get("etag"),
            "updated_at_google": updated_at_google,
        }
