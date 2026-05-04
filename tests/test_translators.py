"""
Tests for llm_relay.translators.

Covers:
- TranslatorFactory: registration, creation, error handling
- DeepSeekTranslator.build_request: payload structure, tool_choice logic
- DeepSeekTranslator.parse_response: text, native tool calls, XML tool calls, usage
"""

import json
import unittest
from typing import Optional

from llm_relay.config import Config
from llm_relay.translators.base import AbstractTranslator, ParsedResponse
from llm_relay.translators.deepseek import DeepSeekTranslator
from llm_relay.translators.factory import TranslatorFactory


# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_config(**overrides) -> Config:
    """Build a minimal Config for tests without reading os.environ."""
    defaults = dict(
        port=8080,
        api_key="sk-test-key-1234",
        backend="deepseek",
        debug=False,
        max_output_tokens=4096,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_deepseek_response(
    content: str = "",
    tool_calls: Optional[list] = None,
    model: str = "deepseek-chat",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
) -> bytes:
    """Build a minimal DeepSeek API response body (as bytes)."""
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls

    return json.dumps({
        "id": "ds-abc",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": 5},
        },
    }).encode()


# ─────────────────────────────────────────────────────────────────────────────
# TranslatorFactory
# ─────────────────────────────────────────────────────────────────────────────


class TestTranslatorFactory(unittest.TestCase):

    def test_create_deepseek_returns_deepseek_translator(self):
        config = _make_config()
        translator = TranslatorFactory.create("deepseek", config)
        self.assertIsInstance(translator, DeepSeekTranslator)

    def test_create_is_case_insensitive(self):
        config = _make_config()
        self.assertIsInstance(TranslatorFactory.create("DeepSeek", config), DeepSeekTranslator)
        self.assertIsInstance(TranslatorFactory.create("DEEPSEEK", config), DeepSeekTranslator)

    def test_create_unknown_backend_raises_value_error(self):
        config = _make_config()
        with self.assertRaises(ValueError) as ctx:
            TranslatorFactory.create("unknown_backend", config)
        self.assertIn("unknown_backend", str(ctx.exception))
        self.assertIn("deepseek", str(ctx.exception))   # lists available backends

    def test_register_non_translator_raises_type_error(self):
        class NotATranslator:
            pass
        with self.assertRaises(TypeError):
            TranslatorFactory.register("bad", NotATranslator)  # type: ignore

    def test_register_and_create_custom_backend(self):
        """A newly registered backend must be immediately available."""

        class _StubTranslator(AbstractTranslator):
            @property
            def base_url(self): return "https://stub"
            @property
            def chat_endpoint(self): return "/v1/chat"
            def build_request(self, messages, tools, max_output_tokens, tc_count): return {}
            def parse_response(self, raw_body, req_id): return ParsedResponse({}, {})

        TranslatorFactory.register("stub_test", _StubTranslator)
        t = TranslatorFactory.create("stub_test", _make_config())
        self.assertIsInstance(t, _StubTranslator)

    def test_available_backends_includes_deepseek(self):
        self.assertIn("deepseek", TranslatorFactory.available_backends())

    def test_available_backends_is_sorted(self):
        backends = TranslatorFactory.available_backends()
        self.assertEqual(backends, sorted(backends))


# ─────────────────────────────────────────────────────────────────────────────
# DeepSeekTranslator — properties
# ─────────────────────────────────────────────────────────────────────────────


class TestDeepSeekTranslatorProperties(unittest.TestCase):

    def setUp(self):
        self.t = DeepSeekTranslator(_make_config())

    def test_base_url(self):
        self.assertEqual(self.t.base_url, "https://api.deepseek.com")

    def test_chat_endpoint(self):
        self.assertEqual(self.t.chat_endpoint, "/v1/chat/completions")

    def test_full_url(self):
        self.assertIn("deepseek.com", self.t._full_url())
        self.assertIn("/v1/chat/completions", self.t._full_url())


