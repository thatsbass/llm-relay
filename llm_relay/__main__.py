"""Entry point for ``python -m llm_relay`` and the ``llm-relay`` CLI command."""

from __future__ import annotations

import argparse
import os
import sys

from llm_relay import __version__


# ── Argument parser ───────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-relay",
        description=(
            "Local proxy that translates OpenAI Responses API "
            "and Anthropic Messages API to any LLM backend."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  llm-relay start --daemon          start proxy in background
  llm-relay start --tls --daemon    start with HTTPS (Claude Desktop 3P)
  llm-relay stop                    stop the proxy
  llm-relay status                  show running state and config
  llm-relay logs -f                 follow proxy log
  llm-relay setup                   re-run setup wizard
  llm-relay config backend deepseek switch provider
  llm-relay config backend list     list available backends
  llm-relay claude proxy            Claude Code → proxy
  llm-relay claude direct           Claude Code → Anthropic
        """,
    )

    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"llm-relay {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    start_p = subparsers.add_parser(
        "start",
        help="Start the proxy",
    )
    start_p.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Run in background (logs to ~/.llm-relay/proxy.log)",
    )
    start_p.add_argument(
        "--tls",
        action="store_true",
        help="Enable HTTPS (for Claude Desktop 3P)",
    )
    start_p.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="Port (default: 8080)",
    )
    start_p.add_argument(
        "--force", "-f",
        action="store_true",
        help="Kill old proxy process before starting",
    )
    subparsers.add_parser("stop", help="Stop the proxy")
    subparsers.add_parser("status", help="Show running state and config")
    subparsers.add_parser("setup", help="Re-run setup wizard")
    subparsers.add_parser("trust-ca", help="Install CA cert in system trust store")
    subparsers.add_parser("update", help="Upgrade from GitHub")

    # logs
    logs_p = subparsers.add_parser("logs", help="Display proxy logs")
    logs_p.add_argument("-n", type=int, default=20, help="Number of lines (default: 20)")
    logs_p.add_argument("-f", "--follow", action="store_true", help="Follow log")

    # config
    config_p = subparsers.add_parser("config", help="Update config")
    config_p.add_argument("key", choices=["port", "key", "backend"], metavar="<key>")
    config_p.add_argument("value", nargs="?", metavar="<value>", help="New value")

    # backend (shortcut)
    backend_p = subparsers.add_parser("backend", help="Switch backend provider")
    backend_p.add_argument("name", nargs="?", default=None, help="Backend name (or 'list')")

    # claude (Claude Code mode)
    claude_p = subparsers.add_parser("claude", help="Configure Claude Code CLI")
    claude_p.add_argument("mode", choices=["proxy", "direct"], help="proxy | direct")

    codex_p = subparsers.add_parser("codex", help="Configure Codex CLI")
    codex_p.add_argument("mode", nargs="?", choices=["proxy", "direct"], default="proxy", help="proxy | direct")

    models_p = subparsers.add_parser("models", help="List or refresh available models")
    models_p.add_argument("--backend", "-b", default=None, help="Backend to query (default: current)")
    models_p.add_argument("--refresh", "-r", action="store_true", help="Force-refresh from API")

    return parser


# ── Internal daemon worker ────────────────────────────────────────────────────


def _cmd_serve() -> None:
    """Internal daemon worker — spawned by subprocess.Popen, never called directly.

    Reads the readiness-pipe FD from LLM_RELAY_READY_FD, starts the server,
    signals the parent with b"ok", then serves forever.  stdout/stderr are
    already redirected to the log file by the parent before spawning.
    """
    import signal
    from llm_relay.cli import pid as _pid
    from llm_relay.config import Config
    from llm_relay.server.app import create_server

    w_fd_str      = os.environ.get("LLM_RELAY_READY_FD", "")
    w_fd          = int(w_fd_str) if w_fd_str.isdigit() else None
    effective_port = int(os.environ.get("LLM_RELAY_PORT", "8080"))

    def _fail(msg: str) -> None:
        if w_fd is not None:
            try:
                os.write(w_fd, msg.encode())
                os.close(w_fd)
            except OSError:
                pass
        sys.exit(1)

    try:
        config = Config.from_env(port=effective_port)
    except RuntimeError as exc:
        _fail(f"Cannot start: {exc}")
        return  # unreachable, satisfies type checker

    try:
        server = create_server(config)
    except OSError as exc:
        _fail(f"Cannot bind to port {effective_port}: {exc.strerror}")
        return

    if w_fd is not None:
        os.write(w_fd, b"ok")
        os.close(w_fd)

    _pid.write(port=effective_port)

    def _on_sigterm(signum, frame):
        _pid.clear()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _pid.clear()
        server.shutdown()


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    # Internal daemon worker — spawned by _start_daemon via subprocess.Popen.
    if len(sys.argv) >= 2 and sys.argv[1] == "_serve":
        _cmd_serve()
        return

    parser = _build_parser()
    args   = parser.parse_args()

    from llm_relay.cli.commands import (
        cmd_backend,
        cmd_claude,
        cmd_codex,
        cmd_config,
        cmd_logs,
        cmd_models,
        cmd_setup,
        cmd_start,
        cmd_status,
        cmd_stop,
        cmd_trust_ca,
        cmd_update,
    )

    if args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "setup":
        cmd_setup()
    elif args.command == "trust-ca":
        cmd_trust_ca()
    elif args.command == "update":
        cmd_update()
    elif args.command == "logs":
        cmd_logs(lines=args.n, follow=args.follow)
    elif args.command == "backend":
        cmd_backend(name=args.name)
    elif args.command == "claude":
        cmd_claude(args.mode)
    elif args.command == "codex":
        cmd_codex(mode=args.mode)
    elif args.command == "models":
        cmd_models(backend=args.backend, refresh=args.refresh)
    elif args.command == "config":
        if args.key == "backend":
            cmd_backend(name=args.value)
        elif args.key in ("port", "key"):
            cmd_config(args.key, args.value)
        else:
            print(f"  Unknown config key: {args.key}")
            sys.exit(1)
    else:
        tls = getattr(args, "tls", False) or os.environ.get(
            "LLM_RELAY_TLS", ""
        ).lower() in ("1", "true", "yes")
        port = getattr(args, "port", None)
        daemon = getattr(args, "daemon", False)
        force = getattr(args, "force", False)
        cmd_start(tls=tls, port=port, daemon=daemon, force=force)


if __name__ == "__main__":
    main()
