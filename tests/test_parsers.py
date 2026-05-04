"""
Tests for llm_relay.parsers.

Covers:
- messages.trim_system_prompt
- messages.input_to_messages (all item types)
- messages.translate_tools
- xml_tools.extract_xml_tool_calls (standard XML, DSML, mixed content)
"""

import unittest

from llm_relay.parsers.messages import (
    input_to_messages,
    translate_tools,
    trim_system_prompt,
)
from llm_relay.parsers.xml_tools import XmlToolCall, extract_xml_tool_calls


# ─────────────────────────────────────────────────────────────────────────────
# trim_system_prompt
# ─────────────────────────────────────────────────────────────────────────────


class TestTrimSystemPrompt(unittest.TestCase):

    def test_none_returns_tool_guide_only(self):
        result = trim_system_prompt(None)
        self.assertIn("HOW TO USE TOOLS", result)
        self.assertNotIn("CODER INSTRUCTIONS", result)

    def test_empty_string_returns_tool_guide_only(self):
        result = trim_system_prompt("")
        self.assertIn("HOW TO USE TOOLS", result)

    def test_short_instructions_are_included_verbatim(self):
        result = trim_system_prompt("You are a helpful coder.")
        self.assertIn("You are a helpful coder.", result)
        self.assertIn("CODER INSTRUCTIONS", result)

    def test_long_instructions_are_trimmed(self):
        # 250 lines — more than the 200-line threshold.
        long = "\n".join(f"line {i}" for i in range(250))
        result = trim_system_prompt(long)
        self.assertIn("[... trimmed ...]", result)
        # First and last lines must be preserved.
        self.assertIn("line 0", result)
        self.assertIn("line 249", result)

    def test_exactly_200_lines_not_trimmed(self):
        exact = "\n".join(f"line {i}" for i in range(200))
        result = trim_system_prompt(exact)
        self.assertNotIn("[... trimmed ...]", result)


# ─────────────────────────────────────────────────────────────────────────────
# input_to_messages — item type handling
# ─────────────────────────────────────────────────────────────────────────────


