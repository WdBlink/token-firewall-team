from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from src.tasks import (
    canonical_query,
    collect_pages,
    deep_merge,
    merge_patch,
    parse_duration,
    parse_retry_after,
    read_through_cache,
    safe_join,
    stable_unique,
    topological_order,
)


class ParseDurationTests(unittest.TestCase):
    def test_positive_units_and_bound(self):
        self.assertEqual(parse_duration("250ms"), 250)
        self.assertEqual(parse_duration("2s"), 2_000)
        self.assertEqual(parse_duration("3m"), 180_000)
        self.assertEqual(parse_duration("1h"), 3_600_000)

    def test_rejects_ambiguous_syntax_and_overflow(self):
        for value in ("", " 2s", "+2s", "02s", "2.0s", "２s", "0s"):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                parse_duration(value)
        with self.assertRaises(ValueError):
            parse_duration("25h")


class CanonicalQueryTests(unittest.TestCase):
    def test_rfc3986_encoding_sort_and_duplicates(self):
        params = [("b", "two words"), ("a", "~"), ("a", "/")]
        self.assertEqual(canonical_query(params), "a=%2F&a=~&b=two%20words")
        self.assertEqual(canonical_query([("q", "café")]), "q=caf%C3%A9")

    def test_rejects_non_string_or_malformed_pairs(self):
        for params in ([('a', 1)], [("a",)], ["ab"], None):
            with self.subTest(params=params), self.assertRaises((TypeError, ValueError)):
                canonical_query(params)


class StableUniqueTests(unittest.TestCase):
    def test_preserves_first_occurrence_and_supports_unhashable_values(self):
        self.assertEqual(stable_unique(["b", "a", "b", "c", "a"]), ["b", "a", "c"])
        self.assertEqual(stable_unique([[1], [1], [2]]), [[1], [2]])

    def test_iterable_boundary(self):
        self.assertEqual(stable_unique(iter([1, 2, 1])), [1, 2])
        with self.assertRaises(TypeError):
            stable_unique(None)


class DeepMergeTests(unittest.TestCase):
    def test_recursive_merge_and_list_replacement(self):
        base = {"db": {"host": "a", "ports": [1, 2]}, "debug": False}
        override = {"db": {"host": "b", "ports": [3]}}
        self.assertEqual(deep_merge(base, override), {"db": {"host": "b", "ports": [3]}, "debug": False})

    def test_does_not_mutate_or_alias_inputs(self):
        base = {"nested": {"a": [1]}}
        override = {"nested": {"b": [2]}}
        result = deep_merge(base, override)
        result["nested"]["a"].append(9)
        result["nested"]["b"].append(9)
        self.assertEqual(base, {"nested": {"a": [1]}})
        self.assertEqual(override, {"nested": {"b": [2]}})
        with self.assertRaises(TypeError):
            deep_merge([], {})


class CollectPagesTests(unittest.TestCase):
    def test_collects_all_pages_in_order(self):
        pages = {
            None: {"items": [1, 2], "next_cursor": "a"},
            "a": {"items": [3], "next_cursor": "b"},
            "b": {"items": [], "next_cursor": None},
        }
        calls = []
        self.assertEqual(collect_pages(lambda cursor: calls.append(cursor) or pages[cursor]), [1, 2, 3])
        self.assertEqual(calls, [None, "a", "b"])

    def test_rejects_cycles_malformed_pages_and_limit_overrun(self):
        cyclic = {None: {"items": [], "next_cursor": "a"}, "a": {"items": [], "next_cursor": "a"}}
        with self.assertRaises(ValueError):
            collect_pages(lambda cursor: cyclic[cursor])
        with self.assertRaises(ValueError):
            collect_pages(lambda cursor: {"items": [], "next_cursor": "next"}, max_pages=1)
        with self.assertRaises((TypeError, ValueError)):
            collect_pages(lambda cursor: {"items": "not-a-list", "next_cursor": None})


