"""Fable 5.1 request compatibility and safe snippet fallback."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import dashboard_snippet as snippets


@pytest.fixture
def fake_claude(monkeypatch):
    calls = {}
    calls["response"] = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="thinking"),
        SimpleNamespace(type="text", text='{"text":" A generated fixture line. ","byline":" Fixture Author "}'),
    ])

    class Client:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.messages = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def create(self, **kwargs):
            calls["request"] = kwargs
            if calls.get("error"):
                raise RuntimeError("test provider unavailable")
            return calls["response"]

    monkeypatch.setattr(snippets.anthropic, "AsyncAnthropic", Client)
    monkeypatch.setattr(snippets, "get_settings", lambda: SimpleNamespace(claude_api_key="test-key"))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["quote", "observation"])
async def test_fable_json_output_request_and_parsing(fake_claude, kind):
    result = await snippets._maybe_call_claude(kind, datetime(2026, 9, 27, 18, tzinfo=timezone.utc), {})
    assert result == {"text": "A generated fixture line.", "byline": "Fixture Author"}
    request = fake_claude["request"]
    assert request["model"] == "claude-fable-5-1"
    assert request["max_tokens"] == 4096
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "tool_choice" not in request and "tools" not in request
    assert "thinking" not in request
    assert fake_claude["client"]["timeout"] == 45.0


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["max_tokens", "refusal", "tool_use", "pause_turn"])
async def test_incomplete_or_refused_response_keeps_curated_fallback(fake_claude, stop):
    fake_claude["response"].stop_reason = stop
    assert await snippets._maybe_call_claude("quote", datetime.now(timezone.utc), {}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ['not json', '[]', '{}', '{"text":4,"byline":"A"}',
    '{"text":" ","byline":"A"}', '{"text":"Some words","byline":4}',
    '{"text":"Some words","byline":""}'])
async def test_bad_quote_response_keeps_curated_fallback(fake_claude, raw):
    fake_claude["response"].content = [SimpleNamespace(type="text", text=raw)]
    assert await snippets._maybe_call_claude("quote", datetime.now(timezone.utc), {}) is None


@pytest.mark.asyncio
async def test_provider_error_keeps_curated_fallback(fake_claude):
    fake_claude["error"] = True
    assert await snippets._maybe_call_claude("quote", datetime.now(timezone.utc), {}) is None


@pytest.mark.asyncio
async def test_missing_claude_key_does_not_call_another_provider(fake_claude, monkeypatch):
    monkeypatch.setattr(snippets, "get_settings", lambda: SimpleNamespace(claude_api_key=""))
    assert await snippets._maybe_call_claude("quote", datetime.now(timezone.utc), {}) is None
    assert "request" not in fake_claude
