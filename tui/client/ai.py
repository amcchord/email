"""AI API client for needs-reply, awaiting-response, threads, trends, and more."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient


class AIClient:
    """Handles AI-related API calls against the backend."""

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def get_needs_reply(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """Get emails that the user should respond to.

        Returns dict with keys: emails, total.
        Each email includes ai_analysis fields like reply_options.
        """
        return await self.api.get(
            "/ai/needs-reply",
            params={"page": page, "page_size": page_size},
        )

    async def get_awaiting_response(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """Get sent emails waiting for replies.

        Returns dict with keys: emails, total.
        """
        return await self.api.get(
            "/ai/awaiting-response",
            params={"page": page, "page_size": page_size},
        )

    async def get_threads(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """Get thread summaries with message counts and participants.

        Returns dict with keys: threads, total.
        """
        return await self.api.get(
            "/ai/threads",
            params={"page": page, "page_size": page_size},
        )

    async def get_trends(self) -> dict[str, Any]:
        """Get AI-powered trends and insights.

        Returns dict with needs_attention, category_over_time,
        top_topics, urgent_senders, summary, etc.
        """
        return await self.api.get("/ai/trends")

    async def get_stats(self) -> dict[str, Any]:
        """Get AI analysis statistics.

        Returns dict with total_emails, total_analyzed, models, unanalyzed.
        """
        return await self.api.get("/ai/stats")

    async def ignore_needs_reply(self, email_id: int) -> dict[str, Any]:
        """Mark a needs-reply email as ignored.

        Returns dict with ok key.
        """
        return await self.api.post(f"/ai/needs-reply/{email_id}/ignore")

    async def snooze_needs_reply(
        self, email_id: int, duration: str = "1h"
    ) -> dict[str, Any]:
        """Snooze a needs-reply email for a preset duration.

        Valid durations: 1h, 3h, tomorrow, next_week.
        Returns dict with ok and snoozed_until keys.
        """
        return await self.api.post(
            f"/ai/needs-reply/{email_id}/snooze",
            params={"duration": duration},
        )

    async def generate_reply(
        self, email_id: int, prompt: str | None = None
    ) -> dict[str, Any]:
        """Generate a custom AI reply based on a user-provided prompt.

        Returns dict with the generated reply text.
        """
        json_data: dict[str, Any] = {"email_id": email_id}
        if prompt:
            json_data["prompt"] = prompt
        return await self.api.post("/ai/generate-reply", json_data=json_data)

    async def get_subscriptions(
        self, page: int = 1, page_size: int = 50
    ) -> dict[str, Any]:
        """Get subscription/marketing emails grouped by sender domain.

        Returns dict with emails, senders, total.
        """
        return await self.api.get(
            "/ai/subscriptions",
            params={"page": page, "page_size": page_size},
        )

    async def get_bundles(
        self, page: int = 1, page_size: int = 20, status: str = "active"
    ) -> dict[str, Any]:
        """Get topic-based email bundles.

        Returns dict with bundles, total.
        """
        return await self.api.get(
            "/ai/bundles",
            params={"page": page, "page_size": page_size, "status": status},
        )

    async def get_digests(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """Get thread digests with AI-generated summaries.

        Returns dict with digests, total.
        """
        return await self.api.get(
            "/ai/digests",
            params={"page": page, "page_size": page_size},
        )

    async def auto_categorize(
        self, days: int | None = None
    ) -> dict[str, Any]:
        """Trigger auto-categorization of unanalyzed emails.

        Returns dict with message, accounts_queued, total_to_process.
        """
        params: dict[str, Any] = {}
        if days is not None:
            params["days"] = days
        return await self.api.post("/ai/auto-categorize", params=params)

    async def get_processing_status(self) -> dict[str, Any]:
        """Get the current AI processing progress.

        Returns dict with active, type, total, processed, model.
        """
        return await self.api.get("/ai/processing/status")

    async def delete_analyses(
        self, rebuild_days: int | None = None
    ) -> dict[str, Any]:
        """Drop all AI analyses for the user's accounts.

        Returns dict with deleted count and optional rebuild info.
        """
        params: dict[str, Any] = {}
        if rebuild_days is not None:
            params["rebuild_days"] = rebuild_days
        return await self.api.delete("/ai/analyses", params=params)