class RetryAfterTests(unittest.TestCase):
    def test_seconds_date_and_clamp(self):
        now = datetime(2026, 7, 12, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_retry_after(" 120\t", now=now), 120)
        self.assertEqual(parse_retry_after("Sun, 12 Jul 2026 00:02:00 GMT", now=now), 120)
        self.assertEqual(parse_retry_after("9999", now=now, max_delay=300), 300)

    def test_rejects_invalid_values_and_clamps_past_date(self):
        now = datetime(2026, 7, 12, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_retry_after("Sat, 11 Jul 2026 23:59:59 GMT", now=now), 0)
        for value in ("-1", "+1", "1.5", "tomorrow", "１"):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                parse_retry_after(value, now=now)


class SafeJoinTests(unittest.TestCase):
    def test_allows_descendants_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "base"
            base.mkdir()
            self.assertEqual(safe_join(base, "a/file.txt"), (base / "a/file.txt").resolve())
            for value in ("../secret", "/tmp/secret", "a/../../secret", ""):
                with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                    safe_join(base, value)

    def test_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base"
            outside = root / "outside"
            base.mkdir()
            outside.mkdir()
            (base / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                safe_join(base, "link/secret.txt")


class MergePatchTests(unittest.TestCase):
    def test_rfc7396_object_merge_delete_and_replace(self):
        target = {"a": "b", "c": {"d": "e", "f": "g"}}
        patch = {"a": "z", "c": {"f": None, "x": 1}}
        self.assertEqual(merge_patch(target, patch), {"a": "z", "c": {"d": "e", "x": 1}})
        self.assertEqual(merge_patch({"a": 1}, [1, 2]), [1, 2])

    def test_no_input_aliasing(self):
        target = {"a": {"x": [1]}}
        patch = {"b": [2]}
        result = merge_patch(target, patch)
        result["a"]["x"].append(9)
        result["b"].append(9)
        self.assertEqual(target, {"a": {"x": [1]}})
        self.assertEqual(patch, {"b": [2]})


class TopologicalOrderTests(unittest.TestCase):
    def test_dependencies_precede_dependents_with_stable_ties(self):
        graph = {"build": ["lint", "test"], "lint": [], "test": ["compile"], "compile": []}
        self.assertEqual(topological_order(graph), ["lint", "compile", "test", "build"])
        self.assertEqual(topological_order({"b": [], "a": []}), ["b", "a"])

    def test_rejects_cycles_missing_nodes_and_bad_shapes(self):
        for graph in ({"a": ["b"], "b": ["a"]}, {"a": ["missing"]}, {"a": "b"}):
            with self.subTest(graph=graph), self.assertRaises((TypeError, ValueError)):
                topological_order(graph)


class ReadThroughCacheTests(unittest.TestCase):
    def test_fresh_hit_and_expired_reload(self):
        cache = {"fresh": ("old", 11), "expired": ("old", 10)}
        calls = []
        self.assertEqual(read_through_cache("fresh", now=10, cache=cache, loader=lambda: calls.append(1)), "old")
        self.assertEqual(calls, [])
        self.assertEqual(
            read_through_cache("expired", now=10, cache=cache, loader=lambda: ("new", 5)),
            "new",
        )
        self.assertEqual(cache["expired"], ("new", 15))

    def test_failed_or_invalid_load_is_atomic(self):
        cache = {"keep": ("value", 20)}
        before = dict(cache)
        with self.assertRaises(RuntimeError):
            read_through_cache("new", now=10, cache=cache, loader=lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(cache, before)
        for loaded in (("x", 0), ("x", True), "bad"):
            with self.subTest(loaded=loaded), self.assertRaises((TypeError, ValueError)):
                read_through_cache("new", now=10, cache=cache, loader=lambda loaded=loaded: loaded)
        self.assertEqual(cache, before)


if __name__ == "__main__":
    unittest.main()
