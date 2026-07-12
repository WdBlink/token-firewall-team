from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import deep_merge


class HiddenDeepMergeTests(unittest.TestCase):
    def test_replaces_scalar_mapping_boundary(self):
        self.assertEqual(deep_merge({"x": {"a": 1}}, {"x": 3}), {"x": 3})
        self.assertEqual(deep_merge({"x": 3}, {"x": {"a": 1}}), {"x": {"a": 1}})

    def test_deep_copies_unmodified_and_override_branches(self):
        base = {"keep": {"items": [{"x": 1}]}}
        override = {"new": {"items": [{"y": 2}]}}
        result = deep_merge(base, override)
        result["keep"]["items"][0]["x"] = 9
        result["new"]["items"][0]["y"] = 9
        self.assertEqual(base["keep"]["items"][0]["x"], 1)
        self.assertEqual(override["new"]["items"][0]["y"], 2)


if __name__ == "__main__":
    unittest.main()
