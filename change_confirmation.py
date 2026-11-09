"""Short-lived, single-use confirmations for an exact operation and data state.

This prevents unconfirmed or stale app requests, not an agent confirming its own
dialog. It does not authenticate a human or protect direct filesystem access.
"""
from __future__ import annotations

import secrets
import threading
import time


class Confirmations:
    def __init__(self, *, lifetime: int = 300, limit: int = 256):
        self.lifetime = lifetime
        self.limit = limit
        self._pending: dict[str, tuple[str, str, float]] = {}
        self._lock = threading.Lock()

    def check(self, token: str, owner: str, fingerprint: str) -> str | None:
        """Consume a matching confirmation or issue a fresh one without executing."""
        with self._lock:
            now = time.monotonic()
            self._pending = {k: v for k, v in self._pending.items() if v[2] > now}
            entry = self._pending.get(token)
            if entry and entry[:2] == (owner, fingerprint):
                del self._pending[token]
                return None
            # Invalid/stale tokens never authorize the new state. Discard only
            # this owner's token, so another browser cannot consume it.
            if entry and entry[0] == owner:
                del self._pending[token]
            while len(self._pending) >= self.limit:
                del self._pending[next(iter(self._pending))]
            fresh = secrets.token_urlsafe(32)
            self._pending[fresh] = (owner, fingerprint, now + self.lifetime)
            return fresh

    def discard(self, token: str, owner: str) -> None:
        with self._lock:
            entry = self._pending.get(token)
            if entry and entry[0] == owner:
                del self._pending[token]