# ─────────────────────────────────────────────────────────────────────────────
# DeepSeekTranslator.build_request
# ─────────────────────────────────────────────────────────────────────────────


class TestDeepSeekBuildRequest(unittest.TestCase):

    def setUp(self):
        self.t = DeepSeekTranslator(_make_config())
        self.messages = [{"role": "user", "content": "Hello"}]

    def test_basic_payload_structure(self):
        payload = self.t.build_request(self.messages, None, 4096, 0)
        self.assertEqual(payload["model"], "deepseek-chat")
        self.assertEqual(payload["messages"], self.messages)
        self.assertFalse(payload["stream"])    # always False — we simulate streaming
        self.assertEqual(payload["max_tokens"], 4096)

    def test_no_tools_omits_tools_and_tool_choice(self):
        payload = self.t.build_request(self.messages, None, 4096, 0)
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)

    def test_with_tools_sets_tool_choice_auto(self):
        tools = [{"type": "function", "function": {"name": "exec_command"}}]
        payload = self.t.build_request(self.messages, tools, 4096, tc_count=0)
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"], "auto")

    def test_tool_choice_none_when_tc_count_exceeds_limit(self):
        """When the model has called tools too many times, force a text answer."""
        config = _make_config()
        tools = [{"type": "function", "function": {"name": "fn"}}]
        # tc_count = max_tool_call_turns + 1 → should trigger "none"
        payload = self.t.build_request(
            self.messages, tools, 4096,
            tc_count=config.max_tool_call_turns + 1,
        )
        self.assertEqual(payload["tool_choice"], "none")

    def test_tool_choice_auto_at_exact_limit(self):
        """At exactly the limit (not over), tool_choice should still be auto."""
        config = _make_config()
        tools = [{"type": "function", "function": {"name": "fn"}}]
        payload = self.t.build_request(
            self.messages, tools, 4096,
            tc_count=config.max_tool_call_turns,  # exactly at limit, not over
        )
        self.assertEqual(payload["tool_choice"], "auto")

    def test_max_output_tokens_is_forwarded(self):
        payload = self.t.build_request(self.messages, None, 8192, 0)
        self.assertEqual(payload["max_tokens"], 8192)


# ─────────────────────────────────────────────────────────────────────────────
# DeepSeekTranslator.parse_response
# ─────────────────────────────────────────────────────────────────────────────


