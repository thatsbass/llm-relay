"""
Application factory and server lifecycle.

``create_server()`` is the single wiring point for the entire application.
It assembles all components — config, session store, translator, handler —
and returns a ready-to-run ``HTTPServer`` instance.

Keeping all wiring in one function makes the dependency graph explicit and
testable: tests can call ``create_server()`` with a custom config and inspect
or control exactly what gets created.
"""

from __future__ import annotations

from http.server import HTTPServer

from llm_relay.config import Config
from llm_relay.server.handler import make_handler
from llm_relay.session.store import SessionStore
from llm_relay.translators.factory import TranslatorFactory


def create_server(config: Config) -> HTTPServer:
    """
    Wire all application components together and return a configured server.

    Component graph::

        Config  ──┬──► SessionStore
                  ├──► TranslatorFactory.create()  ──► AbstractTranslator
                  └──► make_handler()  ◄── (SessionStore + Translator)
                            │
                            ▼
                        HTTPServer(127.0.0.1:<port>)

    The server listens only on ``127.0.0.1`` (loopback) by design.
    llm-relay is a local development tool; exposing it on ``0.0.0.0``
    would allow any process on the network to use (and potentially exhaust)
    the configured API key.

    Args:
        config: Immutable runtime configuration built by ``Config.from_env()``.

    Returns:
        An ``HTTPServer`` instance bound to the configured port.
        Call ``.serve_forever()`` to start accepting requests.

    Raises:
        ValueError:   If ``config.backend`` is not a registered translator.
        OSError:      If the port is already in use.
    """
    # ── Session store ─────────────────────────────────────────────────────────
    session_store = SessionStore(
        max_sessions=config.max_sessions,
        trim_to=config.sessions_trim_to,
    )

    # ── Backend translator ────────────────────────────────────────────────────
    # The factory validates the backend name and raises ValueError if unknown.
    translator = TranslatorFactory.create(config.backend, config)

    # ── HTTP handler class ────────────────────────────────────────────────────
    handler_class = make_handler(config, session_store, translator)

    # ── HTTP server ───────────────────────────────────────────────────────────
    return HTTPServer(("127.0.0.1", config.port), handler_class)
