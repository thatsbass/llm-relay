"""Manages Claude Desktop 3P config and Claude Code CLI environment.

Writes the actual config files so users don't have to copy-paste
anything — the proxy handles the setup end-to-end.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────

CLAUDE_3P_DIR  = Path.home() / "Library" / "Application Support" / "Claude-3p"
CONFIG_LIBRARY = CLAUDE_3P_DIR / "configLibrary"
CLAUDE_CODE_ENV = Path.home() / ".llm-relay" / "claude-code.env"


# ── Public API ────────────────────────────────────────────────────────────────


def write_all(base_url: str, port: int, tls: bool = True) -> None:
    """Write Claude Desktop 3P config and Claude Code env file.

    Defaults to HTTPS because Claude Desktop 3P requires it.
    """
    scheme = "https" if tls else "http"
    url = f"{scheme}://127.0.0.1:{port}"

    _write_3p_config(url)
    _write_claude_code_env(url)


def _write_3p_config(gateway_url: str) -> None:
    """Create or update the Claude Desktop 3P gateway configuration."""
    CONFIG_LIBRARY.mkdir(parents=True, exist_ok=True)

    config_id = _ensure_config_id()

    config_path = CONFIG_LIBRARY / f"{config_id}.json"
    config_path.write_text(json.dumps({
        "inferenceProvider": "gateway",
        "inferenceGatewayBaseUrl": gateway_url,
        "inferenceGatewayApiKey": "llm-relay",
        "inferenceGatewayAuthScheme": "bearer",
        "disableDeploymentModeChooser": False,
        "inferenceModels": [
            {"name": "deepseek-v4-pro", "supports1m": True},
            {"name": "deepseek-v4-flash"},
        ],
    }, indent=2), encoding="utf-8")

    meta_path = CONFIG_LIBRARY / "_meta.json"
    meta_path.write_text(json.dumps({
        "appliedId": config_id,
        "entries": [{"id": config_id, "name": "llm-relay"}],
    }, indent=2), encoding="utf-8")

    print(f"  \033[32m✓\033[0m Claude Desktop 3P config written → {config_path}")
    print(f"    Gateway URL : {gateway_url}")
    print(f"    Models      : deepseek-v4-pro, deepseek-v4-flash")
    print(f"    Auto-chooser: enabled (you can switch between 3P and Anthropic)")


def _write_claude_code_env(gateway_url: str) -> None:
    """Write the Claude Code environment file with all required vars."""
    CLAUDE_CODE_ENV.parent.mkdir(parents=True, exist_ok=True)

    CLAUDE_CODE_ENV.write_text(f"""# llm-relay — Claude Code environment
# Source this in your shell profile:
#   source ~/.llm-relay/claude-code.env

export ANTHROPIC_BASE_URL="{gateway_url}"
export ANTHROPIC_AUTH_TOKEN="llm-relay"
export ANTHROPIC_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
export CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"
export CLAUDE_CODE_EFFORT_LEVEL="max"
""", encoding="utf-8")

    print(f"  \033[32m✓\033[0m Claude Code env written → {CLAUDE_CODE_ENV}")

    # Try to source it in the shell profile.
    profile = _patch_shell_profile()
    if profile:
        print(f"  \033[32m✓\033[0m Auto-sourced in → {profile}")
    else:
        print(f"  \033[33m⚠\033[0m  Add this line to your shell config manually:")
        print(f'    source "$HOME/.llm-relay/claude-code.env"')


# ── Internal helpers ──────────────────────────────────────────────────────────


def _ensure_config_id() -> str:
    """Return the existing 3P config ID or generate a new one."""
    meta_path = CONFIG_LIBRARY / "_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            return meta.get("appliedId", str(uuid.uuid4()))
        except (json.JSONDecodeError, KeyError):
            pass
    return str(uuid.uuid4())


def _patch_shell_profile() -> str:
    """Add the Claude Code env source to the shell profile. Returns the profile path."""
    source_line = 'source "$HOME/.llm-relay/claude-code.env"'
    marker = ".llm-relay/claude-code.env"

    shell = os.path.basename(os.environ.get("SHELL", ""))
    home = Path.home()

    if shell == "zsh":
        for name in (".zshrc", ".zprofile"):
            if (home / name).exists():
                profile = str(home / name)
                break
        else:
            profile = str(home / ".zshrc")
    elif shell == "bash":
        for name in (".bashrc", ".bash_profile", ".profile"):
            if (home / name).exists():
                profile = str(home / name)
                break
        else:
            profile = str(home / ".bashrc")
    elif (home / ".profile").exists():
        profile = str(home / ".profile")
    else:
        return ""

    try:
        existing = Path(profile).read_text(encoding="utf-8") if Path(profile).exists() else ""
    except OSError:
        return ""

    if marker in existing:
        return profile  # already patched

    try:
        with open(profile, "a", encoding="utf-8") as f:
            f.write(f"\n# Added by llm-relay\n{source_line}\n")
        return profile
    except OSError:
        return ""
