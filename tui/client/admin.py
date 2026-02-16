"""Admin API client for dashboard, settings, and account management."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient


class AdminClient:
    """Handles admin-related API calls against the backend.

    All endpoints require admin privileges. Non-admin users will
    receive 403 errors from the backend.
    """

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def get_dashboard(self) -> dict[str, Any]:
        """Get admin dashboard statistics.

        Returns dict with total_accounts, total_emails, total_unread,
        sync_active, ai_analyses_count.
        """
        return await self.api.get("/admin/dashboard")

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed email statistics for charts.

        Returns dict with volume_by_day, top_senders, read_vs_unread,
        category_distribution, emails_per_day_avg, totals, etc.
        """
        return await self.api.get("/admin/stats")

    async def get_settings(self) -> list[dict[str, Any]]:
        """List all application settings.

        Returns a list of setting dicts with key, value, is_secret,
        description, updated_at.
        """
        return await self.api.get("/admin/settings")

    async def update_setting(
        self,
        key: str,
        value: str,
        is_secret: bool = False,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a setting.

        Returns the updated setting dict.
        """
        payload: dict[str, Any] = {
            "key": key,
            "value": value,
            "is_secret": is_secret,
        }
        if description is not None:
            payload["description"] = description
        return await self.api.put("/admin/settings", json_data=payload)

    async def delete_setting(self, key: str) -> dict[str, Any]:
        """Delete a setting by key.

        Returns dict with a message key.
        """
        return await self.api.delete(f"/admin/settings/{key}")

    async def get_admin_accounts(self) -> list[dict[str, Any]]:
        """List all Google accounts with sync status (admin view).

        Returns a list of account dicts with id, email, display_name,
        is_active, created_at, sync_status.
        """
        return await self.api.get("/admin/accounts")