class TestInputToMessages(unittest.TestCase):

    # ── Empty / sentinel ──────────────────────────────────────────────────────

    def test_empty_input_returns_sentinel(self):
        """An empty input list must never produce an empty messages array."""
        msgs = input_to_messages([])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "Hello")

    def test_none_input_returns_sentinel(self):
        msgs = input_to_messages(None)
        self.assertEqual(msgs[0]["content"], "Hello")

    # ── System prompt injection ───────────────────────────────────────────────

    def test_instructions_injected_as_first_system_message(self):
        msgs = input_to_messages(
            [{"type": "message", "role": "user", "content": "Hi"}],
            instructions="Be concise.",
        )
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("Be concise.", msgs[0]["content"])
        self.assertEqual(msgs[1]["role"], "user")

    # ── type=message ──────────────────────────────────────────────────────────

    def test_message_string_content(self):
        msgs = input_to_messages([
            {"type": "message", "role": "user", "content": "Hello world"}
        ])
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "Hello world")

    def test_message_list_content_joined(self):
        msgs = input_to_messages([{
            "type": "message",
            "role": "user",
            "content": [{"type": "text", "text": "Part A"}, {"type": "text", "text": "Part B"}],
        }])
        self.assertEqual(msgs[0]["content"], "Part A\nPart B")

    def test_developer_role_normalised_to_system(self):
        msgs = input_to_messages([
            {"type": "message", "role": "developer", "content": "sys msg"}
        ])
        self.assertEqual(msgs[0]["role"], "system")

    def test_unknown_role_normalised_to_user(self):
        msgs = input_to_messages([
            {"type": "message", "role": "oracle", "content": "weird role"}
        ])
        self.assertEqual(msgs[0]["role"], "user")

    # ── type=function_call ────────────────────────────────────────────────────

    def test_function_call_creates_assistant_with_tool_calls(self):
        msgs = input_to_messages([{
            "type": "function_call",
            "call_id": "call_abc",
            "name": "exec_command",
            "arguments": '{"command": "ls"}',
        }])
        self.assertEqual(msgs[0]["role"], "assistant")
        self.assertIsNone(msgs[0]["content"])
        tc = msgs[0]["tool_calls"][0]
        self.assertEqual(tc["id"], "call_abc")
        self.assertEqual(tc["function"]["name"], "exec_command")

    def test_consecutive_function_calls_grouped_in_one_assistant_message(self):
        """Parallel tool calls must be grouped under a single assistant message."""
        msgs = input_to_messages([
            {"type": "function_call", "call_id": "c1", "name": "fn_a", "arguments": "{}"},
            {"type": "function_call", "call_id": "c2", "name": "fn_b", "arguments": "{}"},
        ])
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        self.assertEqual(len(assistant_msgs), 1)
        self.assertEqual(len(assistant_msgs[0]["tool_calls"]), 2)

    def test_function_call_missing_call_id_gets_generated_id(self):
        msgs = input_to_messages([{
            "type": "function_call",
            "name": "fn_a",
            "arguments": "{}",
        }])
        tc_id = msgs[0]["tool_calls"][0]["id"]
        self.assertTrue(tc_id.startswith("call_"))

    # ── type=function_call_output ─────────────────────────────────────────────

    def test_function_call_output_creates_tool_message(self):
        msgs = input_to_messages([{
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": "total 8\ndrwxr-xr-x",
        }])
        self.assertEqual(msgs[0]["role"], "tool")
        self.assertEqual(msgs[0]["tool_call_id"], "call_abc")
        self.assertIn("total 8", msgs[0]["content"])

    # ── type=reasoning ────────────────────────────────────────────────────────

    def test_reasoning_with_text_summary_creates_assistant_message(self):
        msgs = input_to_messages([{
            "type": "reasoning",
            "summary": [{"type": "text", "text": "I think the answer is 42."}],
        }])
        self.assertEqual(msgs[0]["role"], "assistant")
        self.assertIn("42", msgs[0]["content"])

    def test_reasoning_empty_summary_is_skipped(self):
        msgs = input_to_messages([
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "user", "content": "After reasoning"},
        ])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "After reasoning")

    # ── Skipped types ─────────────────────────────────────────────────────────

    def test_item_reference_is_skipped(self):
        msgs = input_to_messages([
            {"type": "item_reference", "id": "some_ref"},
            {"type": "message", "role": "user", "content": "real message"},
        ])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "real message")

    def test_computer_call_is_skipped(self):
        msgs = input_to_messages([
            {"type": "computer_call", "action": "screenshot"},
            {"type": "message", "role": "user", "content": "real"},
        ])
        self.assertEqual(len(msgs), 1)

    # ── Generic fallback ──────────────────────────────────────────────────────

    def test_item_with_role_but_no_type_handled_as_generic(self):
        msgs = input_to_messages([{"role": "user", "content": "generic item"}])
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "generic item")

    def test_item_with_content_only_treated_as_user_message(self):
        msgs = input_to_messages([{"content": "bare content"}])
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "bare content")


# ─────────────────────────────────────────────────────────────────────────────
# translate_tools
# ─────────────────────────────────────────────────────────────────────────────


class TestTranslateTools(unittest.TestCase):

    def test_none_returns_none(self):
        self.assertIsNone(translate_tools(None))

    def test_empty_list_returns_none(self):
        self.assertIsNone(translate_tools([]))

    def test_valid_function_tool_is_translated(self):
        tools = [{
            "type": "function",
            "name": "exec_command",
            "description": "Run a shell command",
            "parameters": {"type": "object", "properties": {}},
        }]
        result = translate_tools(tools)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "function")
        self.assertEqual(result[0]["function"]["name"], "exec_command")
        self.assertEqual(result[0]["function"]["description"], "Run a shell command")

    def test_skipped_tools_are_filtered(self):
        tools = [
            {"type": "function", "name": "write_stdin",  "parameters": {}},
            {"type": "function", "name": "send_input",   "parameters": {}},
            {"type": "function", "name": "exec_command", "parameters": {}},
        ]
        result = translate_tools(tools)
        names = [t["function"]["name"] for t in result]
        self.assertNotIn("write_stdin", names)
        self.assertNotIn("send_input", names)
        self.assertIn("exec_command", names)

    def test_non_function_type_is_filtered(self):
        tools = [
            {"type": "computer_use", "name": "click"},
            {"type": "function",     "name": "exec_command", "parameters": {}},
        ]
        result = translate_tools(tools)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["function"]["name"], "exec_command")

    def test_all_tools_filtered_returns_none(self):
        tools = [{"type": "function", "name": "write_stdin", "parameters": {}}]
        self.assertIsNone(translate_tools(tools))


