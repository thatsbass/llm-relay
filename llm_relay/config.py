"""
Configuration module.

All tuneable constants and the ``Config`` dataclass live here.
Nothing else in the codebase should read ``os.environ`` directly —
all environment access is centralised in ``Config.from_env()``.

Design note: ``Config`` is a frozen dataclass (immutable after creation).
Build one instance at startup and pass it around via dependency injection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# ── Hard limits ───────────────────────────────────────────────────────────────
#
# These defaults protect against runaway memory usage and infinite tool-call
# loops.  They can be overridden per-instance via ``Config.from_env()``.

_DEFAULT_MAX_HISTORY_MESSAGES: int = 40   # Total messages kept per session.
_DEFAULT_HISTORY_TRIM_TO:      int = 35   # Messages retained after trimming.
_DEFAULT_MAX_SESSIONS:         int = 80   # Max concurrent sessions in memory.
_DEFAULT_SESSIONS_TRIM_TO:     int = 20   # Sessions kept after LRU eviction.
_DEFAULT_MAX_TOOL_CALL_TURNS:  int = 25   # After this many tool turns,
                                           # force tool_choice="none" to break
                                           # potential infinite loops.
_DEFAULT_MAX_OUTPUT_TOKENS:    int = 4096


# ── Tool filter ───────────────────────────────────────────────────────────────
#
# These Codex-internal tool names have no counterpart on upstream backends.
# Forwarding them as-is causes API errors, so we silently drop them during
# tool translation.

SKIP_TOOLS: frozenset[str] = frozenset({
    "write_stdin",
    "send_input",
    "resume_agent",
    "wait_agent",
    "close_agent",
})

# ── Role allowlist ────────────────────────────────────────────────────────────
#
# The Responses API allows roles beyond the Chat Completions spec
# (e.g. "developer").  We normalise unknown roles rather than reject them.

ALLOWED_ROLES: frozenset[str] = frozenset({"system", "user", "assistant", "tool"})


# ── System prompts ────────────────────────────────────────────────────────────
#
# Injected at the top of every conversation so the backend understands
# how to behave as a coding agent regardless of its default personality.

TOOL_GUIDE: str = """
# HOW TO USE TOOLS
- exec_command: Primary tool for shell commands, file creation (heredoc), git, npm, etc.
- update_plan: Track progress on multi-step tasks.
- request_user_input: Ask for clarification — use sparingly.
- view_image: Inspect image files.
- spawn_agent: Delegate parallel subtasks.

# RULES
1. Create files via exec_command heredoc. Never invent tools like "write" or "file_write".
2. A greeting → short text reply only. No function call.
3. An action request → call exec_command immediately. Don't narrate, just act.
4. After a successful action → brief confirmation, then stop.
5. For multi-step tasks → call update_plan to track state.
""".strip()

ESSENTIAL_RULES: str = """
# IDENTITY
You are an AI coding agent. You help users by executing commands and writing code.
Use the provided tools to take real action — never describe what you would do.

# SANDBOX
- Commands run in a sandbox by default. Use sandbox_permissions="require_escalated" for approval.
- Network access may be restricted; request escalation when needed.
- Use exec_command for all shell operations.

# COMMUNICATION
- Be concise and direct. Briefly inform the user about actions in progress.
- Never claim to be "Codex" or "OpenAI". You are an AI assistant.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Config:
    """
    Immutable runtime configuration for llm-relay.

    All fields are set once at startup; the frozen dataclass prevents
    accidental mutation elsewhere in the codebase.

    Example::

        config = Config.from_env(port=8080, debug=False)
    """

    # ── Network ───────────────────────────────────────────────────────────────

    port: int
    """Local port the proxy server listens on."""

    # ── Backend ───────────────────────────────────────────────────────────────

    api_key: str
    """Secret key forwarded to the upstream LLM API (never logged)."""

    backend: str
    """
    Backend identifier resolved by ``TranslatorFactory``.
    Currently supported: ``"deepseek"``.
    """

    # ── Behaviour ─────────────────────────────────────────────────────────────

    debug: bool
    """When True, verbose request/response logs are written to stderr."""

    max_output_tokens: int
    """Default token budget for a single completion request."""

    # ── Limits ────────────────────────────────────────────────────────────────

    max_history_messages: int = field(default=_DEFAULT_MAX_HISTORY_MESSAGES)
    """
    Maximum number of messages kept per session before the history is
    trimmed.  Keeping this below the backend's context window avoids
    silent truncation errors.
    """

    history_trim_to: int = field(default=_DEFAULT_HISTORY_TRIM_TO)
    """Number of messages retained when the history limit is hit."""

    max_sessions: int = field(default=_DEFAULT_MAX_SESSIONS)
    """Maximum number of concurrent sessions held in memory."""

    sessions_trim_to: int = field(default=_DEFAULT_SESSIONS_TRIM_TO)
    """Number of sessions kept after an LRU eviction sweep."""

    max_tool_call_turns: int = field(default=_DEFAULT_MAX_TOOL_CALL_TURNS)
    """
    Maximum consecutive tool-call turns before forcing ``tool_choice="none"``.
    Guards against infinite agentic loops where the model keeps calling tools
    without ever producing a final text answer.
    """

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, *, port: int = 8080, debug: bool = False) -> "Config":
        """
        Build a ``Config`` from environment variables.

        CLI arguments (``port``, ``debug``) are resolved by argparse before
        this method is called and are passed in directly so they can override
        the corresponding environment variables.

        Environment variables:
            DEEPSEEK_API_KEY   (required) Secret key for the upstream API.
            LLM_RELAY_PORT     (optional) Overrides the ``port`` argument.
            LLM_RELAY_BACKEND  (optional) Translator backend. Default: deepseek.
            LLM_RELAY_DEBUG    (optional) ``1``/``true``/``yes`` enables debug.
            LLM_RELAY_MAX_TOKENS (optional) Max output tokens. Default: 4096.

        Raises:
            RuntimeError: If the required API key variable is not set.
        """
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY environment variable is not set.\n"
                "  → export DEEPSEEK_API_KEY=sk-your-key-here\n"
                "  → or copy .env.example to .env and fill in your key."
            )

        # LLM_RELAY_PORT can override the CLI --port argument.
        effective_port = int(os.environ.get("LLM_RELAY_PORT", port))

        # LLM_RELAY_DEBUG can override the CLI --debug flag.
        env_debug = os.environ.get("LLM_RELAY_DEBUG", "")
        effective_debug = debug or env_debug.lower() in ("1", "true", "yes")

        return cls(
            port=effective_port,
            api_key=api_key,
            backend=os.environ.get("LLM_RELAY_BACKEND", "deepseek").lower(),
            debug=effective_debug,
            max_output_tokens=int(
                os.environ.get("LLM_RELAY_MAX_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS)
            ),
        )

    def redacted(self) -> str:
        """Return a human-readable summary safe to print (API key is masked)."""
        masked = f"{self.api_key[:6]}...{self.api_key[-4:]}" if self.api_key else "—"
        return (
            f"Config(backend={self.backend!r}, port={self.port}, "
            f"debug={self.debug}, api_key={masked})"
        )
