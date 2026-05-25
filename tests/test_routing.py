"""Tests for the routing engine, circuit breaker, and fallback chain."""

import unittest
from unittest.mock import MagicMock, patch

from llm_relay.routing.circuit_breaker import CircuitBreaker
from llm_relay.routing.fallback import FallbackChain
from llm_relay.routing.engine import RoutingEngine


class TestCircuitBreaker(unittest.TestCase):
    def test_initial_state_closed(self):
        cb = CircuitBreaker("test")
        self.assertEqual(cb.state, "closed")
        self.assertTrue(cb.allow_request())

    def test_trips_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            self.assertTrue(cb.allow_request())
            cb.record_failure()
        self.assertEqual(cb.state, "open")
        self.assertFalse(cb.allow_request())

    def test_reset_after_success(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(2):
            cb.record_failure()
        cb.record_success()
        self.assertEqual(cb.state, "closed")
        self.assertEqual(cb._failures, 0)

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, reset_timeout=0.001)
        cb.record_failure()
        self.assertEqual(cb.state, "open")
        import time
        time.sleep(0.002)
        self.assertTrue(cb.allow_request())
        self.assertEqual(cb.state, "half_open")

    def test_half_open_success_closes(self):
        cb = CircuitBreaker("test", failure_threshold=1, reset_timeout=0.001)
        cb.record_failure()
        import time
        time.sleep(0.002)
        self.assertTrue(cb.allow_request())
        self.assertEqual(cb.state, "half_open")
        cb.record_success()
        self.assertEqual(cb.state, "closed")


class TestFallbackChain(unittest.TestCase):
    def test_empty_chain_raises(self):
        with self.assertRaises(ValueError):
            FallbackChain([])

    def test_primary_succeeds(self):
        t1 = MagicMock()
        chain = FallbackChain([t1])

        def build(t): return b"payload"
        def forward(t, p): return b"response"
        def parse(t, r): return MagicMock()

        result, used = chain.try_all(build, forward, parse)
        self.assertIs(used, t1)

    def test_primary_fails_fallback_succeeds(self):
        t1 = MagicMock()
        t2 = MagicMock()
        chain = FallbackChain([t1, t2], breaker_threshold=1)

        call_count = [0]

        def forward(t, p):
            call_count[0] += 1
            if t is t1:
                from urllib.error import URLError
                raise URLError("fail")
            return b"ok"

        def build(t): return b"x"
        def parse(t, r): return MagicMock()

        result, used = chain.try_all(build, forward, parse)
        self.assertIs(used, t2)
        self.assertEqual(call_count[0], 2)

    def test_skips_open_breaker(self):
        t1 = MagicMock()
        t2 = MagicMock()
        chain = FallbackChain([t1, t2], breaker_threshold=1)

        # Open the breaker for t1
        breaker = chain._breakers[chain._key(t1)]
        for _ in range(5):
            breaker.record_failure()

        calls = []
        def build(t): return b"x"
        def forward(t, p):
            calls.append(t)
            return b"ok"
            # Actually t1 would be rejected already by allow_request

        def parse(t, r): return MagicMock()

        # This should skip t1 (breaker open) and use t2
        result, used = chain.try_all(build, forward, parse)
        self.assertIs(used, t2)


class TestRoutingEngine(unittest.TestCase):
    def test_has_pass_through_true(self):
        from llm_relay.translators.anthropic_pass import DeepSeekAnthropicTranslator
        from llm_relay.config import Config
        import os
        os.environ["DEEPSEEK_API_KEY"] = "sk-test"
        try:
            config = Config.from_env(port=8080)
            translator = DeepSeekAnthropicTranslator(config)
            engine = RoutingEngine(translator)
            self.assertTrue(engine.has_pass_through())
        finally:
            del os.environ["DEEPSEEK_API_KEY"]

    def test_has_pass_through_false(self):
        from llm_relay.translators.deepseek import DeepSeekTranslator
        from llm_relay.config import Config
        import os
        os.environ["DEEPSEEK_API_KEY"] = "sk-test"
        try:
            config = Config.from_env(port=8080)
            translator = DeepSeekTranslator(config)
            engine = RoutingEngine(translator)
            self.assertFalse(engine.has_pass_through())
        finally:
            del os.environ["DEEPSEEK_API_KEY"]
