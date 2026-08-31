"""Bound compose message bodies before FastAPI parses sensitive JSON."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


MAX_COMPOSE_SEND_BODY_BYTES = 50 * 1024 * 1024
MAX_SNIPPET_BODY_BYTES = 128 * 1024
_COMPOSE_BODY_PATHS = frozenset({"/api/compose/send", "/api/compose/draft"})


class _ComposeBodyTooLarge(Exception):
    pass


class ComposeSendBodyLimitMiddleware:
    """Apply a byte-verified request cap to compose send and draft upsert."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = MAX_COMPOSE_SEND_BODY_BYTES,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_limit = self._request_limit(scope)
        if request_limit is None:
            await self.app(scope, receive, send)
            return

        try:
            content_length = self._content_length(scope)
        except ValueError:
            await self._send_error(
                scope,
                receive,
                send,
                status_code=400,
                code="compose_content_length_invalid",
                message="Content-Length is invalid",
            )
            return

        if content_length is not None and content_length > request_limit:
            await self._send_too_large(scope, receive, send, request_limit=request_limit)
            return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > request_limit:
                    raise _ComposeBodyTooLarge
            return message

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _ComposeBodyTooLarge:
            if response_started:
                raise
            await self._send_too_large(scope, receive, send, request_limit=request_limit)

    def _request_limit(self, scope: Scope) -> int | None:
        if scope["type"] != "http":
            return None
        method = scope.get("method")
        path = scope.get("path") or ""
        if method == "POST" and path in _COMPOSE_BODY_PATHS:
            return self.max_bytes
        if path == "/api/compose/snippets" and method == "POST":
            return min(self.max_bytes, MAX_SNIPPET_BODY_BYTES)
        if path.startswith("/api/compose/snippets/") and method == "PUT":
            return min(self.max_bytes, MAX_SNIPPET_BODY_BYTES)
        return None

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if not values:
            return None
        if len(values) != 1:
            raise ValueError("multiple Content-Length headers")
        try:
            length = int(values[0].decode("ascii"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("invalid Content-Length") from error
        if length < 0:
            raise ValueError("negative Content-Length")
        return length

    async def _send_too_large(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        request_limit: int,
    ) -> None:
        path = scope.get("path") or ""
        is_snippet = path == "/api/compose/snippets" or path.startswith(
            "/api/compose/snippets/"
        )
        await self._send_error(
            scope,
            receive,
            send,
            status_code=413,
            code="snippet_payload_too_large" if is_snippet else "compose_payload_too_large",
            message=(
                "Snippet content exceeds the 128 KB request limit"
                if is_snippet
                else "Email content exceeds the 50 MB request limit"
            ),
        )

    @staticmethod
    async def _send_error(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"detail": {"code": code, "message": message}},
        )
        await response(scope, receive, send)
