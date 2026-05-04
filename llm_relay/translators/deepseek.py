"""
DeepSeek translator.

Concrete implementation of ``AbstractTranslator`` for the DeepSeek
Chat Completions API (https://api.deepseek.com/v1/chat/completions).

Responsibilities
----------------
1. ``build_request``  — Assembles the DeepSeek-specific JSON payload from the
                        normalised messages, tools, and config.
2. ``parse_response`` — Converts the DeepSeek JSON response into the OpenAI
                        Responses API format expected by Codex CLI, including:
                          • Extracting native JSON tool calls.
                          • Detecting and parsing inline XML / DSML tool calls.
                          • Building the ``output[]`` array.
                          • Normalising the ``usage`` field.
3. ``forward``        — Inherited from ``AbstractTranslator`` (Bearer auth,
                        TLS validation, 120-second timeout).

DeepSeek-specific notes
-----------------------
- Model: ``deepseek-chat`` (instruction-tuned, supports function calling).
- The API is largely OpenAI-compatible but not identical.
- DeepSeek sometimes returns tool calls as inline XML in ``message.content``
  rather than (or in addition to) the standard ``tool_calls`` JSON field.
  The XML parser in ``llm_relay.parsers.xml_tools`` handles this.
- ``stream`` is always set to ``False``: the proxy receives the full response,
  then *simulates* streaming to the client via SSE (handled in the server layer).
  This avoids partial-JSON parsing complexity in the translator.
"""

from __future__ import annotations

import json
import time
import uuid

from llm_relay.parsers.xml_tools import XmlToolCall, extract_xml_tool_calls
from llm_relay.translators.base import AbstractTranslator, ParsedResponse

# ── DeepSeek constants ────────────────────────────────────────────────────────

_BASE_URL:      str = "https://api.deepseek.com"
_CHAT_ENDPOINT: str = "/v1/chat/completions"
_DEFAULT_MODEL: str = "deepseek-chat"


