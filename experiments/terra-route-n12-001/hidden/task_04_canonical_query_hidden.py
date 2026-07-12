from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import canonical_query


class HiddenCanonicalQueryTests(unittest.TestCase):
    def test_sorts_encoded_values_and_preserves_empty_and_duplicates(self):
        params = iter([("x", "z"), ("x", "/"), ("empty", ""), ("x", "/")])
        self.assertEqual(canonical_query(params), "empty=&x=%2F&x=%2F&x=z")

    def test_encodes_unicode_by_utf8_and_rejects_surrogate(self):
        self.assertEqual(canonical_query([("é", "雪")]), "%C3%A9=%E9%9B%AA")
        with self.assertRaises((TypeError, ValueError, UnicodeError)):
            canonical_query([("bad", "\ud800")])


if __name__ == "__main__":
    unittest.main()
