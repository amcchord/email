"""Todos API client for managing todo items."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient


class TodosClient:
    """Handles todo-related API calls against the backend."""

    def __init__(self, api_client: APIClient) -> None:
        self.api = api_client

    async def list_todos(
        self,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List todos with optional status filter.

        Args:
            status: Filter by status (pending, done, dismissed).
            page: Page number (1-indexed).
            page_size: Items per page.

        Returns dict with keys: todos, total.
        """
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }
        if status is not None:
            params["status"] = status
        return await self.api.get("/todos/", params=params)

    async def create_todo(
        self,
        title: str,
        email_id: int | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        """Create a new todo item.

        Returns the created todo dict.
        """
        payload: dict[str, Any] = {
            "title": title,
            "source": source,
        }
        if email_id is not None:
            payload["email_id"] = email_id
        return await self.api.post("/todos/", json_data=payload)

    async def update_todo(
        self,
        todo_id: int,
        title: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Update a todo's title or status.

        Args:
            todo_id: The todo item ID.
            title: New title (optional).
            status: New status - pending, done, or dismissed (optional).

        Returns the updated todo dict.
        """
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if status is not None:
            payload["status"] = status
        return await self.api.patch(f"/todos/{todo_id}", json_data=payload)

    async def delete_todo(self, todo_id: int) -> dict[str, Any]:
        """Delete a todo item.

        Returns dict with a message key.
        """
        return await self.api.delete(f"/todos/{todo_id}")

    async def create_from_email(self, email_id: int) -> dict[str, Any]:
        """Create todos from an email's AI-extracted action items.

        Returns dict with message, created count, and todos list.
        """
        return await self.api.post(f"/todos/from-email/{email_id}")
