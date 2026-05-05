"""Segment-based TOML merger for ~/.codex/config.toml — preserves user content."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from llm_relay.cli.config_manager import RelayConfig

# ── Target path ───────────────────────────────────────────────────────────────

CODEX_CONFIG = Path.home() / ".codex" / "config.toml"

# The model name Codex CLI uses when routing requests to our proxy.
# This is a Codex-internal alias, NOT the actual upstream model name
# (DeepSeek uses "deepseek-chat" internally; Codex just needs any string here).
_CODEX_MODEL = "gpt-5.5"


# ── Public API ────────────────────────────────────────────────────────────────


def update(config: RelayConfig) -> None:
    """Merge llm-relay settings into ~/.codex/config.toml, preserving all other content."""
    existing = (
        CODEX_CONFIG.read_text(encoding="utf-8")
        if CODEX_CONFIG.exists()
        else ""
    )
    merged = _merge(existing, config)
    CODEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CODEX_CONFIG.write_text(merged, encoding="utf-8")


# ── Core merge logic ──────────────────────────────────────────────────────────


def _merge(content: str, config: RelayConfig) -> str:
    """Pure function: merge relay config into a TOML string and return the result."""
    segs = _split(content)

    # ── Top-level keys ────────────────────────────────────────────────────────
    top = segs.get(None, "")
    top = _upsert(top, "model",          f'"{_CODEX_MODEL}"')
    top = _upsert(top, "model_provider", f'"{config.provider}"')
    segs[None] = top

    # ── [model_providers.<provider>] ──────────────────────────────────────────
    prov_key = f"model_providers.{config.provider}"
    prov     = segs.get(prov_key, f"[{prov_key}]\n")
    prov = _upsert(prov, "name",            f'"{config.provider_display()}"')
    prov = _upsert(prov, "context_window",  "64000")
    prov = _upsert(prov, "supports_images", "true")
    prov = _upsert(prov, "supports_tools",  "true")
    prov = _upsert(prov, "base_url",        f'"{config.base_url()}"')
    prov = _upsert(prov, "env_key",         f'"{config.env_key_name()}"')
    prov = _upsert(prov, "wire_api",        '"responses"')
    segs[prov_key] = prov

    # ── [tui.model_availability_nux] ──────────────────────────────────────────
    nux_key = "tui.model_availability_nux"
    nux     = segs.get(nux_key, f"[{nux_key}]\n")
    nux = _upsert(nux, f'"{_CODEX_MODEL}"', "4")
    segs[nux_key] = nux

    return _reassemble(segs)


# ── Segment splitter / assembler ──────────────────────────────────────────────

# Matches a TOML section header such as  [model_providers.deepseek]
# Does NOT match array-of-tables headers like  [[servers]].
_SECTION_RE = re.compile(r"^\[([^\[\]]+)\]$")


def _split(content: str) -> dict:
    """Split TOML into an ordered dict: None → top-level block, str → section name."""
    segments: dict       = {}
    current_key: Optional[str] = None
    current_lines: list[str]   = []

    for line in content.splitlines(keepends=True):
        m = _SECTION_RE.match(line.strip())
        if m:
            # Flush the current buffer before starting a new segment.
            segments[current_key] = "".join(current_lines)
            current_key   = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush the last buffer.
    segments[current_key] = "".join(current_lines)
    return segments


def _reassemble(segments: dict) -> str:
    """Reassemble ordered segments back into a valid TOML string."""
    parts: list[str] = []

    # Top-level block.
    top = segments.pop(None, "").rstrip("\n")
    if top:
        parts.append(top)

    # Section blocks.
    for block in segments.values():
        block = block.rstrip("\n")
        if block:
            parts.append("\n" + block)

    return "\n".join(parts) + "\n" if parts else ""


# ── Key upsert ────────────────────────────────────────────────────────────────

# Matches a TOML key-value line, capturing:
#   group 1 → leading whitespace
#   group 2 → key (word chars, dots, or quoted)
#   group 3 → `` = `` with surrounding spaces
#   group 4 → value
#   group 5 → trailing whitespace / comment
_KV_RE = re.compile(r'^(\s*)([\w".]+)(\s*=\s*)(.+?)(\s*(?:#.*)?)$')


def _upsert(block: str, key: str, value: str) -> str:
    """Update *key* = *value* in *block*, or append it if absent."""
    lines         = block.splitlines(keepends=True)
    key_pattern   = re.compile(rf"^\s*{re.escape(key)}\s*=")

    for i, line in enumerate(lines):
        if key_pattern.match(line):
            m = _KV_RE.match(line.rstrip("\n"))
            if m:
                indent, _, eq, _, comment = m.groups()
                lines[i] = f"{indent}{key}{eq}{value}{comment}\n"
            else:
                lines[i] = f"{key} = {value}\n"
            return "".join(lines)

    # Key not found in this block — append before the content ends.
    lines.append(f"{key} = {value}\n")
    return "".join(lines)
