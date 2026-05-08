"""CLI subcommand implementations (start, stop, status, setup, update, config, backend, claude, logs)."""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from llm_relay.cli import config_manager
from llm_relay.cli import pid as _pid
from llm_relay.cli.config_manager import PROVIDERS, RelayConfig
from llm_relay.cli.codex_writer import update as _update_codex
from llm_relay.cli.wizard import run as _run_wizard

_REPO   = "https://github.com/thatsbass/llm-relay.git"
_LOG_FILE  = Path.home() / ".llm-relay" / "proxy.log"
_CLAUDE_ENV = Path.home() / ".llm-relay" / "claude-code.env"
_CLAUDE_BIN = Path.home() / ".llm-relay" / "bin" / "claude"
_CODEX_BIN  = Path.home() / ".llm-relay" / "bin" / "codex"


# ── start ─────────────────────────────────────────────────────────────────────


def cmd_start(tls: bool = False, port: int | None = None, daemon: bool = False, force: bool = False) -> None:
    """Start the proxy, running setup first if not yet configured."""
    relay_cfg = config_manager.load()
    if not relay_cfg or not relay_cfg.api_key.strip():
        print("No configuration found — running setup first.\n")
        relay_cfg = _run_wizard()

    # ── Single-instance check ─────────────────────────────────────────
    if _pid.is_running():
        if force:
            _pid.stop()
            _ok("Killed old proxy process")
        else:
            _die(
                f"Proxy is already running (PID {_pid.read()}).\n"
                f"  Use llm-relay stop or llm-relay start --force"
            )

    # ── Pick the effective port ───────────────────────────────────────
    # Explicit --port: must match exactly, no fallback.
    # Otherwise (config default): auto-fall back to a free port if needed.
    preferred = port if port is not None else relay_cfg.port
    effective_port = _find_free_port(preferred)
    if effective_port != preferred:
        if port is not None:
            _die(
                f"Port {preferred} is already in use.\n"
                f"  Find it:  lsof -ti:{preferred}\n"
                f"  Kill it:  llm-relay start --force"
            )
        _info(f"\033[33m⚠\033[0m  Port {preferred} occupé → utilise {effective_port}")

    # Rewrite all downstream env files so the claude/codex wrappers source the
    # correct URL on their next invocation — no manual `source` needed.
    _sync_env_files(relay_cfg, effective_port, tls=tls)

    # Truncate the log so historical "Cannot bind" lines don't pollute this run.
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LOG_FILE.write_text("", encoding="utf-8")

    if daemon:
        _start_daemon(relay_cfg, tls=tls, effective_port=effective_port)
    else:
        _run(relay_cfg, tls=tls, effective_port=effective_port)


def _start_daemon(relay_cfg: RelayConfig, tls: bool = False, effective_port: int = 0) -> None:
    """Spawn a fresh server subprocess and return immediately.

    Uses subprocess.Popen + start_new_session instead of os.fork() to avoid
    macOS fork-safety issues with OpenSSL (SIGABRT on first urlopen call).
    """
    import subprocess

    _ok(f"Using port {effective_port}")

    if tls:
        from llm_relay.server.tls import ensure_certificate as _ensure_tls
        _ensure_tls()

    env = os.environ.copy()
    env[relay_cfg.env_key_name()] = relay_cfg.api_key
    env["LLM_RELAY_BACKEND"] = relay_cfg.provider
    env["LLM_RELAY_PORT"]    = str(effective_port)
    if tls:
        env["LLM_RELAY_TLS"] = "1"

    # Pipe for readiness signalling: child writes b"ok" when the socket is bound.
    r_fd, w_fd = os.pipe()
    env["LLM_RELAY_READY_FD"] = str(w_fd)

    log_fd = open(str(_LOG_FILE), "a", buffering=1)

    proc = subprocess.Popen(
        [sys.executable, "-m", "llm_relay", "_serve"],
        env=env,
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,  # detach from parent's terminal/process group
        pass_fds=(w_fd,),        # child inherits the write end of the pipe
    )
    log_fd.close()
    os.close(w_fd)  # parent doesn't write to the pipe

    # Wait for the child to signal readiness (or failure / EOF).
    msg = b""
    while True:
        ready, _, _ = select.select([r_fd], [], [], 30)
        if ready:
            chunk = os.read(r_fd, 4096)
            if not chunk:   # EOF — child crashed before writing
                break
            msg += chunk
            if b"ok" in msg or b"Cannot" in msg:
                break
        else:
            break           # 30-second timeout
    os.close(r_fd)

    if msg == b"ok":
        _pid.write(proc.pid, port=effective_port)
        scheme = "https" if tls else "http"
        _ok(f"Proxy started (daemon) → PID {proc.pid}")
        _ok(f"Listening on {scheme}://127.0.0.1:{effective_port}")
        _ok(f"Backend: {relay_cfg.provider_display()}")
        _ok(f"Logs: llm-relay logs -f")
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _pid.clear()
        error_tail = msg.decode(errors="replace")[:200] if msg else ""
        _die(
            f"Proxy failed to start.\n"
            f"  Logs: llm-relay logs\n"
            f"{'  ' + error_tail if error_tail else ''}"
        )


