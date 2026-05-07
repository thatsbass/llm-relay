"""OpenCode Go Chat Completions translator."""

from __future__ import annotations

from llm_relay.translators.chat_completions import ChatCompletionsTranslator


class OpenCodeGoTranslator(ChatCompletionsTranslator):
    """Translator for the OpenCode Go Chat Completions API."""

    DEFAULT_BASE_URL      = "https://opencode.ai/zen/go"
    DEFAULT_CHAT_ENDPOINT = "/v1/chat/completions"
    DEFAULT_MODEL         = "deepseek-v4-pro"
