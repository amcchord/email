"""Compose API client for sending emails and saving drafts."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient


class ComposeClient:
    """Handles compose-related API calls against the backend."""

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def send_email(
        self,
        account_id: int,
        to: list[str],
        subject: str,
        body_html: str,
        body_text: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Send an email via the compose API.

        Returns dict with message and gmail_message_id.
        """
        json_data: dict[str, Any] = {
            "account_id": account_id,
            "to": to,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
        }
        if cc:
            json_data["cc"] = cc
        if bcc:
            json_data["bcc"] = bcc
        if in_reply_to:
            json_data["in_reply_to"] = in_reply_to
        if references:
            json_data["references"] = references
        if thread_id:
            json_data["thread_id"] = thread_id

        return await self.api.post("/compose/send", json_data=json_data)

    async def save_draft(
        self,
        account_id: int,
        to: list[str],
        subject: str,
        body_html: str,
        body_text: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Save an email as a draft.

        Returns dict with message and draft_id.
        """
        json_data: dict[str, Any] = {
            "account_id": account_id,
            "to": to,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
        }
        if cc:
            json_data["cc"] = cc
        if bcc:
            json_data["bcc"] = bcc
        if in_reply_to:
            json_data["in_reply_to"] = in_reply_to
        if references:
            json_data["references"] = references
        if thread_id:
            json_data["thread_id"] = thread_id

        return await self.api.post("/compose/draft", json_data=json_data)
