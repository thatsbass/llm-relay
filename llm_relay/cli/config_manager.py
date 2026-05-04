"""
Local configuration manager.

Source of truth: ~/.llm-relay/config.json
Also generates ~/.llm-relay/.env for manual shell sourcing.

Design notes
------------
- Zero external dependencies — pure stdlib only.
- ``RelayConfig`` is a plain (mutable) dataclass so ``cmd_config`` can update
  a single field without rebuilding the whole object.
- All file I/O is isolated here; no other module touches the JSON file directly.
"""

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
}


# ── Config dataclass ──────────────────────────────────────────────────────────


@dataclass
class RelayConfig:
    """
    Runtime configuration for the llm-relay proxy.

    Stored as JSON at ``~/.llm-relay/config.json``.  Fields are mutable so
    ``cmd_config`` can update individual values in place before re-saving.

    Attributes:
        port:     Local port the proxy listens on.
        provider: Backend provider key (must be in ``PROVIDERS``).
        api_key:  Secret API key for the upstream backend.
    """

    port:     int
    provider: str
    api_key:  str

    # ── Derived helpers ───────────────────────────────────────────────────────

    @classmethod
    def default(cls) -> "RelayConfig":
        """Return a safe default config — API key is intentionally empty."""
        return cls(port=8080, provider="deepseek", api_key="")

    def base_url(self) -> str:
        """Full proxy URL, e.g. ``http://127.0.0.1:8080``."""
        return f"http://127.0.0.1:{self.port}"

    def env_key_name(self) -> str:
        """
        Environment variable name for the API key.

        Example: ``"DEEPSEEK_API_KEY"`` for the ``deepseek`` provider.
        """
        return PROVIDERS.get(self.provider, {}).get("env_key", "API_KEY")

    def provider_display(self) -> str:
        """Human-readable provider name, e.g. ``"DeepSeek"``."""
        return PROVIDERS.get(self.provider, {}).get(
            "display", self.provider.capitalize()
        )


# ── Public API ────────────────────────────────────────────────────────────────


def load() -> Optional[RelayConfig]:
    """
    Load the config from ``~/.llm-relay/config.json``.

    Returns ``None`` if the file is absent or malformed — callers should
    treat ``None`` as "not yet configured" and run the setup wizard.
    """
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return RelayConfig(
            port=int(data["port"]),
            provider=str(data["provider"]),
            api_key=str(data["api_key"]),
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
    """
    Write ``~/.llm-relay/.env`` for users who prefer to source env vars
    manually in their shell (``source ~/.llm-relay/.env``).

    This file is NOT auto-sourced — the proxy sets env vars in its own
    process space at startup via ``os.environ``.
    """
    env_key = config.env_key_name()
    lines = [
        "# llm-relay — source this file to export env vars in your shell:",
        "#   source ~/.llm-relay/.env",
        "",
        f'export {env_key}="{config.api_key}"',
        f'export OPENAI_BASE_URL="{config.base_url()}"',
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
