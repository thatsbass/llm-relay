"""Application factory — wires all components and returns a ready HTTPServer."""

from __future__ import annotations

import os
import ssl
import sys
from http.server import HTTPServer
from socketserver import ThreadingMixIn

from llm_relay.config import Config
from llm_relay.routing.engine import RoutingEngine
from llm_relay.server.handler import make_handler
from llm_relay.server.tls import create_ssl_context
from llm_relay.session.store import SessionStore
from llm_relay.translators.factory import TranslatorFactory


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer that spawns a new thread per request.

    Without this, a slow upstream call (30-60s for reasoning models) blocks
    the entire server — Claude Code can't connect for retries or health checks,
    and reports "ConnectionRefused" even though the server is alive.
    """
    daemon_threads = True  # threads die when main process exits


def create_server(config: Config) -> HTTPServer:
    """Wire all application components and return an HTTPServer bound to 127.0.0.1."""
    session_store = SessionStore(
        max_sessions=config.max_sessions,
        trim_to=config.sessions_trim_to,
    )
    primary_translator = TranslatorFactory.create(config.backend, config)

    fallback_translator = None
    fallback_name = os.environ.get("LLM_RELAY_FALLBACK_BACKEND", "").strip()
    if fallback_name:
        try:
            fallback_translator = TranslatorFactory.create(fallback_name, config)
        except ValueError:
            pass  # silently ignore unknown fallback

    routing = RoutingEngine(primary_translator, fallback_translator)
    handler_class = make_handler(config, session_store, routing)
    server = _ThreadedHTTPServer(("127.0.0.1", config.port), handler_class)

    if config.tls:
        ctx = create_ssl_context()
        server.socket = ctx.wrap_socket(server.socket, server_side=True)

    scheme = "https" if config.tls else "http"
    print(
        f"[llm-relay] started  backend={config.backend}"
        f"  url={scheme}://127.0.0.1:{config.port}"
        f"  tls={config.tls}  debug={config.debug}",
        file=sys.stderr, flush=True,
    )

    return server