class TestDeepSeekParseResponse(unittest.TestCase):

    def setUp(self):
        self.t = DeepSeekTranslator(_make_config())
        self.req_id = "resp_test_001"

    # ── Text-only response ────────────────────────────────────────────────────

    def test_text_response_output_contains_message(self):
        raw = _make_deepseek_response(content="Hello, world!")
        result = self.t.parse_response(raw, self.req_id)
        self.assertIsInstance(result, ParsedResponse)
        output = result.response["output"]
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["type"], "message")
        self.assertEqual(output[0]["content"][0]["text"], "Hello, world!")

    def test_text_response_assistant_message(self):
        raw = _make_deepseek_response(content="Hi")
        result = self.t.parse_response(raw, self.req_id)
        am = result.assistant_message
        self.assertEqual(am["role"], "assistant")
        self.assertEqual(am["content"], "Hi")
        self.assertNotIn("tool_calls", am)

    def test_response_id_and_status(self):
        raw = _make_deepseek_response(content="ok")
        result = self.t.parse_response(raw, self.req_id)
        self.assertEqual(result.response["id"], self.req_id)
        self.assertEqual(result.response["status"], "completed")

    # ── Native JSON tool calls ────────────────────────────────────────────────

    def test_native_tool_call_emits_function_call_output_item(self):
        tc = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "exec_command", "arguments": '{"command": "ls"}'},
        }
        raw = _make_deepseek_response(tool_calls=[tc])
        result = self.t.parse_response(raw, self.req_id)
        output = result.response["output"]
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["type"], "function_call")
        self.assertEqual(output[0]["name"], "exec_command")
        self.assertEqual(output[0]["call_id"], "call_abc")

    def test_native_tool_call_assistant_message_has_null_content(self):
        tc = {"id": "c1", "type": "function",
              "function": {"name": "fn", "arguments": "{}"}}
        raw = _make_deepseek_response(tool_calls=[tc])
        result = self.t.parse_response(raw, self.req_id)
        am = result.assistant_message
        self.assertIsNone(am["content"])
        self.assertIn("tool_calls", am)

    def test_multiple_native_tool_calls(self):
        tcs = [
            {"id": "c1", "type": "function", "function": {"name": "fn_a", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "fn_b", "arguments": "{}"}},
        ]
        raw = _make_deepseek_response(tool_calls=tcs)
        result = self.t.parse_response(raw, self.req_id)
        fn_calls = [o for o in result.response["output"] if o["type"] == "function_call"]
        self.assertEqual(len(fn_calls), 2)

    # ── XML / DSML tool calls ─────────────────────────────────────────────────

    def test_xml_tool_call_in_content_is_parsed(self):
        xml_content = (
            '<tool_calls><invoke name="exec_command">'
            '<parameter name="command">pwd</parameter>'
            '</invoke></tool_calls>'
        )
        raw = _make_deepseek_response(content=xml_content)
        result = self.t.parse_response(raw, self.req_id)
        fn_calls = [o for o in result.response["output"] if o["type"] == "function_call"]
        self.assertEqual(len(fn_calls), 1)
        self.assertEqual(fn_calls[0]["name"], "exec_command")

    def test_xml_tool_call_arguments_are_json_encoded(self):
        xml_content = (
            '<tool_calls><invoke name="fn">'
            '<parameter name="key">value</parameter>'
            '</invoke></tool_calls>'
        )
        raw = _make_deepseek_response(content=xml_content)
        result = self.t.parse_response(raw, self.req_id)
        fn_call = result.response["output"][0]
        args = json.loads(fn_call["arguments"])
        self.assertEqual(args["key"], "value")

    def test_xml_tool_call_id_is_generated(self):
        xml_content = (
            '<tool_calls><invoke name="fn">'
            '<parameter name="k">v</parameter>'
            '</invoke></tool_calls>'
        )
        raw = _make_deepseek_response(content=xml_content)
        result = self.t.parse_response(raw, self.req_id)
        call_id = result.response["output"][0]["call_id"]
        self.assertTrue(call_id.startswith("call_"))

    # ── Usage normalisation ───────────────────────────────────────────────────

    def test_usage_fields_are_normalised(self):
        raw = _make_deepseek_response(content="ok", prompt_tokens=100, completion_tokens=50)
        result = self.t.parse_response(raw, self.req_id)
        usage = result.response["usage"]
        self.assertEqual(usage["input_tokens"], 100)
        self.assertEqual(usage["output_tokens"], 50)
        self.assertEqual(usage["total_tokens"], 150)

    def test_usage_cached_tokens_extracted(self):
        raw = _make_deepseek_response(content="ok")
        result = self.t.parse_response(raw, self.req_id)
        cached = result.response["usage"]["input_tokens_details"]["cached_tokens"]
        self.assertEqual(cached, 5)   # set in _make_deepseek_response

    def test_usage_reasoning_tokens_always_zero(self):
        raw = _make_deepseek_response(content="ok")
        result = self.t.parse_response(raw, self.req_id)
        reasoning = result.response["usage"]["output_tokens_details"]["reasoning_tokens"]
        self.assertEqual(reasoning, 0)

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_invalid_json_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.t.parse_response(b"not json at all", self.req_id)

    def test_empty_content_produces_no_message_item(self):
        raw = _make_deepseek_response(content="")
        result = self.t.parse_response(raw, self.req_id)
        msg_items = [o for o in result.response["output"] if o["type"] == "message"]
        self.assertEqual(len(msg_items), 0)


if __name__ == "__main__":
    unittest.main()
