"""Routing engine — wires translators and fallback chain together."""

from __future__ import annotations

from llm_relay.routing.fallback import FallbackChain
from llm_relay.translators.base import AbstractTranslator


class RoutingEngine:
    """Selects and invokes the appropriate backend translator.

    When a ``fallback_translator`` is configured and the primary
    translator fails, the engine automatically retries through the
    fallback chain with exponential backoff.
    """

    def __init__(
        self,
        primary: AbstractTranslator,
        fallback: AbstractTranslator | None = None,
    ) -> None:
        self._primary = primary
        translators = [primary]
        if fallback is not None:
            translators.append(fallback)
        self._chain = FallbackChain(translators)

    @property
    def primary(self) -> AbstractTranslator:
        return self._primary

    def build_request(self, messages, tools, max_tokens, tc_count,
                      temperature=None, top_p=None):
        """Build a request using the primary translator."""
        return self._primary.build_request(
            messages, tools, max_tokens, tc_count,
            temperature=temperature, top_p=top_p,
        )

    def forward(self, payload: bytes) -> bytes:
        """Forward to the primary translator (fallback handled separately)."""
        return self._primary.forward(payload)

    def parse_response(self, raw_body: bytes, req_id: str):
        """Parse response using the primary translator."""
        return self._primary.parse_response(raw_body, req_id)

    def try_all(self, build_fn, forward_fn, parse_fn) -> tuple:
        """Run the fallback chain; returns ``(result, translator)``."""
        return self._chain.try_all(build_fn, forward_fn, parse_fn)

    def has_pass_through(self) -> bool:
        """Return True if the primary translator supports Anthropic pass-through."""
        return (
            "build_anthropic_request" in type(self._primary).__dict__
            or callable(getattr(self._primary, "build_anthropic_request", None))
        )

    def __getattr__(self, name: str):
        """Delegate unknown attributes to the primary translator."""
        return getattr(self._primary, name)
