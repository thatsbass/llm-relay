"""Application factory — wires all components and returns a ready HTTPServer."""

from __future__ import annotations

from http.server import HTTPServer

from llm_relay.config import Config
from llm_relay.server.handler import make_handler
from llm_relay.session.store import SessionStore
from llm_relay.translators.factory import TranslatorFactory


def create_server(config: Config) -> HTTPServer:
    """Wire all application components and return an HTTPServer bound to 127.0.0.1."""
    session_store = SessionStore(
        max_sessions=config.max_sessions,
        trim_to=config.sessions_trim_to,
    )
    translator    = TranslatorFactory.create(config.backend, config)
    handler_class = make_handler(config, session_store, translator)
    return HTTPServer(("127.0.0.1", config.port), handler_class)
