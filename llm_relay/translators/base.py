"""Abstract base class and result type for all LLM backend translators."""

from __future__ import annotations

import json
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.request import Request, urlopen

from llm_relay.config import Config


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class ParsedResponse:
    """Holds the client-facing response and the assistant turn for session history."""

    response: dict
    assistant_message: dict


# ── Abstract base ─────────────────────────────────────────────────────────────


class AbstractTranslator(ABC):
    """Interface all LLM backend translators must implement."""

    def __init__(self, config: Config) -> None:
        self._config: Config = config

    # ── Abstract properties ───────────────────────────────────────────────────

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Root URL of the backend API, e.g. ``"https://api.deepseek.com"``."""

    @property
    @abstractmethod
    def chat_endpoint(self) -> str:
        """Chat completions path, e.g. ``"/v1/chat/completions"``."""

    # ── Abstract methods ──────────────────────────────────────────────────────

    @abstractmethod
    def build_request(
        self,
        messages: list,
        tools: list | None,
        max_output_tokens: int,
        tc_count: int,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> dict:
        """Return a backend-specific JSON payload dict ready for forwarding."""

    @abstractmethod
    def parse_response(self, raw_body: bytes, req_id: str) -> ParsedResponse:
        """Convert raw backend bytes into a ParsedResponse."""

    # ── Concrete default implementation ──────────────────────────────────────

    def forward(self, payload: bytes) -> bytes:
        """POST *payload* to the backend with Bearer auth and return raw bytes."""
        url = f"{self.base_url}{self.chat_endpoint}"
        request = Request(url, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", f"Bearer {self._config.api_key}")

        ctx = ssl.create_default_context()
        return urlopen(request, context=ctx, timeout=120).read()

    # ── Helpers available to all subclasses ───────────────────────────────────

    def _full_url(self) -> str:
        """Convenience method — full endpoint URL for logging."""
        return f"{self.base_url}{self.chat_endpoint}"

    @staticmethod
    def _safe_load(raw_body: bytes) -> dict:
        """Parse *raw_body* as JSON, raising a descriptive error on failure."""
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Backend returned non-JSON response: {raw_body[:200]!r}"
            ) from exc
