"""Async HTTP client for communicating with the backend API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx


class APIError(Exception):
    """Base exception for API errors."""

    def __init__(self, message: str, status_code: int = 0, detail: str = ""):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class AuthenticationError(APIError):
    """Raised on 401/403 responses after refresh attempt fails."""
    pass


class NotFoundError(APIError):
    """Raised on 404 responses."""
    pass


class APIClient:
    """Async HTTP client with automatic token refresh.

    Stores access_token and refresh_token in memory. On 401, attempts
    to refresh the token once and retry the request.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def set_tokens(self, access_token: str, refresh_token: str) -> None:
        """Store authentication tokens."""
        self.access_token = access_token
        self.refresh_token = refresh_token

    def clear_tokens(self) -> None:
        """Clear stored authentication tokens."""
        self.access_token = None
        self.refresh_token = None

    async def _refresh_access_token(self) -> bool:
        """Attempt to refresh the access token. Returns True on success."""
        if not self.refresh_token:
            return False
        try:
            client = await self._get_client()
            response = await client.post(
                "/auth/refresh",
                json={"refresh_token": self.refresh_token},
            )
            if response.status_code == 200:
                data = response.json()
                self.access_token = data["access_token"]
                self.refresh_token = data["refresh_token"]
                return True
        except Exception:
            pass
        return False

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Raise appropriate exception for error responses."""
        if response.status_code == 404:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                pass
            raise NotFoundError(
                f"Not found: {response.url}",
                status_code=404,
                detail=detail,
            )
        if response.status_code in (401, 403):
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                pass
            raise AuthenticationError(
                f"Authentication failed: {detail}",
                status_code=response.status_code,
                detail=detail,
            )
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                detail = response.text
            raise APIError(
                f"API error {response.status_code}: {detail}",
                status_code=response.status_code,
                detail=detail,
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
        _retried: bool = False,
    ) -> Any:
        """Make an authenticated request. Auto-refreshes on 401."""
        client = await self._get_client()
        kwargs: dict[str, Any] = {"headers": self._auth_headers()}
        if json_data is not None:
            kwargs["json"] = json_data
        if params is not None:
            kwargs["params"] = params

        response = await client.request(method, path, **kwargs)

        # Auto-refresh on 401
        if response.status_code == 401 and not _retried:
            if await self._refresh_access_token():
                kwargs["headers"] = self._auth_headers()
                response = await client.request(method, path, **kwargs)

        self._raise_for_status(response)
        if response.status_code == 204:
            return None
        return response.json()

    async def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Make an authenticated GET request."""
        return await self._request("GET", path, params=params)

    async def post(
        self,
        path: str,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated POST request."""
        return await self._request(
            "POST", path, json_data=json_data, params=params
        )

    async def put(
        self,
        path: str,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated PUT request."""
        return await self._request(
            "PUT", path, json_data=json_data, params=params
        )

    async def patch(
        self,
        path: str,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated PATCH request."""
        return await self._request(
            "PATCH", path, json_data=json_data, params=params
        )

    async def delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Make an authenticated DELETE request."""
        return await self._request("DELETE", path, params=params)

    async def stream_post(
        self,
        path: str,
        json_data: Any = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """Stream a POST request for SSE endpoints.

        Yields (event_type, data) tuples. The event_type defaults to
        "message" when not specified in the SSE stream.
        """
        client = await self._get_client()
        headers = self._auth_headers()
        headers["Accept"] = "text/event-stream"

        async with client.stream(
            "POST",
            path,
            json=json_data,
            headers=headers,
            timeout=120.0,
        ) as response:
            if response.status_code == 401:
                # Try refresh
                if await self._refresh_access_token():
                    # Re-open the stream with new token
                    pass
                else:
                    self._raise_for_status(response)
                    return

            if response.status_code >= 400:
                # Read the body for error details
                await response.aread()
                self._raise_for_status(response)
                return

            event_type = "message"
            data_lines: list[str] = []

            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "":
                    # End of event
                    if data_lines:
                        yield (event_type, "\n".join(data_lines))
                    event_type = "message"
                    data_lines = []

            # Yield any remaining data
            if data_lines:
                yield (event_type, "\n".join(data_lines))
