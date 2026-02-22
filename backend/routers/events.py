"""SSE endpoint that streams real-time events to the browser.

Subscribes to the authenticated user's Redis Pub/Sub channel and
forwards every message as an SSE event.
"""

import asyncio
import json
import logging

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
        try:
            while True:
                if await request.is_disconnected():
                    break

                # get_message returns None when nothing is available
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=HEARTBEAT_INTERVAL
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
                else:
                    # No message within the heartbeat window – send a keep-alive comment
                    yield ": heartbeat\n\n"
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
