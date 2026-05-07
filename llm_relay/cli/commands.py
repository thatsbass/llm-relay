"""CLI subcommand implementations (start, stop, status, setup, update, config)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from llm_relay.cli import config_manager
from llm_relay.cli import pid as _pid
from llm_relay.cli.config_manager import RelayConfig
from llm_relay.cli.codex_writer import update as _update_codex
from llm_relay.cli.wizard import run as _run_wizard

_REPO = "https://github.com/thatsbass/llm-relay.git"


# ── start ─────────────────────────────────────────────────────────────────────


def cmd_start(tls: bool = False, port: int | None = None) -> None:
    """Start the proxy, running setup first if not yet configured."""
    relay_cfg = config_manager.load()
    if not relay_cfg or not relay_cfg.api_key.strip():
        print("No configuration found — running setup first.\n")
        relay_cfg = _run_wizard()

    _run(relay_cfg, tls=tls, port=port)


def _run(relay_cfg: RelayConfig, tls: bool = False, port: int | None = None) -> None:
    """Wire relay config into the proxy stack and start serving."""
    # Inject the API key into the environment so Config.from_env() picks it up.
    os.environ[relay_cfg.env_key_name()] = relay_cfg.api_key

    # Inject fallback config if set.
    if relay_cfg.fallback_provider:
        os.environ["LLM_RELAY_FALLBACK_BACKEND"] = relay_cfg.fallback_provider
        fb_info = config_manager.PROVIDERS.get(relay_cfg.fallback_provider, {})
        fb_key = fb_info.get("env_key", "")
        if fb_key and relay_cfg.fallback_api_key:
            os.environ[fb_key] = relay_cfg.fallback_api_key

    if tls:
        os.environ["LLM_RELAY_TLS"] = "1"

    if port is not None:
        os.environ["LLM_RELAY_PORT"] = str(port)

    # Import here (not at module top) so ``cmd_stop`` / ``cmd_status`` never
    # pay the cost of importing the full server stack.
    from llm_relay.config import Config
    from llm_relay.server.app import create_server

    effective_port = port if port is not None else relay_cfg.port
    try:
        config = Config.from_env(port=effective_port)
    except RuntimeError as exc:
        _die(str(exc))

    try:
        server = create_server(config)
    except OSError as exc:
        _die(
            f"Cannot bind to port {relay_cfg.port}: {exc.strerror}.\n"
            f"  → Run:  llm-relay config port <other-port>"
        )

    # ── PID file + signal handler ─────────────────────────────────────────────

    _pid.write()

    def _on_sigterm(signum, frame):
        _pid.clear()
        server.shutdown()
        _info("Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    # ── Startup banner ────────────────────────────────────────────────────────

    print()
    scheme = "https" if tls else "http"
    _ok(f"Proxy running  →  {scheme}://127.0.0.1:{relay_cfg.port}")
    _ok(f"Backend        →  {relay_cfg.provider_display()}")
    if relay_cfg.fallback_provider:
        fb_name = config_manager.PROVIDERS.get(
            relay_cfg.fallback_provider, {}
        ).get("display", relay_cfg.fallback_provider)
        _ok(f"Fallback       →  {fb_name}")
    print()
    print("  Endpoints:")
    print(f"    {relay_cfg.base_url()}/responses      (Codex CLI)")
    print(f"    {relay_cfg.base_url()}/v1/responses   (Codex CLI)")
    print(f"    {relay_cfg.base_url()}/v1/messages    (Claude Code / Desktop)")
    print(f"    {relay_cfg.base_url()}/v1/models      (Auto-discovery)")
    print()
    print("  Press Ctrl+C to stop.\n")

    # ── Serve ─────────────────────────────────────────────────────────────────

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _pid.clear()
        server.shutdown()
        print()
        _info("Stopped.")


# ── stop ──────────────────────────────────────────────────────────────────────


def cmd_stop() -> None:
    """Send SIGTERM to the running proxy via the PID file."""
    if _pid.stop():
        _ok("Proxy stopped.")
    else:
        print("  Proxy is not running.")


# ── status ────────────────────────────────────────────────────────────────────


def cmd_status() -> None:
    """Print the running state and active configuration."""
    running = _pid.is_running()
    pid_val = _pid.read()
    cfg     = config_manager.load()

    print()

    if running:
        _ok(f"Status    : running  (PID {pid_val})")
    else:
        print("  Status    : stopped")

    if cfg:
        _ok(f"Provider  : {cfg.provider_display()}")
        _ok(f"Port      : {cfg.port}")
        _ok(f"URL       : {cfg.base_url()}")
        key_hint = f"…{cfg.api_key[-4:]}" if cfg.api_key else "(not set)"
        _ok(f"API key   : {key_hint}")
    else:
        print("  Config    : not configured — run:  llm-relay setup")

    print()


# ── setup ─────────────────────────────────────────────────────────────────────


def cmd_setup() -> None:
    """Re-run the interactive setup wizard."""
    _run_wizard()
    print("Setup complete.")
    if _pid.is_running():
        print("  Proxy is running — restart it to apply changes:")
        print("    llm-relay stop && llm-relay start")
    else:
        print("  Run:  llm-relay start")


# ── update ───────────────────────────────────────────────────────────────────


def cmd_update() -> None:
    """Upgrade llm-relay to the latest version from GitHub using venv pip."""
    pip = Path(sys.executable).parent / "pip"
    if not pip.exists():
        _die(
            "Cannot locate pip in the current environment.\n"
            "  Re-install from scratch:  "
            "curl -fsSL https://raw.githubusercontent.com/thatsbass/llm-relay/main/install.sh | bash"
        )

    was_running = _pid.is_running()
    if was_running:
        print("  Proxy is running — stopping it before the update...")
        _pid.stop()

    print()
    print("  Downloading latest llm-relay from GitHub…")

    result = subprocess.run(
        [str(pip), "install", "--upgrade", f"git+{_REPO}"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        _die(
            "Update failed. Check your internet connection and try again.\n"
            "  You can also re-run the one-line installer to do a clean install."
        )

    print()
    _ok("llm-relay updated to the latest version.")

    if was_running:
        print()
        print("  Proxy was stopped. Start it again:")
        print("    llm-relay start")
    else:
        print()
        print("  Run  llm-relay start  to launch the proxy.")

    print()


# ── config ────────────────────────────────────────────────────────────────────


def cmd_config(subkey: str, value: str) -> None:
    """Update a single config value (port or key) without re-running setup."""
    cfg = config_manager.load()
    if cfg is None:
        _die("Not configured yet. Run:  llm-relay setup")

    if subkey == "port":
        if not value.isdigit() or not (1 <= int(value) <= 65535):
            _die("Invalid port number — must be an integer between 1 and 65535.")
        cfg.port = int(value)
        _ok(f"Port updated to {cfg.port}.")

    elif subkey == "key":
        stripped = value.strip()
        if not stripped:
            _die("API key cannot be empty.")
        cfg.api_key = stripped
        _ok("API key updated.")

    else:
        _die(f"Unknown config key {subkey!r}. Supported: port, key")

    config_manager.save(cfg)
    _update_codex(cfg)
    _ok("Config saved.")

    if _pid.is_running():
        print()
        print("  Proxy is running — restart it for changes to take effect:")
        print("    llm-relay stop && llm-relay start")


# ── Print helpers ─────────────────────────────────────────────────────────────


def _ok(msg: str)   -> None: print(f"  \033[32m✓\033[0m {msg}")
def _info(msg: str) -> None: print(f"  {msg}")


def _die(msg: str) -> None:
    """Print an error message and exit with code 1."""
    print(f"  \033[31m✗\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


# ── trust-ca ──────────────────────────────────────────────────────────────────


def cmd_trust_ca() -> None:
    """Install the local CA certificate in the system trust store."""
    from llm_relay.server.tls import install_ca_trust
    print()
    install_ca_trust()
    print()