# ─────────────────────────────────────────────────────────────────────────────
# extract_xml_tool_calls
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractXmlToolCalls(unittest.TestCase):

    # ── No XML ────────────────────────────────────────────────────────────────

    def test_plain_text_returns_empty_list_and_original(self):
        calls, text = extract_xml_tool_calls("Hello, world!")
        self.assertEqual(calls, [])
        self.assertEqual(text, "Hello, world!")

    def test_empty_string_returns_empty_list_and_empty_string(self):
        calls, text = extract_xml_tool_calls("")
        self.assertEqual(calls, [])
        self.assertEqual(text, "")

    def test_none_returns_empty_list_and_none(self):
        calls, text = extract_xml_tool_calls(None)
        self.assertEqual(calls, [])
        self.assertIsNone(text)

    # ── Standard XML ──────────────────────────────────────────────────────────

    def test_standard_xml_single_tool_call(self):
        content = (
            "<tool_calls>"
            '<invoke name="exec_command">'
            '<parameter name="command">ls -la</parameter>'
            "</invoke>"
            "</tool_calls>"
        )
        calls, text = extract_xml_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0], XmlToolCall)
        self.assertEqual(calls[0].name, "exec_command")
        self.assertEqual(calls[0].arguments, {"command": "ls -la"})
        self.assertEqual(text, "")

    def test_standard_xml_multiple_parameters(self):
        content = (
            "<tool_calls>"
            '<invoke name="exec_command">'
            '<parameter name="command">git commit</parameter>'
            '<parameter name="cwd">/repo</parameter>'
            "</invoke>"
            "</tool_calls>"
        )
        calls, _ = extract_xml_tool_calls(content)
        self.assertEqual(calls[0].arguments["command"], "git commit")
        self.assertEqual(calls[0].arguments["cwd"], "/repo")

    def test_standard_xml_multiple_tool_calls(self):
        content = (
            "<tool_calls>"
            '<invoke name="fn_a"><parameter name="x">1</parameter></invoke>'
            '<invoke name="fn_b"><parameter name="y">2</parameter></invoke>'
            "</tool_calls>"
        )
        calls, _ = extract_xml_tool_calls(content)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].name, "fn_a")
        self.assertEqual(calls[1].name, "fn_b")

    def test_text_before_and_after_xml_is_preserved(self):
        content = "Before the call.\n<tool_calls><invoke name=\"fn\"><parameter name=\"k\">v</parameter></invoke></tool_calls>\nAfter the call."
        calls, text = extract_xml_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertIn("Before the call.", text)
        self.assertIn("After the call.", text)

    # ── DSML format ───────────────────────────────────────────────────────────

    def test_dsml_format_parsed_correctly(self):
        content = (
            "<｜｜DSML｜｜tool_calls>"
            "<｜｜DSML｜｜invoke name=\"exec_command\">"
            "<｜｜DSML｜｜parameter name=\"command\">pwd</｜｜DSML｜｜parameter>"
            "</｜｜DSML｜｜invoke>"
            "</｜｜DSML｜｜tool_calls>"
        )
        calls, text = extract_xml_tool_calls(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "exec_command")
        self.assertEqual(calls[0].arguments["command"], "pwd")
        self.assertEqual(text, "")

    # ── Clean text output ─────────────────────────────────────────────────────

    def test_clean_text_has_no_xml_tags(self):
        content = "<tool_calls><invoke name=\"fn\"><parameter name=\"k\">v</parameter></invoke></tool_calls>Done."
        _, text = extract_xml_tool_calls(content)
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertIn("Done.", text)

    def test_xml_tool_call_is_immutable(self):
        """XmlToolCall is a frozen dataclass — mutation must raise."""
        call = XmlToolCall(name="fn", arguments={"k": "v"})
        with self.assertRaises((AttributeError, TypeError)):
            call.name = "other"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
