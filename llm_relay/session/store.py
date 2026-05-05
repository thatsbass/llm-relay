"""Thread-safe LRU store mapping response IDs to conversation histories."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional


class SessionStore:
    """LRU in-memory store for per-session conversation histories."""

    def __init__(self, max_sessions: int, trim_to: int) -> None:
        if trim_to >= max_sessions:
            raise ValueError(
                f"trim_to ({trim_to}) must be less than max_sessions ({max_sessions})"
            )
        self._max_sessions = max_sessions
        self._trim_to      = trim_to
        # OrderedDict gives O(1) LRU: move_to_end → mark recent, popitem(last=False) → evict oldest
        self._store: OrderedDict[str, list] = OrderedDict()
        self._lock  = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> Optional[list]:
        """Return a copy of the session history, or None if not found."""
        with self._lock:
            if session_id not in self._store:
                return None
            self._store.move_to_end(session_id)
            return list(self._store[session_id])

    def save(self, session_id: str, messages: list) -> None:
        """Persist messages under session_id, evicting old sessions if needed."""
        with self._lock:
            self._store[session_id] = list(messages)
            self._store.move_to_end(session_id)
            self._evict_if_needed()

    def delete(self, session_id: str) -> None:
        """Remove session_id from the store (no-op if absent)."""
        with self._lock:
            self._store.pop(session_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._store

    # ── Internal ──────────────────────────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        """Drop LRU sessions until within limits. Must be called under self._lock."""
        if len(self._store) <= self._max_sessions:
            return
        for _ in range(len(self._store) - self._trim_to):
            if self._store:
                self._store.popitem(last=False)
