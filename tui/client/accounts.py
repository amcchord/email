"""Accounts API client for listing, syncing, and managing email accounts."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient


class AccountsClient:
    """Handles account-related API calls against the backend."""

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def list_accounts(self) -> list[dict[str, Any]]:
        """List all connected email accounts.

        Returns a list of account dicts with id, email, display_name,
        short_label, is_active, etc.
        """
        return await self.api.get("/accounts/")

    async def trigger_sync(self, account_id: int) -> dict[str, Any]:
        """Trigger an email sync for a specific account.

        Returns dict with a message key.
        """
        return await self.api.post(f"/accounts/{account_id}/sync")

    async def get_sync_status(self, account_id: int) -> dict[str, Any]:
        """Get the sync status for a specific account.

        Returns dict with sync status details.
        """
        return await self.api.get(f"/accounts/{account_id}/sync-status")

    async def delete_account(self, account_id: int) -> dict[str, Any]:
        """Remove a connected email account.

        Returns dict with a message key.
        """
        return await self.api.delete(f"/accounts/{account_id}")

    async def update_description(
        self, account_id: int, description: str
    ) -> dict[str, Any]:
        """Update the description/purpose for an email account.

        Returns dict with description and short_label.
        """
        return await self.api.put(
            f"/accounts/{account_id}/description",
            json_data={"description": description},
        )
