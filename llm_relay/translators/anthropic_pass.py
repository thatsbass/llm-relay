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

    # Map Claude model names (sent by Claude Desktop) to backend model IDs.
    MODEL_MAP: dict[str, str] = {}

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
        """Forward the original body, remapping model + forcing non-streaming.

        Claude Desktop sends Anthropic model names (e.g. ``claude-sonnet-4-6``).
        We remap them to backend-specific model IDs via ``MODEL_MAP``.
        """
        body = dict(original_body)
        body["stream"] = False

        model = body.get("model", "")
        body["model"] = self.MODEL_MAP.get(model, model)

        return json.dumps(body).encode()

    def parse_anthropic_response(
        self, raw_body: bytes, req_id: str
    ) -> ParsedResponse:
        """Convert an Anthropic Messages response into a ParsedResponse."""
        data = self._safe_load(raw_body)

        # Handle error responses gracefully.
        if "error" in data:
            err = data["error"]
            error_response = {
                "id":     req_id,
                "object": "response",
                "status": "failed",
                "model":  "unknown",
                "output": [{
                    "type":    "message",
                    "role":    "assistant",
                    "content": [{
                        "type":        "output_text",
                        "text":        f"[Backend error] {err.get('message', str(err))}",
                        "annotations": [],
                    }],
                }],
                "text": "",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}},
            }
            return ParsedResponse(
                response=error_response,
                assistant_message={"role": "assistant", "content": f"Error: {err.get('message')}"},
            )

        content = data.get("content", [])
        output: list = []

        for block in content:
            block_type = block.get("type", "")
            if block_type == "text":
                output.append({
                    "type":    "message",
                    "role":    "assistant",
                    "content": [{
                        "type":        "output_text",
                        "text":        block.get("text", ""),
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
            # Claude Desktop expects a recognizable model name in the
            # SSE message_start event.  Use what the backend returned;
            # DeepSeek /anthropic maps unknown models to deepseek-v4-flash.
            "model":               data.get("model", "deepseek-v4-flash"),
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
            # Keep the raw fallback for debugging.
            "_anthropic_raw": data,
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

    MODEL_MAP = {
        "claude-sonnet-4-6":  "deepseek-v4-pro",
        "claude-sonnet-4-5":  "deepseek-v4-pro",
        "claude-opus-4-7":    "deepseek-v4-pro",
        "claude-opus-4-6":    "deepseek-v4-pro",
        "claude-haiku-4-5":   "deepseek-v4-flash",
        "claude-sonnet-4":    "deepseek-v4-pro",
        "claude-opus-4":      "deepseek-v4-pro",
        "claude-haiku-3-5":   "deepseek-v4-flash",
    }
