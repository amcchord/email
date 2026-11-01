"""SSE endpoint that streams real-time events to the browser.

Subscribes to the authenticated user's Redis Pub/Sub channel and
forwards every message as an SSE event.
"""

import asyncio
import json
import logging
import signal
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.services.notifications import subscribe

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/events", tags=["events"])

HEARTBEAT_INTERVAL = 25  # seconds – keeps proxies / browsers from timing out
POLL_INTERVAL = 1  # seconds – how quickly a stream notices it should end

_shutting_down = False


@contextmanager
def end_streams_on_sigterm() -> Iterator[None]:
    """Make open streams finish as soon as the server is told to stop.

    uvicorn waits for open responses before it runs lifespan shutdown and does
    not tell them it is stopping, so a stream would otherwise hold its worker
    until --timeout-graceful-shutdown. uvicorn installs its signal handlers
    before lifespan startup, so this wraps its handler. Without one, streams
    keep today's behaviour and the graceful-shutdown timeout still applies.
    """
    global _shutting_down
    _shutting_down = False
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    if not callable(previous):
        yield
        return

    def handler(signum, frame):
        global _shutting_down
        _shutting_down = True
        previous(signum, frame)

    signal.signal(signal.SIGTERM, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@router.get("/stream")
async def event_stream(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Long-lived SSE connection scoped to the authenticated user."""

    user_id = user.id

    async def generate():
        redis_client, pubsub = await subscribe(user_id)
        last_sent = time.monotonic()
        try:
            while True:
                if _shutting_down or await request.is_disconnected():
                    break

                # get_message returns None when nothing is available
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=POLL_INTERVAL
                )
                if msg is not None and msg["type"] == "message":
                    data = msg["data"]
                    try:
                        parsed = json.loads(data)
                        event_type = parsed.pop("type", "message")
                    except (json.JSONDecodeError, AttributeError):
                        event_type = "message"
                        parsed = {"raw": data}
                    yield f"event: {event_type}\ndata: {json.dumps(parsed)}\n\n"
                    last_sent = time.monotonic()
                elif time.monotonic() - last_sent >= HEARTBEAT_INTERVAL:
                    # Nothing sent within the heartbeat window – send a keep-alive comment
                    yield ": heartbeat\n\n"
                    last_sent = time.monotonic()
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            await redis_client.aclose()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
