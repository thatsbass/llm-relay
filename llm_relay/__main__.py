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
  llm-relay                     start proxy (wizard on first run)
  llm-relay start               start proxy
  llm-relay start --tls         start proxy with HTTPS (for Claude Desktop 3P)
  llm-relay stop                stop proxy running in another terminal
  llm-relay status              show running state and config
  llm-relay setup               re-run setup wizard
  llm-relay trust-ca            install the CA cert in system trust store
  llm-relay update              upgrade to the latest version
  llm-relay config port 9000    change port
  llm-relay config key sk-xxx   update API key
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
        help="Start the proxy in the foreground",
    )
    start_p.add_argument(
        "--tls",
        action="store_true",
        help="Enable HTTPS with a self-signed certificate (for Claude Desktop 3P)",
    )
    start_p.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="Port to listen on (default: 8080)",
    )
    subparsers.add_parser(
        "stop",
        help="Stop the running proxy (sends SIGTERM via PID file)",
    )
    subparsers.add_parser(
        "status",
        help="Show running state and active configuration",
    )
    subparsers.add_parser(
        "setup",
        help="Re-run the interactive setup wizard",
    )
    subparsers.add_parser(
        "trust-ca",
        help="Install the local CA certificate in the system trust store (for HTTPS)",
    )
    subparsers.add_parser(
        "update",
        help="Upgrade llm-relay to the latest version from GitHub",
    )

    config_p = subparsers.add_parser(
        "config",
        help="Update a single config value without re-running setup",
    )
    config_p.add_argument(
        "key",
        choices=["port", "key"],
        metavar="<port|key>",
        help="Setting to change",
    )
    config_p.add_argument(
        "value",
        metavar="<value>",
        help="New value (port: integer 1-65535 / key: API key string)",
    )

    return parser


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate command handler."""
    parser = _build_parser()
    args   = parser.parse_args()

    # Lazy import keeps stop/status fast.
    from llm_relay.cli.commands import (
        cmd_config,
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

    elif args.command == "config":
        cmd_config(args.key, args.value)

    else:
        # ``start`` or no subcommand — both start the proxy.
        tls = getattr(args, "tls", False) or os.environ.get(
            "LLM_RELAY_TLS", ""
        ).lower() in ("1", "true", "yes")
        port = getattr(args, "port", None)
        cmd_start(tls=tls, port=port)


if __name__ == "__main__":
    main()
