"""
Translators package.

Contains the abstract base translator, the Factory, and concrete
backend implementations (DeepSeek, etc.).
"""

from .base import AbstractTranslator
from .factory import TranslatorFactory
from .deepseek import DeepSeekTranslator

__all__ = ["AbstractTranslator", "TranslatorFactory", "DeepSeekTranslator"]
