import asyncio
import signal
from types import SimpleNamespace

import pytest

from backend.routers import events


class _FakePubSub:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.closed = False

    async def get_message(self, ignore_subscribe_messages=True, timeout=0):
        await asyncio.sleep(0)
        return self.messages.pop(0) if self.messages else None

    async def unsubscribe(self):
        pass

    async def aclose(self):
        self.closed = True


class _FakeRedis:
    async def aclose(self):
        pass


class _FakeRequest:
    async def is_disconnected(self):
        return False


async def _open_stream(monkeypatch, pubsub):
    async def fake_subscribe(user_id):
        return _FakeRedis(), pubsub

    monkeypatch.setattr(events, "subscribe", fake_subscribe)
    response = await events.event_stream(_FakeRequest(), db=None, user=SimpleNamespace(id=1))
    return response.body_iterator


@pytest.fixture
def uvicorn_like_handler():
    calls = []
    original = signal.signal(signal.SIGTERM, lambda signum, frame: calls.append(signum))
    yield calls
    signal.signal(signal.SIGTERM, original)


@pytest.fixture(autouse=True)
def reset_shutdown_flag(monkeypatch):
    monkeypatch.setattr(events, "_shutting_down", False)


def test_sigterm_marks_shutdown_and_still_reaches_the_server_handler(uvicorn_like_handler):
    installed = signal.getsignal(signal.SIGTERM)

    with events.end_streams_on_sigterm():
        assert not events._shutting_down
        signal.raise_signal(signal.SIGTERM)
        assert events._shutting_down

    assert uvicorn_like_handler == [signal.SIGTERM]
    assert signal.getsignal(signal.SIGTERM) is installed


def test_default_signal_disposition_is_left_alone():
    original = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        with events.end_streams_on_sigterm():
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
    finally:
        signal.signal(signal.SIGTERM, original)


@pytest.mark.asyncio
async def test_stream_ends_and_cleans_up_when_shutdown_is_requested(monkeypatch):
    pubsub = _FakePubSub([{"type": "message", "data": '{"type": "new_emails"}'}])
    body = await _open_stream(monkeypatch, pubsub)

    assert await anext(body) == "event: new_emails\ndata: {}\n\n"

    monkeypatch.setattr(events, "_shutting_down", True)
    with pytest.raises(StopAsyncIteration):
        await anext(body)
    assert pubsub.closed


@pytest.mark.asyncio
async def test_idle_stream_still_sends_heartbeats(monkeypatch):
    monkeypatch.setattr(events, "HEARTBEAT_INTERVAL", 0)
    body = await _open_stream(monkeypatch, _FakePubSub())

    assert await anext(body) == ": heartbeat\n\n"
    await body.aclose()


@pytest.mark.asyncio
async def test_heartbeat_waits_for_the_interval(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(events.time, "monotonic", lambda: now[0])
    polls = []

    class CountingPubSub(_FakePubSub):
        async def get_message(self, ignore_subscribe_messages=True, timeout=0):
            polls.append(timeout)
            now[0] += events.POLL_INTERVAL
            return None

    body = await _open_stream(monkeypatch, CountingPubSub())

    assert await anext(body) == ": heartbeat\n\n"
    assert len(polls) == events.HEARTBEAT_INTERVAL
    assert set(polls) == {events.POLL_INTERVAL}
    await body.aclose()
