import json

import pytest

from backend.middleware.compose_body_limit import ComposeSendBodyLimitMiddleware


def _scope(*, path="/api/compose/send", method="POST", headers=None):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 443),
    }


async def _run_middleware(*, max_bytes, chunks, headers=None, path="/api/compose/send"):
    sent = []
    received = 0
    app_called = False
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]

    async def receive():
        nonlocal received
        received += 1
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def app(_scope, app_receive, app_send):
        nonlocal app_called
        app_called = True
        while True:
            message = await app_receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await app_send({"type": "http.response.start", "status": 204, "headers": []})
        await app_send({"type": "http.response.body", "body": b""})

    middleware = ComposeSendBodyLimitMiddleware(app, max_bytes=max_bytes)
    await middleware(_scope(path=path, headers=headers), receive, send)
    return sent, received, app_called


def _response(sent):
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return status, json.loads(body) if body else None


@pytest.mark.asyncio
async def test_compose_limit_rejects_declared_oversize_without_reading_body():
    sent, received, app_called = await _run_middleware(
        max_bytes=5,
        chunks=[b"ignored"],
        headers=[(b"content-length", b"6")],
    )
    status, payload = _response(sent)
    assert status == 413
    assert payload["detail"]["code"] == "compose_payload_too_large"
    assert received == 0
    assert app_called is False


@pytest.mark.asyncio
async def test_compose_limit_counts_streamed_bytes_without_content_length():
    sent, received, app_called = await _run_middleware(
        max_bytes=5,
        chunks=[b"abc", b"def"],
    )
    status, payload = _response(sent)
    assert status == 413
    assert payload["detail"]["code"] == "compose_payload_too_large"
    assert received == 2
    assert app_called is True


@pytest.mark.asyncio
async def test_snippet_limit_uses_snippet_error_even_with_a_small_test_cap():
    sent, received, app_called = await _run_middleware(
        max_bytes=5,
        chunks=[b"ignored"],
        headers=[(b"content-length", b"6")],
        path="/api/compose/snippets",
    )
    status, payload = _response(sent)
    assert status == 413
    assert payload["detail"]["code"] == "snippet_payload_too_large"
    assert received == 0
    assert app_called is False


@pytest.mark.asyncio
async def test_compose_limit_allows_exact_bound_caps_drafts_and_ignores_other_routes():
    sent, _received, app_called = await _run_middleware(
        max_bytes=5,
        chunks=[b"abc", b"de"],
        headers=[(b"content-length", b"5")],
    )
    assert _response(sent)[0] == 204
    assert app_called is True

    draft_sent, _received, draft_called = await _run_middleware(
        max_bytes=5,
        chunks=[b"oversized"],
        headers=[(b"content-length", b"999")],
        path="/api/compose/draft",
    )
    assert _response(draft_sent)[0] == 413
    assert draft_called is False

    other_sent, _received, other_called = await _run_middleware(
        max_bytes=5,
        chunks=[b"oversized"],
        headers=[(b"content-length", b"999")],
        path="/api/compose/drafts/recent",
    )
    assert _response(other_sent)[0] == 204
    assert other_called is True


@pytest.mark.asyncio
async def test_compose_limit_rejects_ambiguous_content_length():
    sent, received, app_called = await _run_middleware(
        max_bytes=5,
        chunks=[b"abc"],
        headers=[(b"content-length", b"3"), (b"content-length", b"3")],
    )
    status, payload = _response(sent)
    assert status == 400
    assert payload["detail"]["code"] == "compose_content_length_invalid"
    assert received == 0
    assert app_called is False