class DeepSeekTranslator(AbstractTranslator):
    """
    Translator for the DeepSeek Chat Completions API.

    Registered in ``TranslatorFactory`` under the key ``"deepseek"``.
    Instantiated by the factory with the runtime ``Config``; do not
    construct directly in production code.
    """

    # ── AbstractTranslator properties ─────────────────────────────────────────

    @property
    def base_url(self) -> str:
        return _BASE_URL

    @property
    def chat_endpoint(self) -> str:
        return _CHAT_ENDPOINT

    # ── Request builder ───────────────────────────────────────────────────────

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
        Assemble the DeepSeek Chat Completions request payload.

        Args:
            messages:          Full conversation history (Chat Completions format).
            tools:             Translated tools list, or ``None``.
            max_output_tokens: Maximum tokens for the completion.
            tc_count:          Number of tool-call turns already in *messages*.
                               When this exceeds ``config.max_tool_call_turns``,
                               ``tool_choice`` is forced to ``"none"`` so the
                               model is required to produce a text answer and
                               cannot keep looping on tool calls indefinitely.
            temperature:       Forwarded as-is when provided by the client.
            top_p:             Forwarded as-is when provided by the client.

        Returns:
            A dict ready for ``json.dumps()`` and forwarding to DeepSeek.
        """
        payload: dict = {
            "model":      _DEFAULT_MODEL,
            "messages":   messages,
            # Always False: streaming is simulated by the server layer after
            # the full response is received.
            "stream":     False,
            "max_tokens": max_output_tokens,
        }

        if tools:
            payload["tools"] = tools
            # Force a text answer once the tool-call loop is too deep.
            payload["tool_choice"] = (
                "none"
                if tc_count > self._config.max_tool_call_turns
                else "auto"
            )

        # Forward optional sampling parameters only when explicitly provided.
        # Omitting them lets DeepSeek use its own defaults rather than
        # overriding with None, which some backends reject.
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p

        return payload

    # ── Response parser ───────────────────────────────────────────────────────

    def parse_response(self, raw_body: bytes, req_id: str) -> ParsedResponse:
        """
        Convert a raw DeepSeek response into a ``ParsedResponse``.

        Steps
        -----
        1. JSON-decode the raw bytes.
        2. Extract ``choices[0].message`` (content + native tool_calls).
        3. Run the XML/DSML parser on ``message.content`` to catch any
           tool calls emitted as markup rather than JSON.
        4. Merge native and XML tool calls into a single list.
        5. Build the Responses API ``output[]`` array.
        6. Construct the assistant message for session persistence.

        Args:
            raw_body: Raw bytes from ``forward()``.
            req_id:   Proxy-generated request ID (e.g. ``"resp_abc123"``).

        Returns:
            ``ParsedResponse(response=..., assistant_message=...)``.
        """
        chat_resp = self._safe_load(raw_body)

        # ── 1. Extract the first choice ───────────────────────────────────────
        choice  = chat_resp.get("choices", [{}])[0]
        msg     = choice.get("message", {})
        content = msg.get("content") or ""

        # ── 2. Native JSON tool calls ─────────────────────────────────────────
        native_tool_calls: list = msg.get("tool_calls") or []

        # ── 3. XML / DSML tool calls from message.content ────────────────────
        xml_tool_calls, clean_text = extract_xml_tool_calls(content)

        # ── 4. Merge all tool calls into one list ─────────────────────────────
        all_tool_calls: list = list(native_tool_calls)
        for xtc in xml_tool_calls:
            all_tool_calls.append(self._xml_tc_to_chat_tc(xtc))

        # ── 5. Build Responses API output[] ──────────────────────────────────
        output = self._build_output(clean_text, all_tool_calls)

        # ── 6. Build Responses API response body ──────────────────────────────
        usage    = chat_resp.get("usage", {})
        response = {
            "id":                  req_id,
            "object":              "response",
            "created_at":          int(time.time()),
            "status":              "completed",
            "model":               chat_resp.get("model", _DEFAULT_MODEL),
            "output":              output,
            "parallel_tool_calls": True,
            # ``text`` is included for clients that read it directly (e.g.
            # simple integrations that bypass the output[] array).  It is
            # empty when the response contains tool calls only.
            "text":                content if not native_tool_calls else "",
            "usage":               self._build_usage(usage),
        }

        # ── 7. Build the assistant message for session history ────────────────
        assistant_message = self._build_assistant_message(msg, all_tool_calls)

        return ParsedResponse(response=response, assistant_message=assistant_message)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _xml_tc_to_chat_tc(xtc: XmlToolCall) -> dict:
        """
        Convert an ``XmlToolCall`` (from the XML parser) into the standard
        Chat Completions ``tool_calls`` dict shape.

        We generate a fresh UUID-based call ID because XML tool calls do not
        carry one — DeepSeek only includes IDs in the native JSON format.
        """
        return {
            "id":   f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name":      xtc.name,
                # XML parameters are always strings; wrap in a JSON object so
                # the consumer receives a consistent ``arguments`` format.
                "arguments": json.dumps(xtc.arguments),
            },
        }

    @staticmethod
    def _build_output(clean_text: str, all_tool_calls: list) -> list:
        """
        Build the ``output[]`` array for the Responses API response.

        Rules:
        - If there are NO tool calls → emit a single ``type=message`` item
          containing the assistant's text.
        - For EACH tool call → emit a ``type=function_call`` item.
        - If there are tool calls, the text item is omitted (the model is in
          "acting" mode, not "answering" mode).

        This mirrors the behaviour of the real OpenAI Responses API.
        """
        output: list = []

        # Text message (only when there are no tool calls).
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

        # One item per tool call.
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
        """
        Normalise DeepSeek's usage dict to the Responses API ``usage`` schema.

        DeepSeek uses ``prompt_tokens`` / ``completion_tokens``; the Responses
        API uses ``input_tokens`` / ``output_tokens``.
        """
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
        """
        Build the assistant message dict that will be appended to session history.

        When tool calls are present, ``content`` must be ``None`` per the
        Chat Completions spec (some backends reject non-null content alongside
        tool_calls).
        """
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
