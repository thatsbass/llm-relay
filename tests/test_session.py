"""
Tests for llm_relay.session.store.SessionStore.

Covers: basic get/save/delete, LRU eviction order, thread-safety invariant,
and constructor validation.
"""

import threading
import unittest

from llm_relay.session.store import SessionStore


class TestSessionStoreBasics(unittest.TestCase):

    def setUp(self):
        self.store = SessionStore(max_sessions=5, trim_to=2)

    def test_get_unknown_session_returns_none(self):
        self.assertIsNone(self.store.get("nonexistent"))

    def test_save_and_get_roundtrip(self):
        msgs = [{"role": "user", "content": "hello"}]
        self.store.save("s1", msgs)
        result = self.store.get("s1")
        self.assertEqual(result, msgs)

    def test_get_returns_copy_not_reference(self):
        """Mutating the returned list must not corrupt the store."""
        msgs = [{"role": "user", "content": "hello"}]
        self.store.save("s1", msgs)
        copy = self.store.get("s1")
        copy.append({"role": "assistant", "content": "hi"})
        # Original in store must be unchanged.
        self.assertEqual(self.store.get("s1"), msgs)

    def test_save_overwrites_existing(self):
        self.store.save("s1", [{"role": "user", "content": "v1"}])
        self.store.save("s1", [{"role": "user", "content": "v2"}])
        self.assertEqual(self.store.get("s1")[0]["content"], "v2")

    def test_delete_removes_session(self):
        self.store.save("s1", [])
        self.store.delete("s1")
        self.assertIsNone(self.store.get("s1"))

    def test_delete_nonexistent_is_noop(self):
        """Should not raise for an unknown key."""
        self.store.delete("ghost")

    def test_len(self):
        self.store.save("a", [])
        self.store.save("b", [])
        self.assertEqual(len(self.store), 2)

    def test_contains(self):
        self.store.save("a", [])
        self.assertIn("a", self.store)
        self.assertNotIn("z", self.store)


class TestSessionStoreEviction(unittest.TestCase):

    def test_eviction_removes_lru_entries(self):
        """
        After filling the store past max_sessions, the *oldest* sessions
        (least-recently-used) must be evicted, not random ones.

        Setup: max_sessions=3, trim_to=2.
          save s1, s2, s3  →  store is full (3 == max_sessions, no eviction yet)
          get  s1           →  LRU order becomes: s2, s3, s1
          save s4           →  4 > 3, evict down to trim_to=2
                               evict_count = 4 - 2 = 2  →  drop s2 then s3
                               survivors: s1 (recently touched) + s4 (just added)
        """
        store = SessionStore(max_sessions=3, trim_to=2)

        store.save("s1", [])
        store.save("s2", [])
        store.save("s3", [])

        # Promote s1 to most-recently-used.
        store.get("s1")

        # Saving s4 pushes len to 4 > max_sessions=3 → evict to trim_to=2.
        store.save("s4", [])

        self.assertIsNone(store.get("s2"), "s2 should have been evicted (LRU)")
        self.assertIsNone(store.get("s3"), "s3 should have been evicted (LRU)")
        self.assertIsNotNone(store.get("s1"), "s1 should survive (was accessed)")
        self.assertIsNotNone(store.get("s4"), "s4 should survive (just added)")

    def test_store_never_exceeds_max_after_many_saves(self):
        store = SessionStore(max_sessions=5, trim_to=2)
        for i in range(50):
            store.save(f"session_{i}", [{"turn": i}])
        self.assertLessEqual(len(store), 5)


class TestSessionStoreThreadSafety(unittest.TestCase):

    def test_concurrent_saves_do_not_corrupt(self):
        """
        100 threads each saving to the same store must leave it consistent
        (no KeyError, no race condition on len).
        """
        store = SessionStore(max_sessions=20, trim_to=10)
        errors = []

        def worker(n: int):
            try:
                store.save(f"session_{n}", [{"turn": n}])
                store.get(f"session_{n}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        self.assertLessEqual(len(store), 20)


class TestSessionStoreConstructor(unittest.TestCase):

    def test_trim_to_must_be_less_than_max_sessions(self):
        with self.assertRaises(ValueError):
            SessionStore(max_sessions=5, trim_to=5)

    def test_trim_to_equal_raises(self):
        with self.assertRaises(ValueError):
            SessionStore(max_sessions=10, trim_to=10)

    def test_valid_construction(self):
        store = SessionStore(max_sessions=10, trim_to=9)
        self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
