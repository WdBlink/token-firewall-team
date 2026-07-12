from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import merge_patch


class HiddenMergePatchTests(unittest.TestCase):
    def test_non_object_target_is_empty_object_for_object_patch(self):
        self.assertEqual(merge_patch([1, 2], {"a": 1, "gone": None}), {"a": 1})
        self.assertEqual(merge_patch(None, {"a": {"b": 2}}), {"a": {"b": 2}})

    def test_nested_null_deletes_without_creating_missing_member(self):
        target = {"a": {"keep": 1, "drop": 2}}
        patch = {"a": {"drop": None, "missing": None}}
        self.assertEqual(merge_patch(target, patch), {"a": {"keep": 1}})


if __name__ == "__main__":
    unittest.main()
