"""Fallback chain — tries a sequence of backends until one succeeds."""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError

from llm_relay.routing.circuit_breaker import CircuitBreaker


class FallbackChain:
    """Iterates over a list of translators until one returns a response.

    Each backend in the chain has an associated ``CircuitBreaker`` so a
    misbehaving provider is skipped quickly without adding latency.
    """

    def __init__(self, translators: list, breaker_threshold: int = 5) -> None:
        if not translators:
            raise ValueError("FallbackChain requires at least one translator")
        self._translators = translators
        self._breakers: dict[str, CircuitBreaker] = {
            self._key(t): CircuitBreaker(
                name=self._key(t),
                failure_threshold=breaker_threshold,
            )
            for t in translators
        }

    @staticmethod
    def _key(translator) -> str:
        return getattr(translator, "DEFAULT_BASE_URL", "") or str(id(translator))

    def try_all(self, build_fn, forward_fn, parse_fn) -> tuple:
        """Try each translator in order; return ``(result, translator)``.

        *build_fn(translator)* must return a bytes payload.
        *forward_fn(translator, payload)* must return raw bytes.
        *parse_fn(translator, raw, req_id)* must return a ParsedResponse.

        The caller is responsible for generating ``req_id`` and including
        it in *parse_fn*.
        """
        last_error: Exception | None = None

        for idx, translator in enumerate(self._translators):
            breaker = self._breakers[self._key(translator)]

            if not breaker.allow_request():
                continue

            try:
                payload = build_fn(translator)
                raw = forward_fn(translator, payload)
                result = parse_fn(translator, raw)
                breaker.record_success()
                return result, translator
            except (HTTPError, URLError) as exc:
                breaker.record_failure()
                last_error = exc
                backoff = min(2 ** idx, 8)
                time.sleep(backoff)
            except Exception:
                breaker.record_failure()
                raise

        raise last_error or RuntimeError("All backends in the fallback chain failed")