def _run(relay_cfg: RelayConfig, tls: bool = False, effective_port: int = 0, is_daemon: bool = False, _server=None) -> None:
    """Wire relay config into the proxy stack and start serving on *effective_port*."""
    # Inject the API key + backend so Config.from_env() resolves the right provider.
    os.environ[relay_cfg.env_key_name()] = relay_cfg.api_key
    os.environ["LLM_RELAY_BACKEND"] = relay_cfg.provider

    # Inject fallback config if set.
    if relay_cfg.fallback_provider:
        os.environ["LLM_RELAY_FALLBACK_BACKEND"] = relay_cfg.fallback_provider
        fb_info = config_manager.PROVIDERS.get(relay_cfg.fallback_provider, {})
        fb_key = fb_info.get("env_key", "")
        if fb_key and relay_cfg.fallback_api_key:
            os.environ[fb_key] = relay_cfg.fallback_api_key

    if tls:
        os.environ["LLM_RELAY_TLS"] = "1"

    os.environ["LLM_RELAY_PORT"] = str(effective_port)

    # Import here (not at module top) so ``cmd_stop`` / ``cmd_status`` never
    # pay the cost of importing the full server stack.
    from llm_relay.config import Config
    from llm_relay.server.app import create_server

    try:
        config = Config.from_env(port=effective_port)
    except RuntimeError as exc:
        _die(str(exc))

    if _server is not None:
        server = _server
    else:
        try:
            server = create_server(config)
        except OSError as exc:
            _die(
                f"Cannot bind to port {effective_port}: {exc.strerror}.\n"
                f"  → Run:  llm-relay config port <other-port>"
            )

    # ── PID file + signal handler ─────────────────────────────────────────────

    _pid.write(port=effective_port)

    def _on_sigterm(signum, frame):
        _pid.clear()
        server.shutdown()
        _info("Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    # ── Startup banner ────────────────────────────────────────────────────────

    if not is_daemon:
        print()
        scheme = "https" if tls else "http"
        _ok(f"Proxy running  →  {scheme}://127.0.0.1:{effective_port}")
        _ok(f"Backend        →  {relay_cfg.provider_display()}")
        if relay_cfg.fallback_provider:
            fb_name = PROVIDERS.get(
                relay_cfg.fallback_provider, {}
            ).get("display", relay_cfg.fallback_provider)
            _ok(f"Fallback       →  {fb_name}")
        print()
        print("  Endpoints:")
        base = f"{scheme}://127.0.0.1:{effective_port}"
        print(f"    {base}/responses      (Codex CLI)")
        print(f"    {base}/v1/responses   (Codex CLI)")
        print(f"    {base}/v1/messages    (Claude Code / Desktop)")
        print(f"    {base}/v1/models      (Auto-discovery)")
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
    running  = _pid.is_running()
    pid_val  = _pid.read()
    eff_port = _pid.read_port()
    cfg      = config_manager.load()

    # Stale state: PID alive but nothing listens on the bound port.
    stale = running and eff_port is not None and not _port_in_use(eff_port)

    # Read active model + configured URL from claude-code.env.
    env_model: str | None = None
    env_url:   str | None = None
    if _CLAUDE_ENV.exists():
        for line in _CLAUDE_ENV.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("export ANTHROPIC_MODEL="):
                env_model = s.split("=", 1)[1].strip("\"'")
            elif s.startswith("export ANTHROPIC_BASE_URL="):
                env_url = s.split("=", 1)[1].strip("\"'")

    print()

    if stale:
        print(f"  \033[33m⚠\033[0m  Stale state: PID {pid_val} alive but port {eff_port} not bound.")
        print("     Run:  llm-relay stop")
    elif running:
        _ok(f"Status    : running  (PID {pid_val})")
    else:
        print("  Status    : stopped")

    if cfg:
        # Show the effective bound port when running, the configured pref otherwise.
        display_port = eff_port if (running and eff_port and not stale) else cfg.port
        proxy_url    = f"http://127.0.0.1:{display_port}"
        _ok(f"Provider  : {cfg.provider_display()}")
        if eff_port and eff_port != cfg.port:
            _ok(f"Port      : {display_port}  (config: {cfg.port})")
        else:
            _ok(f"Port      : {display_port}")
        _ok(f"URL       : {proxy_url}")
        if env_model:
            _ok(f"Model     : {env_model}")
        key_hint = f"…{cfg.api_key[-4:]}" if cfg.api_key else "(not set)"
        _ok(f"API key   : {key_hint}")

        # Warn when claude-code.env still points to the wrong URL (e.g. https
        # vs http, or wrong port from a previous run).
        if env_url and running and not stale and env_url != proxy_url:
            print()
            print(f"  \033[33m⚠\033[0m  claude-code.env → {env_url}")
            print(f"     Proxy is on     → {proxy_url}")
            print("     Restart to resync:  llm-relay stop && llm-relay start")
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
    _sync_env_files(cfg, cfg.port)  # rewrite codex + claude-code.env + .env
    _ok("Config saved.")

    if _pid.is_running():
        print()
        print("  Proxy is running — restart it for changes to take effect:")
        print("    llm-relay stop && llm-relay start")


# ── Daemon helpers ──────────────────────────────────────────────────────────


def _port_in_use(port: int) -> bool:
    """Return True if *port* is already bound by any process."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        return False
    except OSError:
        return True


def _find_free_port(preferred: int) -> int:
    """Return *preferred* if it's free, else an OS-picked free port."""
    if not _port_in_use(preferred):
        return preferred
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sync_env_files(cfg: RelayConfig, effective_port: int, tls: bool = False) -> None:
    """Rewrite all downstream env files (codex, claude-code.env, .env) using
    *effective_port* + *tls* — so wrappers auto-source URLs that match the
    actually-running proxy on next exec.

    cfg.port (the user's preference) is preserved on disk; only the runtime
    artifacts pick up the effective port + scheme.
    """
    from dataclasses import replace
    from llm_relay.cli import config_manager as _cm

    eff_cfg = replace(cfg, port=effective_port)
    _update_codex(eff_cfg)         # ~/.codex/config.toml
    _cm._write_env(eff_cfg)        # ~/.llm-relay/.env (codex wrapper sources this)
    _write_claude_env(cfg.provider, port=effective_port, tls=tls)


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


# ── backend ────────────────────────────────────────────────────────────────────


def cmd_backend(name: str | None = None) -> None:
    """Switch the active backend provider or list available ones."""
    if name is None or name == "list":
        print()
        cfg = config_manager.load()
        current = cfg.provider if cfg else "—"
        for key, info in PROVIDERS.items():
            marker = "  * " if key == current else "    "
            print(f"    {marker}{key:<22} {info['display']}")
        print()
        print("  Switch:  llm-relay config backend <name>")
        print()
        return

    if name not in PROVIDERS:
        choices = ", ".join(PROVIDERS)
        _die(f"Unknown backend {name!r}. Available: {choices}")

    cfg = config_manager.load()
    if cfg is None:
        _die("Not configured yet. Run: llm-relay setup")

    cfg.provider = name
    config_manager.save(cfg)
    _update_codex(cfg)
    _ok(f"Backend switched to {PROVIDERS[name]['display']}")

    # Update Claude Code env.
    _write_claude_env(name)

    # Update Claude Desktop 3P config.
    from llm_relay.cli import claude_writer
    claude_writer.write_all(cfg.base_url(), cfg.port, provider=name)

    if _pid.is_running():
        print()
        print("  Proxy is running — restart to apply:")
        print("    llm-relay stop && llm-relay start --daemon")


# ── claude ─────────────────────────────────────────────────────────────────────


def cmd_claude(mode: str) -> None:
    """Configure Claude Code CLI to use the proxy or Anthropic directly."""
    if mode not in ("proxy", "direct"):
        _die("Usage: llm-relay claude <proxy|direct>")

    _CLAUDE_ENV.parent.mkdir(parents=True, exist_ok=True)

    if mode == "proxy":
        _write_claude_env(config_manager.load().provider if config_manager.load() else "deepseek")
    else:
        _CLAUDE_ENV.write_text("""# llm-relay — Claude Code (Anthropic direct, OAuth)
export ANTHROPIC_BASE_URL="https://api.anthropic.com"
# Let Claude Code handle auth via its own OAuth (/login).
unset ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_MODEL
unset ANTHROPIC_DEFAULT_OPUS_MODEL
unset ANTHROPIC_DEFAULT_SONNET_MODEL
unset ANTHROPIC_DEFAULT_HAIKU_MODEL
unset CLAUDE_CODE_SUBAGENT_MODEL
unset CLAUDE_CODE_EFFORT_LEVEL
""", encoding="utf-8")

    # Write a wrapper so "claude" always sources the env first.
    _CLAUDE_BIN.parent.mkdir(parents=True, exist_ok=True)
    _CLAUDE_BIN.write_text("""#!/bin/bash
# llm-relay — Claude Code wrapper (auto-sources env)
source "$HOME/.llm-relay/claude-code.env"

# Find the real claude binary, skipping this wrapper.
real=""
for p in $(echo "$PATH" | tr ':' '\\n'); do
    [ "$p" = "$HOME/.llm-relay/bin" ] && continue
    if [ -x "$p/claude" ]; then real="$p/claude"; break; fi
done
exec "${real:-claude}" "$@"
""")
    _CLAUDE_BIN.chmod(0o755)

    # Ensure ~/.llm-relay/bin is in PATH via shell profile.
    _patch_path()

    label = "proxy" if mode == "proxy" else "Anthropic direct"
    _ok(f"Claude Code → {label}")
    print(f"  Just type \033[1mclaude\033[0m — it will use the right config automatically.")
    print()


# ── codex ──────────────────────────────────────────────────────────────────────


def cmd_codex(mode: str = "proxy") -> None:
    """Configure Codex CLI to use the proxy or OpenAI directly."""
    if mode not in ("proxy", "direct"):
        _die("Usage: llm-relay codex <proxy|direct>")

    _CODEX_BIN.parent.mkdir(parents=True, exist_ok=True)

    if mode == "direct":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            api_key = input("  OpenAI API key: ").strip()
            if not api_key:
                _die("API key required for direct OpenAI access")
        _CODEX_BIN.write_text(f"""#!/bin/bash
# llm-relay — Codex CLI wrapper (OpenAI direct)
export OPENAI_API_KEY="{api_key}"
unset OPENAI_BASE_URL

real=""
for p in $(echo "$PATH" | tr ':' '\\n'); do
    [ "$p" = "$HOME/.llm-relay/bin" ] && continue
    if [ -x "$p/codex" ]; then real="$p/codex"; break; fi
done
exec "${{real:-codex}}" "$@"
""")
    else:
        _CODEX_BIN.write_text("""#!/bin/bash
# llm-relay — Codex CLI wrapper (auto-sources env)
source "$HOME/.llm-relay/.env"

real=""
for p in $(echo "$PATH" | tr ':' '\\n'); do
    [ "$p" = "$HOME/.llm-relay/bin" ] && continue
    if [ -x "$p/codex" ]; then real="$p/codex"; break; fi
done
exec "${real:-codex}" "$@"
""")

    _CODEX_BIN.chmod(0o755)
    _patch_path()

    label = "proxy" if mode == "proxy" else "OpenAI direct"
    _ok(f"Codex CLI → {label}")
    print(f"  Just type \033[1mcodex\033[0m — it will use the right config automatically.")
    print()


# ── logs ───────────────────────────────────────────────────────────────────────


def cmd_logs(lines: int = 20, follow: bool = False) -> None:
    """Display or follow the proxy log file."""
    if not _LOG_FILE.exists():
        print("  No log file yet. Start the proxy first.")
        return

    if follow:
        print(f"  Following {_LOG_FILE} (Ctrl+C to stop)...")
        try:
            subprocess.run(["tail", "-f", str(_LOG_FILE)])
        except KeyboardInterrupt:
            pass
    else:
        content = _LOG_FILE.read_text(encoding="utf-8")
        content_lines = content.strip().split("\n")
        for line in content_lines[-lines:]:
            print(f"  {line}")


# ── models ─────────────────────────────────────────────────────────────────────


def cmd_models(backend: str | None = None, refresh: bool = False) -> None:
    """List available models for a given backend (default: current)."""
    from llm_relay.models import get_models_for_backend, refresh_models, PROVIDER_MODEL_SOURCES

    if backend is None:
        cfg = config_manager.load()
        backend = cfg.provider if cfg else "deepseek"

    if backend not in PROVIDER_MODEL_SOURCES:
        choices = ", ".join(PROVIDER_MODEL_SOURCES)
        _die(f"Unknown backend {backend!r}. Available: {choices}")

    if refresh:
        refresh_models(backend)
        _ok(f"Models refreshed from {backend} API")

    models = get_models_for_backend(backend)
    print()
    print(f"  Models for {backend}:")
    for m in models:
        print(f"    {m}")
    print()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _patch_path() -> None:
    """Add ~/.llm-relay/bin to PATH in the shell profile."""
    bin_dir = Path.home() / ".llm-relay" / "bin"
    marker = ".llm-relay/bin"
    export_line = f'export PATH="{bin_dir}:$PATH"  # llm-relay'

    shell = os.path.basename(os.environ.get("SHELL", ""))
    home = Path.home()

    if shell == "zsh":
        profile = home / ".zshrc"
    elif shell == "bash":
        for name in (".bashrc", ".bash_profile", ".profile"):
            if (home / name).exists():
                profile = home / name
                break
        else:
            profile = home / ".bashrc"
    else:
        return

    try:
        existing = profile.read_text(encoding="utf-8") if profile.exists() else ""
    except OSError:
        return

    if marker in existing:
        return  # already patched

    try:
        with open(profile, "a", encoding="utf-8") as f:
            f.write(f"\n{export_line}\n")
    except OSError:
        pass


def _write_claude_env(provider: str, port: int | None = None, tls: bool = False) -> None:
    """Write ~/.llm-relay/claude-code.env for the given provider.

    *port* and *tls* override cfg defaults — used at start time so the env
    file's scheme + port match the actually-running proxy.
    """
    from llm_relay.models import get_models_for_backend

    models = get_models_for_backend(provider)
    if not models:
        models = ["deepseek-v4-pro", "deepseek-v4-flash"]

    # Use the same primary model for every Claude Code model slot so that
    # all requests — main turns, subagents, tool calls — use the same model.
    # This prevents confusing log entries where the model switches mid-session
    # (e.g. glm-5.1 for the main turn but minimax-m2.5 for a spawned subagent).
    primary  = models[0]
    opus     = primary
    sonnet   = primary
    haiku    = primary
    subagent = primary

    if port is None:
        cfg  = config_manager.load()
        port = cfg.port if cfg else 8080
    scheme = "https" if tls else "http"

    _CLAUDE_ENV.parent.mkdir(parents=True, exist_ok=True)
    _CLAUDE_ENV.write_text(f"""# llm-relay — Claude Code environment
# Source in your shell:  source ~/.llm-relay/claude-code.env

export ANTHROPIC_BASE_URL="{scheme}://127.0.0.1:{port}"
export ANTHROPIC_AUTH_TOKEN="llm-relay"
export ANTHROPIC_MODEL="{primary}"
export ANTHROPIC_DEFAULT_OPUS_MODEL="{opus}"
export ANTHROPIC_DEFAULT_SONNET_MODEL="{sonnet}"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="{haiku}"
export CLAUDE_CODE_SUBAGENT_MODEL="{subagent}"
export CLAUDE_CODE_EFFORT_LEVEL="max"
""", encoding="utf-8")
