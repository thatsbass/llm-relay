"""Convert Anthropic Messages API requests to the internal canonical format."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedAnthropicRequest:
    """Canonical internal representation of an Anthropic Messages request.

    All protocol-specific details (content blocks, top-level system, etc.)
    are normalised into Chat-Completions-style fields so southbound
    translators work with a single dialect.
    """

    messages: list[dict]
    tools: list[dict] | None
    system: str | None
    stream: bool
    max_tokens: int
    temperature: float | None
    top_p: float | None
    stop_sequences: list[str] | None
    tool_choice: str | dict | None
    thinking: dict | None

    # Preserved for pass-through translators (e.g. DeepSeek /anthropic).
    # When non-None the *entire* original JSON body is available for
    # forwarding without re-assembly.
    original_body: dict | None = None

    # Model requested by the client — preserved for model-aware routing.
    model: str | None = None


# ── Public API ────────────────────────────────────────────────────────────────


def parse_anthropic_request(body: dict) -> ParsedAnthropicRequest:
    """Convert a raw Anthropic Messages API JSON body into a ParsedAnthropicRequest."""
    system = _extract_system(body.get("system"))
    messages = _convert_messages(body.get("messages", []), system)
    tools = _convert_tools(body.get("tools"))

    return ParsedAnthropicRequest(
        messages=messages,
        tools=tools,
        system=system,
        stream=body.get("stream", False),
        max_tokens=body.get("max_tokens", 4096),
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        stop_sequences=body.get("stop_sequences"),
        tool_choice=_convert_tool_choice(body.get("tool_choice")),
        thinking=body.get("thinking"),
        original_body=body,
        model=body.get("model"),
    )


# ── System prompt extraction ──────────────────────────────────────────────────


def _extract_system(system) -> str | None:
    """Extract the system prompt from an Anthropic request.

    Anthropic accepts *system* as either a plain string or an array of
    ``{"type":"text","text":"..."}`` blocks.  We flatten into a single
    string.
    """
    if system is None:
        return None
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts: list[str] = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts) if parts else None
    return str(system)


# ── Message conversion ────────────────────────────────────────────────────────


def _convert_messages(
    anthropic_messages: list[dict],
    system: str | None,
) -> list[dict]:
    """Convert Anthropic ``messages[]`` to Chat Completions ``messages[]``.

    Each Anthropic message has a ``role`` and ``content`` where *content*
    can be a plain string or an array of content blocks
    (text / tool_use / tool_result / thinking / image / document ...).
    """
    converted: list[dict] = []

    # System prompt goes first as a Chat-Completions system message.
    if system is not None:
        converted.append({"role": "system", "content": system})

    for msg in anthropic_messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if isinstance(content, str):
            _handle_string_content(converted, role, content)
        elif isinstance(content, list):
            _handle_block_array(converted, role, content)
        else:
            converted.append({"role": role, "content": str(content or "")})

    if not converted:
        converted.append({"role": "user", "content": "Hello"})

    return converted


def _handle_string_content(
    messages: list[dict],
    role: str,
    content: str,
) -> None:
    """A plain string content → simple role/content message."""
    if role == "assistant":
        messages.append({"role": "assistant", "content": content})
    elif role == "user":
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": content})


def _handle_block_array(
    messages: list[dict],
    role: str,
    blocks: list[dict],
) -> None:
    """Convert an array of Anthropic content blocks to Chat Completions messages.

    An Anthropic ``user`` turn may carry ``tool_result`` blocks alongside
    ``text`` blocks.  Each ``tool_result`` becomes its own ``role: tool``
    message.  Any remaining text is a regular user message.

    An Anthropic ``assistant`` turn may carry ``text``, ``tool_use``, and
    ``thinking`` blocks.  Text becomes assistant content; tool_use blocks
    are collected into ``tool_calls[]``.
    """
    if role == "user":
        _handle_user_blocks(messages, blocks)
    elif role == "assistant":
        _handle_assistant_blocks(messages, blocks)
    else:
        _handle_user_blocks(messages, blocks)


def _handle_user_blocks(messages: list[dict], blocks: list[dict]) -> None:
    tool_results: list[dict] = []
    text_parts: list[str] = []

    for block in blocks:
        block_type = block.get("type", "")
        if block_type == "tool_result":
            tool_results.append(block)
        elif block_type == "text":
            text_parts.append(block.get("text", ""))
        else:
            text_parts.append(str(block))

    if text_parts:
        messages.append({"role": "user", "content": "\n".join(text_parts)})

    for tr in tool_results:
        tc = tr.get("content", "")
        if isinstance(tc, list):
            tc = "\n".join(
                part.get("text", "") if isinstance(part, dict) and part.get("type") == "text" else str(part)
                for part in tc
            )
        messages.append({
            "role":         "tool",
            "tool_call_id": tr.get("tool_use_id", ""),
            "content":      str(tc),
        })


def _handle_assistant_blocks(messages: list[dict], blocks: list[dict]) -> None:
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in blocks:
        block_type = block.get("type", "")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_calls.append({
                "id":   block.get("id", ""),
                "type": "function",
                "function": {
                    "name":      block.get("name", ""),
                    "arguments": _normalise_arguments(block.get("input", {})),
                },
            })
        # thinking blocks are dropped — they are not part of the
        # Chat Completions message format but are preserved in
        # ``ParsedAnthropicRequest.original_body`` for pass-through.

    if tool_calls:
        messages.append({
            "role":       "assistant",
            "content":    None,
            "tool_calls": tool_calls,
        })
    elif text_parts:
        messages.append({
            "role":    "assistant",
            "content": "\n".join(text_parts),
        })


def _normalise_arguments(input_value) -> str:
    """Ensure tool-call arguments are a JSON string."""
    import json
    if isinstance(input_value, str):
        return input_value
    if input_value is None:
        return "{}"
    return json.dumps(input_value)


# ── Tool conversion ───────────────────────────────────────────────────────────


def _convert_tools(anthropic_tools: list[dict] | None) -> list[dict] | None:
    """Convert Anthropic ``tools[]`` to Chat Completions ``tools[]``."""
    if not anthropic_tools:
        return None

    converted: list[dict] = []
    for tool in anthropic_tools:
        if tool.get("type") == "server_tool_use":
            continue  # server-side tools have no client equivalent
        converted.append({
            "type": "function",
            "function": {
                "name":        tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters":  tool.get("input_schema", {}),
            },
        })

    return converted or None


# ── Tool choice conversion ────────────────────────────────────────────────────


def _convert_tool_choice(tool_choice: dict | str | None) -> str | dict | None:
    """Normalise Anthropic ``tool_choice`` to Chat Completions format."""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict):
        tc_type = tool_choice.get("type", "auto")
        if tc_type == "tool":
            return {
                "type": "function",
                "function": {"name": tool_choice.get("name", "")},
            }
        return tc_type
    return None
