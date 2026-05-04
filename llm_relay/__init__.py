"""
llm-relay
=========
A local proxy that translates the OpenAI Responses API to any
OpenAI-compatible LLM backend (DeepSeek, Mistral, etc.).

Typical usage::

    $ llm-relay --port 8080
    $ python -m llm_relay --port 8080 --debug
"""

__version__ = "0.1.0"
__author__ = "llm-relay contributors"
__license__ = "MIT"
