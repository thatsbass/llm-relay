"""Reads and writes ~/.llm-relay/config.json and ~/.llm-relay/.env."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


# ── Filesystem layout ─────────────────────────────────────────────────────────
#
# Everything the CLI owns lives under ~/.llm-relay/ so uninstalling is trivial:
# ``rm -rf ~/.llm-relay`` removes all state cleanly.

RELAY_DIR   = Path.home() / ".llm-relay"
CONFIG_FILE = RELAY_DIR / "config.json"
ENV_FILE    = RELAY_DIR / ".env"


# ── Provider registry ─────────────────────────────────────────────────────────
#
# Add a new provider here — no other file needs to change for the provider
# selection to appear in the wizard and the status command.

PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "display": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "deepseek-anthropic": {
        "display": "DeepSeek (Anthropic API)",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "opencode": {
        "display": "OpenCode Go",
        "env_key": "OPENCODE_API_KEY",
    },
}


# ── Config dataclass ──────────────────────────────────────────────────────────


@dataclass
class RelayConfig:
    """Mutable proxy config stored at ~/.llm-relay/config.json."""

    port:     int
    provider: str
    api_key:  str
    fallback_provider: str = ""
    fallback_api_key:  str = ""

    # ── Derived helpers ───────────────────────────────────────────────────────

    @classmethod
    def default(cls) -> "RelayConfig":
        """Return a safe default config — API key is intentionally empty."""
        return cls(port=8080, provider="deepseek", api_key="")

    def base_url(self) -> str:
        """Full proxy URL, e.g. ``http://127.0.0.1:8080``."""
        return f"http://127.0.0.1:{self.port}"

    def env_key_name(self) -> str:
        """Environment variable name for the API key, e.g. DEEPSEEK_API_KEY."""
        return PROVIDERS.get(self.provider, {}).get("env_key", "API_KEY")

    def provider_display(self) -> str:
        """Human-readable provider name, e.g. ``"DeepSeek"``."""
        return PROVIDERS.get(self.provider, {}).get(
            "display", self.provider.capitalize()
        )


# ── Public API ────────────────────────────────────────────────────────────────


def load() -> Optional[RelayConfig]:
    """Load config from ~/.llm-relay/config.json, or None if absent or malformed."""
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return RelayConfig(
            port=int(data["port"]),
            provider=str(data["provider"]),
            api_key=str(data["api_key"]),
            fallback_provider=str(data.get("fallback_provider", "")),
            fallback_api_key=str(data.get("fallback_api_key", "")),
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def save(config: RelayConfig) -> None:
    """
    Persist *config* to disk and regenerate ``~/.llm-relay/.env``.

    Creates ``~/.llm-relay/`` if it does not already exist.
    """
    RELAY_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(asdict(config), indent=2),
        encoding="utf-8",
    )
    _write_env(config)


def is_configured() -> bool:
    """Return ``True`` iff a valid config with a non-empty API key exists."""
    cfg = load()
    return cfg is not None and bool(cfg.api_key.strip())


# ── Internal helpers ──────────────────────────────────────────────────────────


def _write_env(config: RelayConfig) -> None:
    """Write ~/.llm-relay/.env with export statements for the API key and base URL."""
    env_key = config.env_key_name()
    lines = [
        "# llm-relay — source this file to export env vars in your shell:",
        "#   source ~/.llm-relay/.env",
        "",
        f'export {env_key}="{config.api_key}"',
    ]
    if config.fallback_provider:
        fb_info = PROVIDERS.get(config.fallback_provider, {})
        fb_key = fb_info.get("env_key", "FALLBACK_API_KEY")
        lines.append(f'export {fb_key}="{config.fallback_api_key}"')
        lines.append(f'export LLM_RELAY_FALLBACK_BACKEND="{config.fallback_provider}"')
    lines.append(f'export OPENAI_BASE_URL="{config.base_url()}"')
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
