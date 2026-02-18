"""Shared fixtures for TUI tests.

Provides a MockAPIClient that returns canned responses so tests can
run headlessly without a real backend.
"""

from __future__ import annotations

import os
from typing import Any
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest

# Ensure web-mode detection doesn't fire during tests
os.environ.pop("TEXTUAL_DRIVER", None)
os.environ.pop("TEXTUAL_WEB", None)
os.environ.pop("TUI_ACCESS_TOKEN", None)
os.environ.pop("TUI_REFRESH_TOKEN", None)
os.environ.pop("TUI_SSH_SERVER", None)


# ── Canned API responses ───────────────────────────────────────────

MOCK_USER = {
    "id": 1,
    "email": "test@example.com",
    "username": "testuser",
    "display_name": "Test User",
    "is_admin": False,
}

MOCK_DEVICE_START = {
    "device_code": "mock-device-code-abc123",
    "user_code": "ABCD-1234",
    "verification_url": "https://example.com/auth/device?code=ABCD-1234",
    "expires_in": 600,
    "interval": 1,
}

MOCK_DEVICE_STATUS_PENDING = {"status": "pending"}

MOCK_DEVICE_STATUS_AUTHORIZED = {
    "status": "authorized",
    "access_token": "mock-access-token",
    "refresh_token": "mock-refresh-token",
    "user": MOCK_USER,
}

MOCK_LOGIN_RESPONSE = {
    "access_token": "mock-access-token",
    "refresh_token": "mock-refresh-token",
    "user": MOCK_USER,
}

MOCK_FLOW_DATA = {
    "needs_reply": [],
    "awaiting": [],
    "threads": [],
    "events": [],
    "todos": [],
}

MOCK_EMPTY_LIST = {"emails": [], "total": 0}
MOCK_EMPTY_TODOS = {"todos": []}
MOCK_EMPTY_EVENTS = {"events": []}


# ── MockAPIClient ─────────────────────────────────────────────────

class MockAPIClient:
    """Drop-in replacement for tui.client.base.APIClient.

    Routes requests to canned responses.  Tests can override
    ``response_map`` to customise behaviour per-path.
    """

    def __init__(self, base_url: str = "http://localhost:8000/api") -> None:
        self.base_url = base_url
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._closed = False

        # Default response map: (method, path-prefix) -> response dict
        self.response_map: dict[tuple[str, str], Any] = {
            ("POST", "/auth/device/start"): MOCK_DEVICE_START,
            ("GET", "/auth/device/status"): MOCK_DEVICE_STATUS_PENDING,
            ("POST", "/auth/login"): MOCK_LOGIN_RESPONSE,
            ("GET", "/auth/me"): MOCK_USER,
            ("POST", "/auth/refresh"): MOCK_LOGIN_RESPONSE,
            ("GET", "/emails/flow"): MOCK_FLOW_DATA,
            ("GET", "/emails"): MOCK_EMPTY_LIST,
            ("GET", "/todos"): MOCK_EMPTY_TODOS,
            ("GET", "/calendar/events"): MOCK_EMPTY_EVENTS,
            ("GET", "/ai/trends"): {},
            ("GET", "/ai/stats"): {"total_emails": 0, "total_analyzed": 0},
            ("GET", "/ai/subscriptions"): {"senders": []},
            ("GET", "/ai/digests"): {"digests": []},
            ("GET", "/admin/stats"): {"total_emails": 0},
            ("GET", "/admin/dashboard"): {"total_emails": 0},
        }

    def set_tokens(self, access_token: str, refresh_token: str) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token

    def clear_tokens(self) -> None:
        self.access_token = None
        self.refresh_token = None

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _find_response(self, method: str, path: str) -> Any:
        """Look up a canned response for the given method + path."""
        # Exact match first
        key = (method, path)
        if key in self.response_map:
            return self.response_map[key]
        # Prefix match
        for (m, prefix), resp in self.response_map.items():
            if m == method and path.startswith(prefix):
                return resp
        return {}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._find_response("GET", path)

    async def post(
        self,
        path: str,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._find_response("POST", path)

    async def put(
        self,
        path: str,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._find_response("PUT", path)

    async def patch(
        self,
        path: str,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._find_response("PATCH", path)

    async def delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        return self._find_response("DELETE", path)

    async def stream_post(
        self,
        path: str,
        json_data: Any = None,
    ) -> AsyncGenerator[tuple[str, str], None]:
        yield ("message", '{"done": true}')

    async def close(self) -> None:
        self._closed = True

    async def _get_client(self):
        """Return a mock httpx client for AuthClient compatibility."""
        return _MockHTTPXClient(self)

    async def _refresh_access_token(self) -> bool:
        return True


class _MockHTTPXClient:
    """Minimal mock that quacks like httpx.AsyncClient for AuthClient."""

    def __init__(self, mock_api: MockAPIClient) -> None:
        self._mock_api = mock_api
        self.is_closed = False

    async def post(self, path: str, **kwargs) -> "_MockHTTPXResponse":
        data = self._mock_api._find_response("POST", path)
        return _MockHTTPXResponse(200, data)

    async def get(self, path: str, **kwargs) -> "_MockHTTPXResponse":
        data = self._mock_api._find_response("GET", path)
        return _MockHTTPXResponse(200, data)


class _MockHTTPXResponse:
    """Minimal mock httpx.Response."""

    def __init__(self, status_code: int, data: Any) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> Any:
        return self._data


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def mock_api_client() -> MockAPIClient:
    """Return a fresh MockAPIClient instance."""
    return MockAPIClient()


@pytest.fixture
def mail_app(mock_api_client: MockAPIClient):
    """Return a MailApp instance wired to a MockAPIClient.

    Usage in tests::

        async with mail_app.run_test() as pilot:
            ...
    """
    from tui.app import MailApp
    app = MailApp()
    app.api_client = mock_api_client
    return app
