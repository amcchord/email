"""Redis Pub/Sub notification service.

Publishes events from the worker (or API) so that the SSE endpoint
can relay them to connected browsers in real time.
"""

import json
import logging
import time

import redis.asyncio as aioredis

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

CHANNEL_PREFIX = "mail:events"


def _channel_for_user(user_id: int) -> str:
    return f"{CHANNEL_PREFIX}:{user_id}"


async def publish_event(user_id: int, event_type: str, data: dict | None = None):
    """Publish an event to the user's Pub/Sub channel.

    Parameters
    ----------
    user_id:    Target user.
    event_type: e.g. ``"new_emails"``, ``"sync_complete"``.
    data:       Arbitrary JSON-serialisable payload.
    """
    payload = {
        "type": event_type,
        "ts": time.time(),
        **(data or {}),
    }
    channel = _channel_for_user(user_id)
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.publish(channel, json.dumps(payload))
        await r.aclose()
    except Exception:
        logger.warning("Failed to publish event %s for user %s", event_type, user_id, exc_info=True)


async def subscribe(user_id: int):
    """Return an async Redis Pub/Sub subscription for the user's channel.

    Caller is responsible for closing the returned client when done.
    Returns ``(redis_client, pubsub)`` so both can be cleaned up.
    """
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(_channel_for_user(user_id))
    return r, pubsub
