"""
Translator factory.

Responsibility
--------------
Map a backend name (e.g. ``"deepseek"``) to its concrete
``AbstractTranslator`` subclass and instantiate it with the correct
configuration.

Extending the factory
---------------------
To add a new backend, you only need two things:

  1. Create a new file ``llm_relay/translators/my_backend.py`` that subclasses
     ``AbstractTranslator``.
  2. Register it here::

         from llm_relay.translators.my_backend import MyBackendTranslator
         TranslatorFactory.register("my_backend", MyBackendTranslator)

  Nothing else in the codebase needs to change.

Why a class-level registry instead of a module-level dict?
----------------------------------------------------------
A ``@classmethod`` registry keeps the factory state encapsulated and makes it
straightforward to add entries from tests without mutating a global dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from llm_relay.config import Config
from llm_relay.translators.base import AbstractTranslator

if TYPE_CHECKING:
    pass


class TranslatorFactory:
    """
    Registry and factory for ``AbstractTranslator`` implementations.

    All public methods are class-methods — ``TranslatorFactory`` is never
    instantiated directly.

    Example::

        # In application startup:
        config = Config.from_env(port=8080)
        translator = TranslatorFactory.create(config.backend, config)

        # In tests, register a mock backend:
        TranslatorFactory.register("mock", MockTranslator)
        t = TranslatorFactory.create("mock", config)
    """

    # Maps backend name (lowercase) → concrete translator class.
    # Populated at module import time by the registration calls at the
    # bottom of this file.
    _registry: dict[str, type[AbstractTranslator]] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    @classmethod
    def register(cls, name: str, translator_class: type[AbstractTranslator]) -> None:
        """
        Register *translator_class* under the key *name*.

        If *name* is already registered, the previous entry is **silently
        overwritten**.  This allows test code to substitute a mock backend
        without error.

        Args:
            name:             Case-insensitive backend identifier
                              (e.g. ``"deepseek"``).
            translator_class: A concrete subclass of ``AbstractTranslator``.

        Raises:
            TypeError: If *translator_class* is not a subclass of
                       ``AbstractTranslator``.
        """
        if not (isinstance(translator_class, type)
                and issubclass(translator_class, AbstractTranslator)):
            raise TypeError(
                f"{translator_class!r} must be a subclass of AbstractTranslator"
            )
        cls._registry[name.lower()] = translator_class

    # ── Creation ──────────────────────────────────────────────────────────────

    @classmethod
    def create(cls, name: str, config: Config) -> AbstractTranslator:
        """
        Instantiate and return the translator for *name*.

        Args:
            name:   Backend identifier (case-insensitive).
                    Must match a previously registered key.
            config: Immutable runtime configuration passed to the translator.

        Returns:
            A ready-to-use ``AbstractTranslator`` instance.

        Raises:
            ValueError: If *name* is not in the registry, with a message that
                        lists the available backends so the error is actionable.
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
#
# These imports are placed at the bottom of the file (after the class
# definition) to avoid circular import issues: the translator modules import
# from ``base``, not from ``factory``.

from llm_relay.translators.deepseek import DeepSeekTranslator  # noqa: E402

TranslatorFactory.register("deepseek", DeepSeekTranslator)
