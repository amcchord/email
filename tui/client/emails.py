"""Email API client for listing, viewing, and acting on emails."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient


class EmailClient:
    """Handles email-related API calls against the backend."""

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def list_emails(
        self,
        mailbox: str = "INBOX",
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
        is_read: bool | None = None,
        is_starred: bool | None = None,
        ai_category: str | None = None,
        exclude_ai_category: str | None = None,
        needs_reply: bool | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """List emails with filtering and pagination.

        Returns dict with keys: emails, total, page, page_size, total_pages.
        """
        params: dict[str, Any] = {
            "mailbox": mailbox,
            "page": page,
            "page_size": page_size,
        }
        if search is not None:
            params["search"] = search
        if is_read is not None:
            params["is_read"] = is_read
        if is_starred is not None:
            params["is_starred"] = is_starred
        if ai_category is not None:
            params["ai_category"] = ai_category
        if exclude_ai_category is not None:
            params["exclude_ai_category"] = exclude_ai_category
        if needs_reply is not None:
            params["needs_reply"] = needs_reply
        if account_id is not None:
            params["account_id"] = account_id

        return await self.api.get("/emails/", params=params)

    async def get_email(self, email_id: int) -> dict[str, Any]:
        """Get full email detail including AI analysis.

        Returns the full email dict with body_html, body_text,
        ai_summary, ai_action_items, reply_options, etc.
        """
        return await self.api.get(f"/emails/{email_id}")

    async def get_thread(
        self, thread_id: str, order: str = "asc"
    ) -> dict[str, Any]:
        """Get all messages in a thread.

        Returns dict with keys: emails, thread_id, participants, subject.
        """
        return await self.api.get(
            f"/emails/thread/{thread_id}",
            params={"order": order},
        )

    async def perform_actions(
        self, email_ids: list[int], action: str
    ) -> dict[str, Any]:
        """Perform a bulk action on one or more emails.

        Valid actions: archive, trash, star, unstar, mark_read,
        mark_unread, spam, unspam, untrash.

        Returns dict with a message key.
        """
        return await self.api.post(
            "/emails/actions",
            json_data={"email_ids": email_ids, "action": action},
        )

    async def get_labels(
        self, account_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Get all labels with message counts.

        Returns a list of label dicts with name, gmail_label_id,
        messages_total, messages_unread, etc.
        """
        params: dict[str, Any] = {}
        if account_id is not None:
            params["account_id"] = account_id
        return await self.api.get("/emails/labels/all", params=params)
