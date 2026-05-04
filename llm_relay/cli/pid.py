"""
PID file management.

Enables ``llm-relay stop`` (launched in a second terminal) to send SIGTERM
to a proxy that is already running in the foreground.

Protocol
--------
1. On proxy start  → ``write()`` saves ``os.getpid()`` to the PID file.
2. On clean stop   → ``clear()`` deletes the PID file (Ctrl+C handler).
3. On crash/kill   → PID file stays on disk (stale); ``read()`` detects
                     the stale file via ``os.kill(pid, 0)`` and cleans it up.

The PID file lives at ``~/.llm-relay/proxy.pid`` alongside the user config,
so it is naturally scoped to the local user and easy to inspect manually.
"""

from __future__ import annotations

import os
import signal
from typing import Optional

from llm_relay.cli.config_manager import RELAY_DIR

_PID_FILE = RELAY_DIR / "proxy.pid"


# ── Public API ────────────────────────────────────────────────────────────────


def write() -> None:
    """
    Write the current process PID to the PID file.

    Called once, immediately after the ``HTTPServer`` is created and before
    ``serve_forever()`` blocks, so that ``stop()`` can target the right PID
    even if the server hasn't started accepting connections yet.
    """
    RELAY_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def clear() -> None:
    """
    Remove the PID file.

    Called on clean shutdown (``KeyboardInterrupt`` or ``SIGTERM`` handler).
    A missing PID file is not an error — ``missing_ok=True`` silences it.
    """
    _PID_FILE.unlink(missing_ok=True)


def read() -> Optional[int]:
    """
    Read the PID from the file and verify the process is still alive.

    If the PID file exists but the process is gone (crash / ``kill -9``),
    the stale file is silently removed and ``None`` is returned.

    Returns:
        The live PID integer, or ``None`` if no proxy is running.
    """
    if not _PID_FILE.exists():
        return None

    try:
        pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None

    # ``os.kill(pid, 0)`` sends no actual signal — it is purely an existence
    # check.  It raises ``ProcessLookupError`` when the process is gone.
    try:
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, PermissionError):
        _PID_FILE.unlink(missing_ok=True)
        return None


def stop() -> bool:
    """
    Send ``SIGTERM`` to the running proxy and remove the PID file.

    Returns:
        ``True``  — proxy was running; SIGTERM was delivered.
        ``False`` — proxy is not running (or PID file is stale).
    """
    pid = read()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        clear()
        return True
    except (ProcessLookupError, PermissionError):
        clear()
        return False


def is_running() -> bool:
    """Return ``True`` if a live proxy process is found."""
    return read() is not None
