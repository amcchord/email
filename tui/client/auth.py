"""Authentication client for login, refresh, me, and logout."""

from __future__ import annotations

from typing import Any

from tui.client.base import APIClient, AuthenticationError


class AuthClient:
    """Handles authentication operations against the backend API."""

    def __init__(self, api_client: APIClient) -> None:
        self._api = api_client

    async def login(self, username: str, password: str) -> dict[str, Any]:
        """Log in with username and password.

        Calls POST /auth/login, stores tokens on the API client, and
        returns the user dict from the response.

        Raises AuthenticationError on invalid credentials.
        """
        # Use the underlying httpx client directly to avoid auto-refresh
        # logic on the login endpoint itself.
        client = await self._api._get_client()
        response = await client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        if response.status_code == 401:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                pass
            raise AuthenticationError(
                detail or "Invalid credentials",
                status_code=401,
                detail=detail or "Invalid credentials",
            )
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                detail = response.text
            raise AuthenticationError(
                detail or f"Login failed ({response.status_code})",
                status_code=response.status_code,
                detail=detail,
            )
        data = response.json()
        self._api.set_tokens(data["access_token"], data["refresh_token"])
        return data.get("user", {})

    async def refresh(self) -> dict[str, Any]:
        """Refresh the access token using the stored refresh token.

        Calls POST /auth/refresh, updates tokens, and returns the user dict.
        """
        if not self._api.refresh_token:
            raise AuthenticationError(
                "No refresh token available",
                status_code=401,
                detail="No refresh token",
            )
        client = await self._api._get_client()
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": self._api.refresh_token},
        )
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                pass
            raise AuthenticationError(
                detail or "Token refresh failed",
                status_code=response.status_code,
                detail=detail or "Token refresh failed",
            )
        data = response.json()
        self._api.set_tokens(data["access_token"], data["refresh_token"])
        return data.get("user", {})

    async def me(self) -> dict[str, Any]:
        """Get the current authenticated user.

        Calls GET /auth/me and returns the user dict.
        """
        return await self._api.get("/auth/me")

    async def logout(self) -> None:
        """Log out the current user.

        Calls POST /auth/logout and clears stored tokens.
        """
        try:
            await self._api.post("/auth/logout")
        except Exception:
            pass
        finally:
            self._api.clear_tokens()
