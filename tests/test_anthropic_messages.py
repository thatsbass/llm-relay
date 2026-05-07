"""Tests for the Anthropic Messages API parser."""

import unittest
from llm_relay.parsers.anthropic_messages import (
    parse_anthropic_request,
    _extract_system,
    _convert_messages,
    _convert_tools,
    _convert_tool_choice,
)


class TestParseAnthropicRequest(unittest.TestCase):
    def test_minimal_request(self):
        body = {
            "model": "claude-sonnet-4",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hello"}],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.model, "claude-sonnet-4")
        self.assertEqual(r.max_tokens, 1024)
        self.assertFalse(r.stream)
        self.assertEqual(len(r.messages), 1)
        self.assertEqual(r.messages[0]["role"], "user")
        self.assertEqual(r.messages[0]["content"], "Hello")

    def test_system_string(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "Hi"}],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.system, "You are helpful.")
        self.assertEqual(len(r.messages), 2)
        self.assertEqual(r.messages[0]["role"], "system")

    def test_system_array(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "system": [
                {"type": "text", "text": "Part 1."},
                {"type": "text", "text": "Part 2."},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.system, "Part 1.\nPart 2.")

    def test_content_blocks_user_text(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
            ],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.messages[0]["role"], "user")
        self.assertEqual(r.messages[0]["content"], "Hello")

    def test_content_blocks_assistant_tool_use(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t1", "name": "bash",
                     "input": {"command": "ls"}}
                ]}
            ],
        }
        r = parse_anthropic_request(body)
        msg = r.messages[0]
        self.assertEqual(msg["role"], "assistant")
        self.assertIsNone(msg["content"])
        tc = msg["tool_calls"][0]
        self.assertEqual(tc["id"], "t1")
        self.assertEqual(tc["function"]["name"], "bash")
        self.assertEqual(tc["function"]["arguments"], '{"command": "ls"}')

    def test_content_blocks_tool_result(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "result"}
                ]}
            ],
        }
        r = parse_anthropic_request(body)
        msg = r.messages[0]
        self.assertEqual(msg["role"], "tool")
        self.assertEqual(msg["tool_call_id"], "t1")
        self.assertEqual(msg["content"], "result")

    def test_tool_result_list_content(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t2", "content": [
                        {"type": "text", "text": "line1"},
                        {"type": "text", "text": "line2"},
                    ]}
                ]}
            ],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.messages[0]["content"], "line1\nline2")

    def test_tools_conversion(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {"name": "bash", "description": "run cmd",
                 "input_schema": {"type": "object", "properties": {}}}
            ],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(len(r.tools), 1)
        self.assertEqual(r.tools[0]["type"], "function")
        self.assertEqual(r.tools[0]["function"]["name"], "bash")
        self.assertEqual(r.tools[0]["function"]["description"], "run cmd")

    def test_server_tools_filtered(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {"name": "bash", "input_schema": {}},
                {"type": "server_tool_use", "name": "web_search"},
            ],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(len(r.tools), 1)
        self.assertEqual(r.tools[0]["function"]["name"], "bash")

    def test_tool_choice_auto(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "auto"},
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.tool_choice, "auto")

    def test_tool_choice_tool(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "tool", "name": "bash"},
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.tool_choice, {"type": "function", "function": {"name": "bash"}})

    def test_stream_detection(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }
        r = parse_anthropic_request(body)
        self.assertTrue(r.stream)

    def test_optional_params(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.5,
            "top_p": 0.9,
            "stop_sequences": ["END"],
            "thinking": {"type": "enabled", "budget_tokens": 2000},
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.temperature, 0.5)
        self.assertEqual(r.top_p, 0.9)
        self.assertEqual(r.stop_sequences, ["END"])
        self.assertEqual(r.thinking, {"type": "enabled", "budget_tokens": 2000})

    def test_original_body_preserved(self):
        body = {
            "model": "x",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }
        r = parse_anthropic_request(body)
        self.assertEqual(r.original_body, body)


class TestExtractSystem(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(_extract_system(None))

    def test_string(self):
        self.assertEqual(_extract_system("Hello"), "Hello")

    def test_array(self):
        self.assertEqual(
            _extract_system([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]),
            "a\nb",
        )

    def test_array_non_text_ignored(self):
        result = _extract_system([{"type": "image", "url": "x"}, {"type": "text", "text": "a"}])
        self.assertEqual(result, "a")


class TestConvertToolChoice(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(_convert_tool_choice(None))

    def test_string(self):
        self.assertEqual(_convert_tool_choice("auto"), "auto")

    def test_dict_auto(self):
        self.assertEqual(_convert_tool_choice({"type": "auto"}), "auto")

    def test_dict_tool(self):
        self.assertEqual(
            _convert_tool_choice({"type": "tool", "name": "bash"}),
            {"type": "function", "function": {"name": "bash"}},
        )
