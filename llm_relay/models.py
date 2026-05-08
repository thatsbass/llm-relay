"""Model list management — cached fetch from OpenCode Go API."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

_CACHE_FILE  = Path.home() / ".llm-relay" / "opencode_models.json"
_CACHE_TTL   = 3600  # 1 hour
_FETCH_URL   = "https://opencode.ai/zen/go/v1/models"

# Anthropic model names the proxy maps (always accepted by Claude Desktop).
ANTHROPIC_MODEL_IDS = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

# Map Anthropic model names → default backend model IDs.
ANTHROPIC_TO_DEEPSEEK = {
    "claude-sonnet-4-6":  "deepseek-v4-pro",
    "claude-sonnet-4-5":  "deepseek-v4-pro",
    "claude-opus-4-7":    "deepseek-v4-pro",
    "claude-opus-4-6":    "deepseek-v4-pro",
    "claude-haiku-4-5":   "deepseek-v4-flash",
    "claude-sonnet-4":    "deepseek-v4-pro",
    "claude-opus-4":      "deepseek-v4-pro",
    "claude-haiku-3-5":   "deepseek-v4-flash",
}


def get_opencode_models(force_refresh: bool = False) -> list[str]:
    """Return available OpenCode Go model IDs, from cache or API."""
    if not force_refresh and _cache_valid():
        return _read_cache()

    try:
        req = Request(_FETCH_URL, method="GET")
        req.add_header("Accept", "application/json")
        data = json.loads(urlopen(req, timeout=10).read())
        ids = sorted(m["id"] for m in data.get("data", []))
        _write_cache(ids)
        return ids
    except Exception:
        # Return stale cache if available, else hardcoded fallback.
        cached = _read_cache()
        if cached:
            return cached
        return _FALLBACK_MODELS


def get_models_for_backend(backend: str) -> list[str]:
    """Return model IDs appropriate for the given backend."""
    if "opencode" in backend:
        return get_opencode_models()
    return ANTHROPIC_MODEL_IDS


def refresh_models() -> list[str]:
    """Force-refresh the OpenCode Go model cache."""
    return get_opencode_models(force_refresh=True)


# ── Internal ───────────────────────────────────────────────────────────────────


_FALLBACK_MODELS = [
    "glm-5.1", "glm-5", "kimi-k2.6", "kimi-k2.5",
    "deepseek-v4-pro", "deepseek-v4-flash",
    "qwen3.6-plus", "qwen3.5-plus",
    "mimo-v2.5-pro", "mimo-v2.5",
    "minimax-m2.7", "minimax-m2.5",
]


def _cache_valid() -> bool:
    if not _CACHE_FILE.exists():
        return False
    return (time.time() - _CACHE_FILE.stat().st_mtime) < _CACHE_TTL


def _read_cache() -> list[str]:
    try:
        return json.loads(_CACHE_FILE.read_text())
    except Exception:
        return []


def _write_cache(ids: list[str]) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(ids))
