"""Model list management — provider-agnostic, with API fetch + local cache.

Adding a new provider only requires one entry in PROVIDER_MODEL_SOURCES.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

_CACHE_FILE = Path.home() / ".llm-relay" / "models_cache.json"
_CACHE_TTL  = 3600  # 1 hour


# ── Model source registry ─────────────────────────────────────────────────────


@dataclass
class ModelSource:
    """Describes where to get the model list for a provider.

    *static*  — the list never changes (hardcoded Anthropic IDs).
    *api*     — the list is fetched from a URL and cached locally.
    """
    kind:     str          # "static" | "api"
    ids:      list[str]    # static model IDs (for kind="static")
    url:      str          # fetch URL (for kind="api")

    @classmethod
    def static(cls, ids: list[str]) -> "ModelSource":
        return cls(kind="static", ids=ids, url="")

    @classmethod
    def api(cls, url: str) -> "ModelSource":
        return cls(kind="api", ids=[], url=url)


# Add a new provider here — everything else picks it up automatically.
PROVIDER_MODEL_SOURCES: dict[str, ModelSource] = {
    "deepseek":           ModelSource.static(["deepseek-v4-pro[1m]", "deepseek-v4-flash"]),
    "deepseek-anthropic": ModelSource.static(["deepseek-v4-pro[1m]", "deepseek-v4-flash"]),
    "opencode":           ModelSource.api("https://opencode.ai/zen/go/v1/models"),
}


# ── Public API ────────────────────────────────────────────────────────────────


def get_models_for_backend(backend: str) -> list[str]:
    """Return model IDs for *backend* (from cache, API, or static list)."""
    source = PROVIDER_MODEL_SOURCES.get(backend)
    if source is None:
        return []

    if source.kind == "static":
        return list(source.ids)

    # API source — try cache first.
    cached = _read_cache_key(backend)
    if cached and not _cache_expired(backend):
        return cached

    return _fetch_and_cache(backend, source.url)


def refresh_models(backend: str) -> list[str]:
    """Force-refresh the model list for *backend* from its API source."""
    source = PROVIDER_MODEL_SOURCES.get(backend)
    if source is None or source.kind != "api":
        return get_models_for_backend(backend)

    return _fetch_and_cache(backend, source.url, force=True)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _cache_expired(backend: str) -> bool:
    cache = _load_cache()
    ts = cache.get(f"{backend}_ts", 0)
    return (time.time() - ts) >= _CACHE_TTL


def _read_cache_key(backend: str) -> list[str]:
    return _load_cache().get(backend, [])


def _fetch_and_cache(backend: str, url: str, force: bool = False) -> list[str]:
    """Fetch model IDs from *url*, update cache, return them.

    Falls back to a cached copy on network errors; if no cache exists
    the *ids* field of the ModelSource is used as a last-resort fallback.
    """
    try:
        req = Request(url, method="GET")
        req.add_header("Accept", "application/json")
        data = json.loads(urlopen(req, timeout=10).read())
        ids = sorted(m["id"] for m in data.get("data", []))
    except Exception:
        cached = _read_cache_key(backend)
        if cached:
            return cached
        # Absolute last resort — use the hardcoded fallback if defined.
        source = PROVIDER_MODEL_SOURCES.get(backend)
        fallback = source.ids if source else []
        return fallback or _GLOBAL_FALLBACK

    _write_cache_key(backend, ids)
    return ids


_GLOBAL_FALLBACK = [
    "glm-5.1", "glm-5", "kimi-k2.6", "kimi-k2.5",
    "deepseek-v4-pro", "deepseek-v4-flash",
    "qwen3.6-plus", "qwen3.5-plus",
    "mimo-v2.5-pro", "mimo-v2.5",
    "minimax-m2.7", "minimax-m2.5",
]


# ── Cache persistence ─────────────────────────────────────────────────────────


def _load_cache() -> dict:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        return json.loads(_CACHE_FILE.read_text())
    except Exception:
        return {}


def _write_cache_key(backend: str, ids: list[str]) -> None:
    cache = _load_cache()
    cache[backend] = ids
    cache[f"{backend}_ts"] = time.time()
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(cache))
