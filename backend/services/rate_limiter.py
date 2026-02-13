"""Process-wide token bucket for Gmail API quota management.

Gmail API quota is per-project (client_id), not per-account.  All accounts
share the same pool of ~250 quota-units/second (~15,000/minute).  This module
provides a single in-process token bucket that every API call must pass
through before executing, preventing any combination of accounts from
exceeding the project ceiling.
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# Gmail API costs (quota units):
#   messages.list   = 5
#   messages.get    = 5
#   labels.list     = 1
#   history.list    = 2
#   batch request   = 1 + per-item cost
#   send / modify   = variable but higher
COST_LIST = 5
COST_GET = 5
COST_HISTORY = 2
COST_LABELS = 1
COST_DEFAULT = 5


class TokenBucket:
    """Async token bucket that enforces a per-second quota ceiling.

    Tokens refill continuously at ``rate_per_second``.  A caller may request
    up to ``burst`` tokens in one shot (e.g. for a 50-item batch).  If the
    bucket has fewer tokens than requested, the caller sleeps until enough
    tokens have accumulated.
    """

    def __init__(self, rate_per_second: float = 200.0, burst: int = 250):
        self.rate = rate_per_second
        self.burst = burst
        self._tokens: float = burst
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = COST_DEFAULT) -> None:
        """Wait until ``tokens`` quota units are available, then consume them."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return

            # Not enough tokens -- calculate how long to wait
            deficit = tokens - self._tokens
            wait = deficit / self.rate
            logger.debug(f"Rate limiter: waiting {wait:.2f}s for {tokens} tokens")
            await asyncio.sleep(wait)

            # After sleeping, set tokens to zero (we consumed what we waited for)
            self._last_refill = time.monotonic()
            self._tokens = 0

    def drain(self) -> None:
        """Force the bucket to empty.

        Call this when the API returns a 429 so that subsequent callers
        are guaranteed to pause rather than fire immediately.
        """
        self._tokens = 0
        self._last_refill = time.monotonic()


# ── Singleton ───────────────────────────────────────────────────────
# Shared across all GmailService instances within the same worker process.
# Using 200 units/sec (leaving ~50 units/sec headroom from the 250 limit).
gmail_rate_limiter = TokenBucket(rate_per_second=200.0, burst=250)
