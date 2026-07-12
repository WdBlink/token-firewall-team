from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import stable_unique


class HiddenStableUniqueTests(unittest.TestCase):
    def test_supports_dicts_and_does_not_consume_twice(self):
        values = ({"a": value} for value in (1, 1, 2))
        self.assertEqual(stable_unique(values), [{"a": 1}, {"a": 2}])

    def test_uses_python_equality_and_keeps_original_objects(self):
        first = [1]
        duplicate = [1]
        result = stable_unique([first, duplicate, True, 1, False, 0])
        self.assertIs(result[0], first)
        self.assertEqual(result, [[1], True, False])


if __name__ == "__main__":
    unittest.main()
