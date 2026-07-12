from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import read_through_cache


class HiddenReadThroughCacheTests(unittest.TestCase):
    def test_expiration_boundary_and_key_isolation(self):
        cache = {"a": (1, 5), "b": (2, 6)}
        self.assertEqual(read_through_cache("a", now=5, cache=cache, loader=lambda: (3, 2)), 3)
        self.assertEqual(cache, {"a": (3, 7), "b": (2, 6)})

    def test_malformed_loader_result_never_partially_writes(self):
        for loaded in (None, ("x",), ("x", -1), ("x", 1.5)):
            cache = {"keep": ("v", 10)}
            before = dict(cache)
            with self.subTest(loaded=loaded), self.assertRaises((TypeError, ValueError)):
                read_through_cache("new", now=1, cache=cache, loader=lambda loaded=loaded: loaded)
            self.assertEqual(cache, before)


if __name__ == "__main__":
    unittest.main()
