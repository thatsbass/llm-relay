"""Generic Chat Completions translator — reusable for any OpenAI-compatible backend."""

from __future__ import annotations

import json
import time
import uuid

from llm_relay.parsers.xml_tools import XmlToolCall, extract_xml_tool_calls
from llm_relay.translators.base import AbstractTranslator, ParsedResponse


class ChatCompletionsTranslator(AbstractTranslator):
    """Generic translator for any OpenAI Chat Completions-compatible backend.

    Subclass and set the three class-level constants to target a specific
    provider (see ``DeepSeekTranslator`` for the canonical example).
    """

    # ── Override these in subclasses ───────────────────────────────────────

    DEFAULT_BASE_URL:      str = ""   # e.g. "https://api.deepseek.com"
    DEFAULT_CHAT_ENDPOINT: str = "/v1/chat/completions"
    DEFAULT_MODEL:         str = ""   # e.g. "deepseek-chat"

    # ── Instance initialisation ────────────────────────────────────────────

    def __init__(self, config) -> None:
        super().__init__(config)

        # Allow the config to override the class-level defaults.  This lets
        # a single translator class serve multiple base URLs (e.g. a
        # self-hosted proxy that points to a different region).
        self._base_url_effective = (
            getattr(config, "api_base_url", None)
            or self.DEFAULT_BASE_URL
        )
        self._model_effective = (
            getattr(config, "model", None)
            or self.DEFAULT_MODEL
        )

    # ── AbstractTranslator properties ─────────────────────────────────────

    @property
    def base_url(self) -> str:
        return self._base_url_effective

    @property
    def chat_endpoint(self) -> str:
        return self.DEFAULT_CHAT_ENDPOINT

    # ── Request builder ───────────────────────────────────────────────────

    def build_request(
        self,
        messages: list,
        tools: list | None,
        max_output_tokens: int,
        tc_count: int,
        temperature: float | None = None,
        top_p: float | None = None,
        model: str | None = None,
    ) -> dict:
        """Assemble the Chat Completions request payload."""
        payload: dict = {
            "model":      model or self._model_effective,
            "messages":   messages,
            "stream":     False,
            "max_tokens": max_output_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = (
                "none"
                if tc_count > self._config.max_tool_call_turns
                else "auto"
            )

        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p

        return payload

    # ── Response parser ───────────────────────────────────────────────────

    def parse_response(self, raw_body: bytes, req_id: str) -> ParsedResponse:
        """Convert a raw Chat Completions response into a ParsedResponse."""
        chat_resp = self._safe_load(raw_body)

        choice  = chat_resp.get("choices", [{}])[0]
        msg     = choice.get("message", {})
        content = msg.get("content") or ""

        native_tool_calls: list = msg.get("tool_calls") or []

        xml_tool_calls, clean_text = extract_xml_tool_calls(content)

        all_tool_calls: list = list(native_tool_calls)
        for xtc in xml_tool_calls:
            all_tool_calls.append(self._xml_tc_to_chat_tc(xtc))

        output = self._build_output(clean_text, all_tool_calls)

        usage    = chat_resp.get("usage", {})
        response = {
            "id":                  req_id,
            "object":              "response",
            "created_at":          int(time.time()),
            "status":              "completed",
            "model":               chat_resp.get("model", self._model_effective),
            "output":              output,
            "parallel_tool_calls": True,
            "text":                content if not native_tool_calls else "",
            "usage":               self._build_usage(usage),
        }

        assistant_message = self._build_assistant_message(msg, all_tool_calls)

        return ParsedResponse(response=response, assistant_message=assistant_message)

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _xml_tc_to_chat_tc(xtc: XmlToolCall) -> dict:
        return {
            "id":   f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name":      xtc.name,
                "arguments": json.dumps(xtc.arguments),
            },
        }

    @staticmethod
    def _build_output(clean_text: str, all_tool_calls: list) -> list:
        output: list = []

        if clean_text and not all_tool_calls:
            output.append({
                "id":      f"msg_{uuid.uuid4().hex[:12]}",
                "type":    "message",
                "role":    "assistant",
                "status":  "completed",
                "content": [{
                    "type":        "output_text",
                    "text":        clean_text,
                    "annotations": [],
                }],
            })

        for tc in all_tool_calls:
            fn = tc.get("function", {})
            output.append({
                "type":      "function_call",
                "id":        tc.get("id", ""),
                "call_id":   tc.get("id", ""),
                "name":      fn.get("name", ""),
                "arguments": fn.get("arguments", ""),
                "status":    "completed",
            })

        return output

    @staticmethod
    def _build_usage(usage: dict) -> dict:
        cached = (
            usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        )
        return {
            "input_tokens":          usage.get("prompt_tokens", 0),
            "output_tokens":         usage.get("completion_tokens", 0),
            "total_tokens":          usage.get("total_tokens", 0),
            "input_tokens_details":  {"cached_tokens": cached},
            "output_tokens_details": {"reasoning_tokens": 0},
        }

    @staticmethod
    def _build_assistant_message(msg: dict, all_tool_calls: list) -> dict:
        if all_tool_calls:
            return {
                "role":       "assistant",
                "content":    None,
                "tool_calls": all_tool_calls,
            }
        return {
            "role":    "assistant",
            "content": msg.get("content"),
        }
