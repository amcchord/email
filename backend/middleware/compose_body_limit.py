"""Bound compose message bodies before FastAPI parses sensitive JSON."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


MAX_COMPOSE_SEND_BODY_BYTES = 50 * 1024 * 1024
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
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in _COMPOSE_BODY_PATHS
        ):
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

        if content_length is not None and content_length > self.max_bytes:
            await self._send_too_large(scope, receive, send)
            return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
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
            await self._send_too_large(scope, receive, send)

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

    async def _send_too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._send_error(
            scope,
            receive,
            send,
            status_code=413,
            code="compose_payload_too_large",
            message="Email content exceeds the 50 MB request limit",
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
