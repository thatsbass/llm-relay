"""Anthropic Messages API pass-through translator.

Forwards the original Anthropic request body to a backend that speaks
the Anthropic Messages API natively (e.g. ``DeepSeek /anthropic``).
"""

from __future__ import annotations

import json
import uuid

from llm_relay.translators.base import AbstractTranslator, ParsedResponse


class AnthropicPassThroughTranslator(AbstractTranslator):
    """Forward Anthropic Messages API requests to a native-Anthropic backend.

    Subclass and set the class-level constants for a specific provider.
    Does NOT translate between Anthropic and Chat Completions — the
    backend must understand the Anthropic protocol.
    """

    DEFAULT_BASE_URL:      str = ""   # e.g. "https://api.deepseek.com/anthropic"
    DEFAULT_CHAT_ENDPOINT: str = "/v1/messages"
    DEFAULT_MODEL:         str = ""

    # Flag telling the handler it can relay SSE events directly.
    supports_anthropic_stream_relay: bool = True

    def __init__(self, config) -> None:
        super().__init__(config)
        self._base_url_effective = (
            getattr(config, "api_base_url", None)
            or self.DEFAULT_BASE_URL
        )

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def base_url(self) -> str:
        return self._base_url_effective

    @property
    def chat_endpoint(self) -> str:
        return self.DEFAULT_CHAT_ENDPOINT

    # ── Pass-through forward ──────────────────────────────────────────────

    def build_request(self, messages, tools, max_output_tokens, tc_count,
                      temperature=None, top_p=None):
        """Fallback build_request (not used in pass-through path)."""
        raise NotImplementedError(
            "Use build_anthropic_request for pass-through translators"
        )

    def parse_response(self, raw_body, req_id):
        """Fallback parse_response (not used in pass-through path)."""
        raise NotImplementedError(
            "Use parse_anthropic_response for pass-through translators"
        )

    def build_anthropic_request(self, original_body: dict) -> bytes:
        """Return the original body as JSON bytes — no transformation needed."""
        return json.dumps(original_body).encode()

    def parse_anthropic_response(
        self, raw_body: bytes, req_id: str
    ) -> ParsedResponse:
        """Convert an Anthropic Messages response into a ParsedResponse.

        The returned ``response`` dict is a thin envelope.  The handler
        uses ``output[]``-style fields for its own SSE simulation in the
        Chat Completions path; for the pass-through path we build a
        lightweight structure that the Anthropic SSE relay can consume.
        """
        data = self._safe_load(raw_body)

        content = data.get("content", [])
        output: list = []

        for block in content:
            block_type = block.get("type", "")
            if block_type == "text":
                output.append({
                    "type":    "message",
                    "role":    "assistant",
                    "content": [{
                        "type": "output_text",
                        "text": block.get("text", ""),
                        "annotations": [],
                    }],
                })
            elif block_type == "tool_use":
                output.append({
                    "type":      "function_call",
                    "id":        block.get("id", ""),
                    "call_id":   block.get("id", ""),
                    "name":      block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {})),
                    "status":    "completed",
                })

        usage = data.get("usage", {})
        response = {
            "id":                  req_id,
            "object":              "response",
            "status":              "completed",
            "model":               data.get("model", self.DEFAULT_MODEL),
            "output":              output,
            "parallel_tool_calls": True,
            "text":                "",
            "usage": {
                "input_tokens":          usage.get("input_tokens", 0),
                "output_tokens":         usage.get("output_tokens", 0),
                "total_tokens":          (usage.get("input_tokens", 0)
                                          + usage.get("output_tokens", 0)),
                "input_tokens_details":  {"cached_tokens": usage.get("cache_read_input_tokens", 0)},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }

        assistant_message = self._build_assistant_message(content)

        return ParsedResponse(response=response, assistant_message=assistant_message)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_assistant_message(content: list) -> dict:
        text_parts = []
        tool_calls = []
        for block in content:
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        if tool_calls:
            return {"role": "assistant", "content": None, "tool_calls": tool_calls}
        return {"role": "assistant", "content": "\n".join(text_parts)}


class DeepSeekAnthropicTranslator(AnthropicPassThroughTranslator):
    """Pass-through to DeepSeek's native Anthropic API endpoint."""

    DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
    DEFAULT_MODEL    = "deepseek-v4-pro"
