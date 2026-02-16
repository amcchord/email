"""Multi-key sequence handler for vim-style keyboard shortcuts."""

from __future__ import annotations

import time


class KeySequenceHandler:
    """Handles vim-style multi-key sequences like `g f`, `g i`, etc.

    Usage:
        handler = KeySequenceHandler()

        # In the key event handler:
        action = handler.process_key("g")  # Returns None (pending)
        action = handler.process_key("f")  # Returns "g_f"

        # If timeout elapses or non-sequence key is pressed:
        action = handler.process_key("g")  # Returns None (pending)
        action = handler.process_key("x")  # Returns "x" (no sequence match)
    """

    # Keys that can start a multi-key sequence
    SEQUENCE_STARTERS = {"g"}

    # Valid second keys when a sequence starter is pending.
    # Maps (starter, second_key) -> action string
    SEQUENCES = {
        ("g", "f"): "g_f",
        ("g", "i"): "g_i",
        ("g", "l"): "g_l",
        ("g", "t"): "g_t",
        ("g", "s"): "g_s",
        ("g", "a"): "g_a",
        ("g", "h"): "g_h",
        ("g", "comma"): "g_comma",
    }

    TIMEOUT = 1.0  # seconds

    def __init__(self) -> None:
        self._pending: str | None = None
        self._pending_time: float = 0.0

    def process_key(self, key: str) -> str | None:
        """Process a key press and return an action string or None.

        Returns:
            - None if the key starts a pending sequence (waiting for next key)
            - An action string like "g_f" if a sequence is completed
            - The key itself if it is a standalone action
            - The key itself if the pending sequence timed out or no match
        """
        now = time.monotonic()

        # Check if we have a pending sequence starter
        if self._pending is not None:
            elapsed = now - self._pending_time
            starter = self._pending
            self._pending = None

            if elapsed <= self.TIMEOUT:
                # Check if (starter, key) forms a valid sequence
                action = self.SEQUENCES.get((starter, key))
                if action is not None:
                    return action

            # No valid sequence: the pending key was consumed,
            # just process the current key as a standalone
            # (We intentionally drop the starter key to avoid double actions)
            if key in self.SEQUENCE_STARTERS:
                self._pending = key
                self._pending_time = now
                return None
            return key

        # No pending sequence; check if this key starts one
        if key in self.SEQUENCE_STARTERS:
            self._pending = key
            self._pending_time = now
            return None

        # Standalone key
        return key

    def has_pending(self) -> bool:
        """Check if there is a pending sequence starter."""
        if self._pending is None:
            return False
        elapsed = time.monotonic() - self._pending_time
        if elapsed > self.TIMEOUT:
            self._pending = None
            return False
        return True

    def clear(self) -> None:
        """Clear any pending sequence."""
        self._pending = None
