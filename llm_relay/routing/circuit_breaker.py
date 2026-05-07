"""Simple circuit breaker — disables a backend after N consecutive failures."""

from __future__ import annotations

import time


class CircuitBreaker:
    """State machine that protects a backend from repeated calls while it is failing.

    States:
        closed    — normal operation, requests pass through
        open      — circuit is tripped, requests are rejected immediately
        half_open — a single trial request is allowed through to test recovery
    """

    STATE_CLOSED     = "closed"
    STATE_OPEN       = "open"
    STATE_HALF_OPEN  = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._failures = 0
        self._last_failure: float = 0.0
        self._state = self.STATE_CLOSED

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == self.STATE_OPEN

    def record_success(self) -> None:
        """Report a successful call — reset the circuit."""
        self._failures = 0
        self._state = self.STATE_CLOSED

    def record_failure(self) -> None:
        """Report a failed call — may trip the circuit."""
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self._threshold:
            self._state = self.STATE_OPEN

    def allow_request(self) -> bool:
        """Return True if a request may be attempted right now."""
        if self._state == self.STATE_CLOSED:
            return True
        if self._state == self.STATE_OPEN:
            if time.time() - self._last_failure >= self._reset_timeout:
                self._state = self.STATE_HALF_OPEN
                return True
            return False
        # half_open — allow a single trial
        return True
