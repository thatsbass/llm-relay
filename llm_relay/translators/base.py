"""
Abstract translator interface.

Design
------
Every backend integration (DeepSeek, Mistral, …) must subclass
``AbstractTranslator`` and implement its abstract methods.  The HTTP handler
depends **only** on this interface — it never imports a concrete class
directly.  This decoupling means:

  - Adding a new backend = creating one new file, registering it in the factory.
  - The handler never changes when a new backend is added.
  - Each translator can be tested in isolation, without a running server.

Class hierarchy::

    AbstractTranslator  (this file)
        └── DeepSeekTranslator  (deepseek.py)
        └── MistralTranslator   (mistral.py)  ← future

Data contract
-------------
``parse_response()`` returns a ``ParsedResponse`` dataclass instead of a raw
dict.  This makes the two distinct outputs explicit:

  1. ``response``          — the Responses API body sent back to the client.
  2. ``assistant_message`` — the assistant turn appended to session history.

Separating them prevents the handler from having to re-parse the response just
to extract the session-relevant part.
"""

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
    """
    The structured result of ``AbstractTranslator.parse_response()``.

    Attributes:
        response:
            A dict conforming to the OpenAI Responses API response schema.
            This is what the proxy sends back to the client (Codex CLI, etc.).

        assistant_message:
            A single Chat Completions message dict (role=``"assistant"``)
            ready to be appended to the session history.  The handler stores
            this in the ``SessionStore`` so subsequent requests can build on it.
    """

    response: dict
    assistant_message: dict


# ── Abstract base ─────────────────────────────────────────────────────────────


class AbstractTranslator(ABC):
    """
    Interface that all LLM backend translators must implement.

    Subclass contract
    -----------------
    - ``base_url``      — Root URL of the backend API (no trailing slash).
    - ``chat_endpoint`` — Path to the chat completions endpoint.
    - ``build_request`` — Build a backend-specific request payload dict.
    - ``parse_response``— Convert raw backend bytes into a ``ParsedResponse``.

    Concrete behaviour provided by this base
    -----------------------------------------
    - ``forward(payload)`` — Sends *payload* via HTTPS with Bearer auth and
      returns raw response bytes.  Works for any standard REST backend.
      Subclasses that need custom auth or transport can override this method.

    Usage::

        translator = TranslatorFactory.create("deepseek", config)

        payload = translator.build_request(messages, tools, max_tokens, tc_count)
        raw     = translator.forward(json.dumps(payload).encode())
        result  = translator.parse_response(raw, req_id)

        send_to_client(result.response)
        session_store.save(req_id, history + [result.assistant_message])
    """

    def __init__(self, config: Config) -> None:
        """
        Args:
            config: Immutable runtime configuration injected by the factory.
                    Stored as ``self._config`` for use by all methods.
        """
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
        """
        Build the backend-specific JSON request payload.

        Args:
            messages:          Full conversation history in Chat Completions
                               format (already translated by the parsers).
            tools:             Translated tools array, or ``None`` if the
                               request carries no tools.
            max_output_tokens: Token budget for this completion.
            tc_count:          Number of tool-call turns already in *messages*.
                               Used to decide whether to force
                               ``tool_choice="none"`` and break potential loops.
            temperature:       Sampling temperature forwarded from the client,
                               or ``None`` to use the backend's default.
            top_p:             Nucleus sampling parameter forwarded from the
                               client, or ``None`` to use the backend's default.

        Returns:
            A dict ready to be JSON-serialised and sent to the backend.
        """

    @abstractmethod
    def parse_response(self, raw_body: bytes, req_id: str) -> ParsedResponse:
        """
        Convert the backend's raw response bytes into a ``ParsedResponse``.

        Args:
            raw_body: Raw bytes returned by ``forward()``.
            req_id:   Unique ID generated by the proxy for this request.
                      Included in the Responses API response as ``"id"``.

        Returns:
            A ``ParsedResponse`` with the client-facing response and the
            assistant message to persist in the session store.

        Raises:
            json.JSONDecodeError: If *raw_body* is not valid JSON.
            KeyError / IndexError: If the backend response is malformed.
        """

    # ── Concrete default implementation ──────────────────────────────────────

    def forward(self, payload: bytes) -> bytes:
        """
        Send *payload* to the backend via HTTPS POST and return raw bytes.

        This default implementation works for any backend that accepts:
          - ``Content-Type: application/json``
          - ``Authorization: Bearer <api_key>``

        Override this method in a subclass if the backend requires a different
        authentication scheme, custom headers, or a non-standard HTTP setup.

        Args:
            payload: JSON-serialised request body.

        Returns:
            Raw response bytes from the backend.

        Raises:
            urllib.error.HTTPError: On 4xx / 5xx responses from the backend.
            urllib.error.URLError:  On connection-level failures (DNS, timeout).
        """
        url = f"{self.base_url}{self.chat_endpoint}"
        request = Request(url, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", f"Bearer {self._config.api_key}")

        # ssl.create_default_context() validates the backend's TLS certificate
        # against the system CA bundle — never skip this in production.
        ctx = ssl.create_default_context()
        return urlopen(request, context=ctx, timeout=120).read()

    # ── Helpers available to all subclasses ───────────────────────────────────

    def _full_url(self) -> str:
        """Convenience method — full endpoint URL for logging."""
        return f"{self.base_url}{self.chat_endpoint}"

    @staticmethod
    def _safe_load(raw_body: bytes) -> dict:
        """
        Parse *raw_body* as JSON, raising a clear error on failure.

        A static method so subclasses can call it without ``self``.
        """
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Backend returned non-JSON response: {raw_body[:200]!r}"
            ) from exc
