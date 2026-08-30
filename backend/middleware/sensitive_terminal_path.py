"""Redact path-bound terminal credentials before server access logging.

Current terminal firmware can persist only a schedule URL, not a separate
Authorization header, so scoped device credentials necessarily appear in the
URL path. Routing needs the real path, while Uvicorn and Starlette's outer
error wrapper retain the server-owned ASGI scope for access and exception
logging. This middleware redacts that outer scope immediately, then passes a
shallow copy containing the real route data inward. The split also covers
exceptions raised before any response is started.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


REDACTED_TERMINAL_PATH = "/terminal/device/[redacted]"


class SensitiveTerminalPathMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        path = scope.get("path")
        if scope.get("type") != "http" or not isinstance(path, str) or not path.startswith(
            "/terminal/device/"
        ):
            await self.app(scope, receive, send)
            return

        routed_scope = dict(scope)
        scope["path"] = REDACTED_TERMINAL_PATH
        scope["raw_path"] = REDACTED_TERMINAL_PATH.encode("ascii")
        scope["query_string"] = b""
        await self.app(routed_scope, receive, send)
