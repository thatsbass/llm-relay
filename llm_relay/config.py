"""Runtime configuration. All environment access is centralised in Config.from_env()."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# ── Provider → env-key mapping ───────────────────────────────────────────────

_PROVIDER_ENV_KEYS: dict[str, str] = {
    "deepseek":           "DEEPSEEK_API_KEY",
    "deepseek-anthropic": "DEEPSEEK_API_KEY",
    "opencode":           "OPENCODE_API_KEY",
}


# ── Defaults ─────────────────────────────────────────────────────────────────

_DEFAULT_MAX_HISTORY_MESSAGES: int = 40
_DEFAULT_HISTORY_TRIM_TO:      int = 35
_DEFAULT_MAX_SESSIONS:         int = 80
_DEFAULT_SESSIONS_TRIM_TO:     int = 20
_DEFAULT_MAX_TOOL_CALL_TURNS:  int = 25  # after this many turns, force tool_choice="none"
_DEFAULT_MAX_OUTPUT_TOKENS:    int = 4096


# ── Tool filter ───────────────────────────────────────────────────────────────

# Codex-internal tools with no backend equivalent — forwarding them causes API errors.
SKIP_TOOLS: frozenset[str] = frozenset({
    "write_stdin",
    "send_input",
    "resume_agent",
    "wait_agent",
    "close_agent",
})

# ── Role allowlist ────────────────────────────────────────────────────────────

# The Responses API allows "developer" as a role; Chat Completions does not.
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
    """Immutable runtime configuration. Build once at startup; share via dependency injection."""

    port:               int
    api_key:            str
    backend:            str
    debug:              bool
    max_output_tokens:  int

    api_base_url:  str | None = None   # override translator default base URL
    model:         str | None = None   # override translator default model
    tls:           bool       = False  # enable HTTPS (self-signed cert)

    max_history_messages: int = field(default=_DEFAULT_MAX_HISTORY_MESSAGES)
    history_trim_to:      int = field(default=_DEFAULT_HISTORY_TRIM_TO)
    max_sessions:         int = field(default=_DEFAULT_MAX_SESSIONS)
    sessions_trim_to:     int = field(default=_DEFAULT_SESSIONS_TRIM_TO)
    max_tool_call_turns:  int = field(default=_DEFAULT_MAX_TOOL_CALL_TURNS)

    @classmethod
    def from_env(cls, *, port: int = 8080, debug: bool = False) -> "Config":
        """Build a Config from environment variables.

        Raises:
            RuntimeError: If the provider's API key env var is not set.
        """
        backend = os.environ.get("LLM_RELAY_BACKEND", "deepseek").lower()
        env_key = _PROVIDER_ENV_KEYS.get(backend, "DEEPSEEK_API_KEY")
        api_key = os.environ.get(env_key, "").strip()
        if not api_key:
            raise RuntimeError(
                f"{env_key} environment variable is not set.\n"
                f"  → run: llm-relay config key <your-key>"
            )

        env_debug = os.environ.get("LLM_RELAY_DEBUG", "")
        return cls(
            port=int(os.environ.get("LLM_RELAY_PORT", port)),
            api_key=api_key,
            backend=backend,
            debug=debug or env_debug.lower() in ("1", "true", "yes"),
            max_output_tokens=int(
                os.environ.get("LLM_RELAY_MAX_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS)
            ),
            api_base_url=os.environ.get("LLM_RELAY_API_BASE_URL") or None,
            model=os.environ.get("LLM_RELAY_MODEL") or None,
            tls=os.environ.get("LLM_RELAY_TLS", "").lower() in ("1", "true", "yes"),
        )

    def redacted(self) -> str:
        """Return a log-safe summary with the API key masked."""
        masked = f"{self.api_key[:6]}...{self.api_key[-4:]}" if self.api_key else "—"
        return f"Config(backend={self.backend!r}, port={self.port}, api_key={masked})"
