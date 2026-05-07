"""PID file helpers for cross-terminal proxy start/stop via ~/.llm-relay/proxy.pid."""

from __future__ import annotations

import os
import signal
import time
from typing import Optional

from llm_relay.cli.config_manager import RELAY_DIR

_PID_FILE = RELAY_DIR / "proxy.pid"


# ── Public API ────────────────────────────────────────────────────────────────


def write(pid: int | None = None) -> None:
    """Write *pid* (or current process PID) to the PID file."""
    RELAY_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid if pid is not None else os.getpid()), encoding="utf-8")


def clear() -> None:
    """Remove the PID file on clean shutdown."""
    _PID_FILE.unlink(missing_ok=True)


def read() -> Optional[int]:
    """Return the live proxy PID, or None if the process is gone (cleans up stale files)."""
    if not _PID_FILE.exists():
        return None

    try:
        pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None

    # os.kill(pid, 0) is a no-op signal used purely as a process existence check.
    try:
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, PermissionError):
        _PID_FILE.unlink(missing_ok=True)
        return None


def stop() -> bool:
    """Send SIGTERM to the proxy, escalate to SIGKILL if needed.

    Returns True if a process was killed, False if nothing was running.
    """
    pid = read()
    if pid is None:
        return False

    # 1. Graceful shutdown via SIGTERM.
    _kill(pid, signal.SIGTERM)
    for _ in range(30):  # up to 3 seconds
        time.sleep(0.1)
        if not _process_alive(pid):
            clear()
            return True

    # 2. Force kill via SIGKILL.
    _kill(pid, signal.SIGKILL)
    for _ in range(10):  # up to 1 second
        time.sleep(0.1)
        if not _process_alive(pid):
            clear()
            return True

    clear()
    return False


def is_running() -> bool:
    """Return ``True`` if a live proxy process is found."""
    return read() is not None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _kill(pid: int, sig: int) -> bool:
    try:
        os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
