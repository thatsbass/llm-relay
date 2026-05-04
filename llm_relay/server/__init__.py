"""Server package — HTTP handler and application entry point."""

from .app import create_server

__all__ = ["create_server"]
