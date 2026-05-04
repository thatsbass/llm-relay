"""
Message parser.

Responsibility: convert the OpenAI **Responses API** request format into the
flat ``messages[]`` list expected by any OpenAI-compatible **Chat Completions**
backend (DeepSeek, Mistral, …).

The Responses API ships richer input items — each has a ``"type"`` field that
determines how it maps to a Chat Completions message:

    ┌──────────────────────────┬────────────────────────────────────────────┐
    │ Responses API item type  │ Chat Completions equivalent                │
    ├──────────────────────────┼────────────────────────────────────────────┤
    │ message                  │ {role, content} message                    │
    │ function_call            │ assistant message with tool_calls[]        │
    │ function_call_output     │ tool message with tool_call_id             │
    │ reasoning                │ assistant message (summary text only)      │
    │ item_reference           │ skipped (internal Responses API reference) │
    │ computer_call            │ skipped (not supported by text backends)   │
    └──────────────────────────┴────────────────────────────────────────────┘

Public API
----------
- ``input_to_messages(input_items, instructions)``  — main entry point.
- ``translate_tools(tools)``                         — converts the tools array.
- ``trim_system_prompt(instructions)``               — injects agent guide.
"""

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
    """
    Build the final system prompt sent to the backend.

    If *instructions* is provided (e.g. from Codex CLI's ``--instructions``
    flag), it is trimmed to a safe length and appended after the agent guide.
    Very long prompts are head-tail truncated to stay within token budgets
    without losing the critical opening and closing context.

    Args:
        instructions: Raw system prompt from the client, or ``None``.

    Returns:
        A combined system prompt string ready to be used as the first message.
    """
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
    """
    Normalise a Responses API role to a Chat Completions-compatible role.

    The Responses API allows ``"developer"`` as a privileged system-level role.
    Chat Completions backends do not know this role, so we map it to
    ``"system"``.  Any other unknown role falls back to ``"user"`` to avoid
    API rejections.

    Args:
        role: Raw role string from the input item.

    Returns:
        One of: ``"system"``, ``"user"``, ``"assistant"``, ``"tool"``.
    """
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
    """
    Convert a ``type=function_call`` item to an assistant tool-call message.

    The Chat Completions spec requires tool calls to live inside an assistant
    message under the ``tool_calls`` key.  If the last message is already an
    assistant message, we append to its list (grouping parallel calls);
    otherwise we create a new assistant message.
    """
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
    """
    Convert a ``type=reasoning`` item to an assistant text message.

    Reasoning items carry ``summary`` — a list of text segments produced by
    the model's chain-of-thought.  Backends that don't support reasoning
    natively can still benefit from seeing the summarised reasoning in context.
    We skip empty summaries to avoid polluting the history with blank messages.
    """
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
    """
    Fallback handler for items without a recognised ``type``.

    Items that carry a ``role`` field are treated as plain messages.
    Items that carry only a ``content`` field are treated as user messages.
    Everything else is silently dropped to keep the pipeline robust.
    """
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
    """
    Convert a Responses API ``input[]`` array into a Chat Completions
    ``messages[]`` list.

    Args:
        input_items: The ``input`` field from the Responses API request body.
        instructions: Optional system prompt (e.g. from ``--instructions``).
                      When provided it is prepended as a ``system`` message.

    Returns:
        A non-empty list of Chat Completions message dicts.  If no messages
        could be produced from *input_items*, a single ``{"role": "user",
        "content": "Hello"}`` sentinel is returned so the backend never
        receives an empty messages array (which is an API error).

    Example::

        messages = input_to_messages(
            input_items=[{"type": "message", "role": "user", "content": "Hi"}],
            instructions="You are a coding assistant.",
        )
        # → [
        #     {"role": "system", "content": "..."},
        #     {"role": "user",   "content": "Hi"},
        #   ]
    """
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
    """
    Convert the Responses API ``tools[]`` array to Chat Completions format.

    The Responses API uses a flat structure::

        {"type": "function", "name": "exec_command", "description": "…", "parameters": {…}}

    Chat Completions wraps the function definition under a ``"function"`` key::

        {"type": "function", "function": {"name": "…", "description": "…", "parameters": {…}}}

    Tools listed in ``SKIP_TOOLS`` and non-function tool types are filtered out
    because they are Codex-internal and would cause API errors on the backend.

    Args:
        tools: The ``tools`` field from the Responses API request body.

    Returns:
        A translated list of tool dicts, or ``None`` if the result is empty
        (so callers can check ``if tools:`` idiomatically).
    """
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
