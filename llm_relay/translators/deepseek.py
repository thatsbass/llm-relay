"""DeepSeek Chat Completions translator — thin config layer over the generic ChatCompletionsTranslator."""

from __future__ import annotations

from llm_relay.translators.chat_completions import ChatCompletionsTranslator


class DeepSeekTranslator(ChatCompletionsTranslator):
    """Translator for the DeepSeek Chat Completions API.

    Configures the generic ``ChatCompletionsTranslator`` with
    DeepSeek-specific defaults.  All request/response logic is
    inherited from the base class.
    """

    DEFAULT_BASE_URL      = "https://api.deepseek.com"
    DEFAULT_CHAT_ENDPOINT = "/v1/chat/completions"
    DEFAULT_MODEL         = "deepseek-chat"
