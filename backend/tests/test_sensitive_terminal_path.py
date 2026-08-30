from __future__ import annotations

import pytest

from backend.middleware.sensitive_terminal_path import (
    REDACTED_TERMINAL_PATH,
    SensitiveTerminalPathMiddleware,
)


@pytest.mark.asyncio
async def test_scoped_terminal_path_is_real_for_routing_then_redacted_for_access_log():
    observed = {}

    async def app(scope, _receive, send):
        observed["routed_path"] = scope["path"]
        observed["routed_query"] = scope["query_string"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []
    scope = {
        "type": "http",
        "path": "/terminal/device/device-id/SECRET/schedule.json",
        "raw_path": b"/terminal/device/device-id/SECRET/schedule.json",
        "query_string": b"variant=bw",
    }

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.start":
            observed["logged_path"] = scope["path"]
            observed["logged_query"] = scope["query_string"]

    await SensitiveTerminalPathMiddleware(app)(scope, receive, send)

    assert observed == {
        "routed_path": "/terminal/device/device-id/SECRET/schedule.json",
        "routed_query": b"variant=bw",
        "logged_path": REDACTED_TERMINAL_PATH,
        "logged_query": b"",
    }
    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
    ]


@pytest.mark.asyncio
async def test_scoped_terminal_path_is_redacted_even_when_endpoint_raises():
    observed = {}

    async def app(scope, _receive, _send):
        observed["routed_path"] = scope["path"]
        observed["routed_query"] = scope["query_string"]
        raise RuntimeError("simulated endpoint failure")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "path": "/terminal/device/device-id/SECRET/schedule.json",
        "raw_path": b"/terminal/device/device-id/SECRET/schedule.json",
        "query_string": b"variant=bw",
    }

    async def send(_message):
        raise AssertionError("no response should be sent")

    with pytest.raises(RuntimeError, match="simulated endpoint failure"):
        await SensitiveTerminalPathMiddleware(app)(scope, receive, send)

    assert observed == {
        "routed_path": "/terminal/device/device-id/SECRET/schedule.json",
        "routed_query": b"variant=bw",
    }
    assert scope["path"] == REDACTED_TERMINAL_PATH
    assert scope["raw_path"] == REDACTED_TERMINAL_PATH.encode("ascii")
    assert scope["query_string"] == b""


@pytest.mark.asyncio
async def test_unrelated_paths_are_not_changed():
    observed = []

    async def app(scope, _receive, send):
        observed.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        observed.append(scope["path"])

    scope = {"type": "http", "path": "/api/health", "query_string": b""}
    await SensitiveTerminalPathMiddleware(app)(scope, receive, send)

    assert observed == ["/api/health", "/api/health"]
