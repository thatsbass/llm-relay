"""
XML / DSML tool-call parser.

Problem
-------
The Chat Completions spec defines tool calls as structured JSON in
``message.tool_calls[]``.  However, some backends (notably DeepSeek) sometimes
emit tool calls as inline XML inside ``message.content`` instead — or worse, in
a proprietary dialect called **DSML** (DeepSeek Markup Language) that prefixes
every tag with the Unicode sequence ``｜｜DSML｜｜``.

Standard XML example::

    <tool_calls>
      <invoke name="exec_command">
        <parameter name="command">ls -la</parameter>
      </invoke>
    </tool_calls>

DSML example (same structure, different tag names)::

    <｜｜DSML｜｜tool_calls>
      <｜｜DSML｜｜invoke name="exec_command">
        <｜｜DSML｜｜parameter name="command">ls -la</｜｜DSML｜｜parameter>
      </｜｜DSML｜｜invoke>
    </｜｜DSML｜｜tool_calls>

Solution
--------
This module uses a set of compiled regular expressions that match *both*
variants via an optional ``(?:｜｜DSML｜｜)?`` prefix group.  The parsed
tool calls are normalised into ``XmlToolCall`` objects and the XML markup
is stripped from the content string so the caller receives clean text.

Public API
----------
- ``XmlToolCall``            — lightweight result dataclass.
- ``extract_xml_tool_calls`` — main entry point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple


# ── DSML / XML regex patterns ─────────────────────────────────────────────────
#
# The ``(?:｜｜DSML｜｜)?`` prefix (stored in _DSML_PREFIX) makes every pattern
# match both the standard ``<tag>`` form and the DSML ``<｜｜DSML｜｜tag>`` form
# without duplicating any regex logic.
#
# NOTE: The characters between the pipes are Unicode FULLWIDTH VERTICAL LINE
# (U+FF5C), not ASCII pipe characters.  They are part of DeepSeek's markup.

_DSML_PREFIX: str = r"(?:｜｜DSML｜｜)?"

# Matches the outer <tool_calls> … </tool_calls> wrapper block (entire block,
# used for stripping — we don't capture its contents here).
_TOOL_CALLS_RE: re.Pattern = re.compile(
    r"<" + _DSML_PREFIX + r"tool_calls\s*>.*?</" + _DSML_PREFIX + r"tool_calls>",
    re.DOTALL,
)

# Matches <invoke name="fn_name"> … </invoke> and captures:
#   group(1) → function name
#   group(2) → raw inner content (may contain <parameter> tags)
_INVOKE_RE: re.Pattern = re.compile(
    r"<" + _DSML_PREFIX + r'invoke\s+name="([^"]+)"\s*>\s*(.*?)\s*</'
    + _DSML_PREFIX + r"invoke>",
    re.DOTALL,
)

# Matches <parameter name="key"> value </parameter> and captures:
#   group(1) → parameter name
#   group(2) → parameter value (trimmed)
_PARAM_RE: re.Pattern = re.compile(
    r"<" + _DSML_PREFIX + r'parameter\s+name="([^"]+)"[^>]*>\s*(.*?)\s*</'
    + _DSML_PREFIX + r"parameter>",
    re.DOTALL,
)

# Generic tag stripper — removes any remaining XML/DSML tags from the text
# after all known structures have been extracted.
_ANY_TAG_RE: re.Pattern = re.compile(r"<[^>]+>")


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class XmlToolCall:
    """
    A tool call parsed from XML / DSML content.

    Attributes:
        name:      Function name (e.g. ``"exec_command"``).
        arguments: Parameter key/value pairs as a plain dict.
                   All values are strings (as received from the XML).
    """

    name: str
    arguments: dict


# ── Public API ────────────────────────────────────────────────────────────────


def extract_xml_tool_calls(content: str) -> Tuple[list, str]:
    """
    Parse XML / DSML tool calls embedded in *content* and return clean text.

    The function handles three scenarios:
    1. **No XML** — returns an empty list and the original content unchanged.
    2. **Standard XML** — ``<tool_calls><invoke …><parameter …>``.
    3. **DSML** — ``<｜｜DSML｜｜tool_calls>``, etc.

    Args:
        content: Raw ``message.content`` string from the backend response.
                 May be empty or ``None``.

    Returns:
        A two-tuple ``(tool_calls, clean_text)`` where:
        - ``tool_calls`` is a (possibly empty) list of ``XmlToolCall`` objects.
        - ``clean_text`` is *content* with all XML/DSML markup stripped.

    Example::

        calls, text = extract_xml_tool_calls(
            '<tool_calls>'
            '  <invoke name="exec_command">'
            '    <parameter name="command">ls -la</parameter>'
            '  </invoke>'
            '</tool_calls>'
            'Here is the result.'
        )
        # calls → [XmlToolCall(name="exec_command", arguments={"command": "ls -la"})]
        # text  → "Here is the result."
    """
    if not content:
        return [], content

    tool_calls: list[XmlToolCall] = []

    # Step 1 — Extract all <invoke> blocks and parse their parameters.
    for invoke_match in _INVOKE_RE.finditer(content):
        fn_name = invoke_match.group(1)
        inner   = invoke_match.group(2)

        arguments = {
            m.group(1): m.group(2).strip()
            for m in _PARAM_RE.finditer(inner)
        }

        tool_calls.append(XmlToolCall(name=fn_name, arguments=arguments))

    # Step 2 — Strip all XML/DSML markup from the content to produce clean text.
    # Order matters: remove the wrapper first, then individual tags, then any
    # remaining stray tags so nothing leaks into the user-facing text.
    clean = _TOOL_CALLS_RE.sub("", content)
    clean = _INVOKE_RE.sub("", clean)
    clean = _PARAM_RE.sub("", clean)
    clean = _ANY_TAG_RE.sub("", clean).strip()

    return tool_calls, clean
