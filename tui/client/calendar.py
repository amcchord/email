"""Calendar API client for fetching and syncing calendar events."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient


class CalendarClient:
    """Handles calendar-related API calls against the backend."""

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def get_events(
        self,
        start: str,
        end: str,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """List calendar events in a date range.

        Args:
            start: Start date in YYYY-MM-DD format.
            end: End date in YYYY-MM-DD format.
            account_id: Optional account ID to filter by.

        Returns dict with keys: events, total.
        """
        params: dict[str, Any] = {
            "start": start,
            "end": end,
        }
        if account_id is not None:
            params["account_id"] = account_id
        return await self.api.get("/calendar/events", params=params)

    async def get_event(self, event_id: int) -> dict[str, Any]:
        """Get a single calendar event by ID.

        Returns the full event dict with summary, start_time, end_time,
        location, attendees, etc.
        """
        return await self.api.get(f"/calendar/events/{event_id}")

    async def sync(self, account_id: int | None = None) -> dict[str, Any]:
        """Trigger a calendar sync for all accounts or a specific one.

        Returns dict with a message key.
        """
        params: dict[str, Any] = {}
        if account_id is not None:
            params["account_id"] = account_id
        return await self.api.post("/calendar/sync", params=params)

    async def get_sync_status(self) -> list[dict[str, Any]]:
        """Get calendar sync status for all accounts.

        Returns a list of sync status dicts per account.
        """
        return await self.api.get("/calendar/sync-status")

    async def get_upcoming(self, days: int = 7) -> dict[str, Any]:
        """Get upcoming events for the next N days.

        Returns dict with keys: events, total.
        """
        return await self.api.get(
            "/calendar/upcoming", params={"days": days}
        )
