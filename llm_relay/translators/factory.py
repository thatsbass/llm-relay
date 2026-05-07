"""Registry and factory for AbstractTranslator implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from llm_relay.config import Config
from llm_relay.translators.base import AbstractTranslator

if TYPE_CHECKING:
    pass


class TranslatorFactory:
    """Registry and factory for AbstractTranslator implementations."""

    # Maps backend name (lowercase) → concrete translator class.
    _registry: dict[str, type[AbstractTranslator]] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    @classmethod
    def register(cls, name: str, translator_class: type[AbstractTranslator]) -> None:
        """Register *translator_class* under *name*; silently overwrites duplicates."""
        if not (isinstance(translator_class, type)
                and issubclass(translator_class, AbstractTranslator)):
            raise TypeError(
                f"{translator_class!r} must be a subclass of AbstractTranslator"
            )
        cls._registry[name.lower()] = translator_class

    # ── Creation ──────────────────────────────────────────────────────────────

    @classmethod
    def create(cls, name: str, config: Config) -> AbstractTranslator:
        """Instantiate the translator registered under *name*.

        Raises:
            ValueError: If *name* is not a registered backend.
        """
        key = name.lower()
        translator_class = cls._registry.get(key)

        if translator_class is None:
            available = ", ".join(sorted(cls._registry)) or "(none registered)"
            raise ValueError(
                f"Unknown backend {name!r}. "
                f"Available backends: {available}. "
                f"Register a new backend with TranslatorFactory.register()."
            )

        return translator_class(config)

    # ── Introspection ─────────────────────────────────────────────────────────

    @classmethod
    def available_backends(cls) -> list[str]:
        """Return a sorted list of registered backend names."""
        return sorted(cls._registry)


# ── Built-in backend registrations ───────────────────────────────────────────
# Imports are at the bottom to avoid circular imports (translators import base, not factory).

from llm_relay.translators.anthropic_pass import DeepSeekAnthropicTranslator  # noqa: E402
from llm_relay.translators.deepseek import DeepSeekTranslator  # noqa: E402

TranslatorFactory.register("deepseek", DeepSeekTranslator)
TranslatorFactory.register("deepseek-anthropic", DeepSeekAnthropicTranslator)
