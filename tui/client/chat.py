"""Chat API client with SSE streaming support."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from tui.client.base import APIClient

logger = logging.getLogger(__name__)


class ChatClient:
    """Handles chat API calls including SSE streaming."""

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def stream_chat(
        self, message: str, conversation_id: int | None = None
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Stream a chat message via SSE.

        Yields (event_type, data_string) tuples.
        Event types from backend: plan_ready, task_complete, task_failed,
        content, clarification, done, error, conversation_id, phase.

        The content event data is JSON with a "text" key containing the
        full accumulated response so far.
        """
        payload: dict[str, Any] = {"message": message}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id

        async for event_type, data_str in self.api.stream_post(
            "/chat", json_data=payload
        ):
            yield event_type, data_str

    async def list_conversations(self) -> list[dict[str, Any]]:
        """List all conversations for the current user.

        Returns list of {id, title, created_at, updated_at}.
        """
        result = await self.api.get("/chat/conversations")
        if isinstance(result, list):
            return result
        return result.get("conversations", result) if isinstance(result, dict) else []

    async def get_conversation(self, conversation_id: int) -> dict[str, Any]:
        """Get a conversation with all its messages.

        Returns {id, title, created_at, updated_at, messages: [{role, content, ...}]}.
        """
        return await self.api.get(f"/chat/conversations/{conversation_id}")

    async def delete_conversation(self, conversation_id: int) -> dict[str, Any]:
        """Delete a conversation.

        Returns {message: "Conversation deleted"}.
        """
        return await self.api.delete(f"/chat/conversations/{conversation_id}")
