"""Interactive setup wizard — prompts for port, provider, and API key."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from llm_relay.cli import config_manager
from llm_relay.cli import codex_writer
from llm_relay.cli import claude_writer
from llm_relay.cli.config_manager import PROVIDERS, RelayConfig


# ── Public API ────────────────────────────────────────────────────────────────


def run() -> RelayConfig:
    """Run the interactive setup wizard and return the saved RelayConfig."""
    _header()

    existing = config_manager.load() or RelayConfig.default()

    try:
        port      = _ask_port(existing.port)
        provider  = _ask_provider(existing.provider)
        api_key   = _ask_api_key(existing.api_key, provider)
        fb_prov   = _ask_fallback(existing.fallback_provider or "")
        fb_key    = ""
        if fb_prov:
            fb_key = _ask_api_key(existing.fallback_api_key or "", fb_prov)
    except (KeyboardInterrupt, EOFError):
        print("\n\nSetup cancelled.")
        sys.exit(1)

    config = RelayConfig(
        port=port,
        provider=provider,
        api_key=api_key,
        fallback_provider=fb_prov,
        fallback_api_key=fb_key,
    )

    _save(config)
    return config


# ── Prompt helpers ────────────────────────────────────────────────────────────


def _ask_port(default: int) -> int:
    """Ask for the proxy port; repeat until valid."""
    while True:
        raw = input(f"  Port [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= 65535:
            return int(raw)
        _err("Invalid port — enter a number between 1 and 65535.")


def _ask_provider(default: str) -> str:
    """Ask for the backend provider; repeat until a known key is entered."""
    choices = "/".join(PROVIDERS)
    while True:
        raw = input(f"  Provider ({choices}) [{default}]: ").strip().lower()
        if not raw:
            return default
        if raw in PROVIDERS:
            return raw
        _err(f"Unknown provider. Choose from: {choices}")


def _ask_api_key(current: str, provider: str) -> str:
    """Ask for the API key with hidden input; keeps the existing key on empty Enter."""
    env_key = PROVIDERS[provider]["env_key"]
    hint    = f" [current ends in …{current[-4:]}]" if current else ""

    while True:
        raw = getpass.getpass(f"  {env_key}{hint}: ").strip()
        if not raw and current:
            return current
        if raw:
            return raw
        _err("API key cannot be empty.")


def _ask_fallback(current: str) -> str:
    """Ask for an optional fallback provider."""
    choices = "/".join(PROVIDERS)
    none_label = "none"
    while True:
        raw = input(
            f"  Fallback provider ({choices}/{none_label}) [{current or none_label}]: "
        ).strip().lower()
        if not raw:
            return current
        if raw == none_label:
            return ""
        if raw in PROVIDERS:
            return raw
        _err(f"Unknown provider. Choose from: {choices}/{none_label}")


# ── Save & confirm ────────────────────────────────────────────────────────────


def _save(config: RelayConfig) -> None:
    """Persist config and update ~/.codex/config.toml, then print a summary."""
    print()

    config_manager.save(config)
    _ok("Config saved         → ~/.llm-relay/config.json")

    codex_writer.update(config)
    _ok("Codex config updated → ~/.codex/config.toml")

    _ok(".env written         → ~/.llm-relay/.env")

    profile = _patch_shell_profile()
    if profile:
        _ok(f"API key auto-export  → {profile}")
    else:
        print()
        print("  To export the API key in your shell, add this line to your shell config:")
        print("    source ~/.llm-relay/.env")

    reload_cmd = f"source {profile}" if profile else "open a new terminal"
    print()
    print("  \033[1mNext steps:\033[0m")
    print(f"    1. Reload your shell:  {reload_cmd}")
    print("    2. Start the proxy:    llm-relay start --tls --port 8443")
    print("    3. For Codex CLI:      codex")
    print()
    tls = os.environ.get("LLM_RELAY_TLS", "").lower() in ("1", "true", "yes")
    claude_writer.write_all(config.base_url(), config.port, tls=tls)


# ── Shell profile helpers ─────────────────────────────────────────────────────

_SOURCE_LINE = 'source "$HOME/.llm-relay/.env"'
_SOURCE_MARKER = ".llm-relay/.env"


def _detect_profile() -> str:
    """Return the most appropriate shell profile path for the current user."""
    shell = os.path.basename(os.environ.get("SHELL", ""))
    home = Path.home()

    if shell == "zsh":
        for name in (".zshrc", ".zprofile"):
            if (home / name).exists():
                return str(home / name)
        return str(home / ".zshrc")

    if shell == "bash":
        for name in (".bashrc", ".bash_profile", ".profile"):
            if (home / name).exists():
                return str(home / name)
        return str(home / ".bashrc")

    if (home / ".profile").exists():
        return str(home / ".profile")
    return ""


def _patch_shell_profile() -> str:
    """Append the .env source line to the shell profile if not already present."""
    profile = _detect_profile()
    if not profile:
        return ""

    try:
        existing = Path(profile).read_text(encoding="utf-8") if Path(profile).exists() else ""
    except OSError:
        return ""

    if _SOURCE_MARKER in existing:
        return profile  # already patched — nothing to do

    try:
        with open(profile, "a", encoding="utf-8") as f:
            f.write(f"\n# Added by llm-relay setup\n{_SOURCE_LINE}\n")
        return profile
    except OSError:
        return ""


# ── Print helpers ─────────────────────────────────────────────────────────────


def _header() -> None:
    print()
    print("╔══════════════════════════════╗")
    print("║      llm-relay  setup        ║")
    print("╚══════════════════════════════╝")
    print()
    print("Press Enter to accept the value shown in [brackets].")
    print()


def _ok(msg: str)  -> None: print(f"  \033[32m✓\033[0m {msg}")
def _err(msg: str) -> None: print(f"  \033[31m✗\033[0m {msg}")
