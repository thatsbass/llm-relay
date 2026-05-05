"""Converts OpenAI Responses API input items to Chat Completions messages."""

from __future__ import annotations

import json
import uuid
from typing import Optional

from llm_relay.config import (
    ALLOWED_ROLES,
    ESSENTIAL_RULES,
    SKIP_TOOLS,
    TOOL_GUIDE,
)


# ── System prompt helpers ─────────────────────────────────────────────────────


def trim_system_prompt(instructions: Optional[str]) -> str:
    """Build the final system prompt, head-tail trimming very long instructions."""
    if not instructions:
        return TOOL_GUIDE

    lines = instructions.split("\n")

    if len(lines) > 200:
        # Keep the first 80 lines (intent / persona) and the last 60
        # (constraints / output format), which are the most load-bearing parts
        # of a typical coding-agent system prompt.
        trimmed = "\n".join(lines[:80] + ["[... trimmed ...]"] + lines[-60:])
    else:
        trimmed = instructions

    return "\n\n".join([TOOL_GUIDE, ESSENTIAL_RULES, "# CODER INSTRUCTIONS\n" + trimmed])


# ── Role normalisation ────────────────────────────────────────────────────────


def _norm_role(role: str) -> str:
    """Map Responses API roles to Chat Completions roles; "developer" → "system"."""
    if role in ALLOWED_ROLES:
        return role
    if role == "developer":
        return "system"
    return "user"


# ── Item handlers ─────────────────────────────────────────────────────────────
#
# Each private function handles one item type.  They append to *messages* in
# place and return None so the calling loop stays clean.


def _handle_message(item: dict, messages: list) -> None:
    """Convert a ``type=message`` item to a simple role/content message."""
    role = _norm_role(item.get("role", "user"))
    content = item.get("content", "")

    # The Responses API allows ``content`` to be either a plain string or a
    # list of content-part dicts (e.g. ``[{"type": "text", "text": "…"}]``).
    # Chat Completions only accepts plain strings, so we join the parts.
    if isinstance(content, list):
        content = "\n".join(
            part["text"] if isinstance(part, dict) and "text" in part else str(part)
            for part in content
        )

    messages.append({"role": role, "content": content or ""})


def _handle_function_call(item: dict, messages: list) -> None:
    """Convert a type=function_call item to an assistant message with tool_calls[]."""
    tool_call = {
        "id": item.get("call_id", f"call_{uuid.uuid4().hex[:12]}"),
        "type": "function",
        "function": {
            "name": item.get("name", ""),
            "arguments": item.get("arguments", "{}"),
        },
    }

    if messages and messages[-1]["role"] == "assistant":
        # Append to the existing assistant turn (parallel tool calls).
        messages[-1].setdefault("tool_calls", []).append(tool_call)
    else:
        messages.append({
            "role": "assistant",
            "content": None,   # content must be null when tool_calls is set
            "tool_calls": [tool_call],
        })


def _handle_function_call_output(item: dict, messages: list) -> None:
    """Convert a ``type=function_call_output`` item to a tool result message."""
    messages.append({
        "role": "tool",
        "tool_call_id": item.get("call_id", ""),
        "content": item.get("output", ""),
    })


def _handle_reasoning(item: dict, messages: list) -> None:
    """Convert a type=reasoning item's summary into an assistant text message."""
    summary = item.get("summary", [])
    if not summary:
        return

    parts = summary if isinstance(summary, list) else [summary]
    text = "".join(
        part.get("text", "") if isinstance(part, dict) else str(part)
        for part in parts
    )

    if text:
        messages.append({"role": "assistant", "content": text})


def _handle_generic(item: dict, messages: list) -> None:
    """Fallback handler for items without a recognised type."""
    if "role" in item:
        content = item.get("content", "")
        messages.append({
            "role": _norm_role(item["role"]),
            # Lists are JSON-encoded to preserve structure rather than coerced
            # to strings, which would produce unreadable ``[{...}]`` output.
            "content": json.dumps(content) if isinstance(content, list) else content,
        })
    elif "content" in item:
        messages.append({"role": "user", "content": str(item["content"])})


# ── Dispatcher map ────────────────────────────────────────────────────────────

_ITEM_HANDLERS = {
    "message":              _handle_message,
    "function_call":        _handle_function_call,
    "function_call_output": _handle_function_call_output,
    "reasoning":            _handle_reasoning,
}

# These item types are intentionally ignored — they are Responses-API-internal
# bookkeeping constructs that have no Chat Completions equivalent.
_SKIPPED_TYPES = frozenset({"item_reference", "computer_call"})


# ── Public API ────────────────────────────────────────────────────────────────


def input_to_messages(
    input_items: list,
    instructions: Optional[str] = None,
) -> list:
    """Convert a Responses API input[] array into a Chat Completions messages[] list."""
    messages: list = []

    if instructions:
        messages.append({
            "role": "system",
            "content": trim_system_prompt(instructions),
        })

    for item in input_items or []:
        item_type = item.get("type", "")

        if item_type in _SKIPPED_TYPES:
            continue

        handler = _ITEM_HANDLERS.get(item_type)
        if handler:
            handler(item, messages)
        else:
            _handle_generic(item, messages)

    if not messages:
        # An empty messages list is rejected by all Chat Completions APIs.
        messages.append({"role": "user", "content": "Hello"})

    return messages


def translate_tools(tools: Optional[list]) -> Optional[list]:
    """Translate the Responses API tools[] to Chat Completions format, filtering SKIP_TOOLS."""
    if not tools:
        return None

    translated = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
            },
        }
        for tool in tools
        if tool.get("type") == "function" and tool.get("name") not in SKIP_TOOLS
    ]

    return translated or None
