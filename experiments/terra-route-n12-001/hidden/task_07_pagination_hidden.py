from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import collect_pages


class HiddenPaginationTests(unittest.TestCase):
    def test_rejects_empty_or_non_string_cursor(self):
        for cursor in ("", 1, False):
            with self.subTest(cursor=cursor), self.assertRaises((TypeError, ValueError)):
                collect_pages(lambda _: {"items": [], "next_cursor": cursor})

    def test_exact_page_limit_can_finish(self):
        pages = {None: {"items": [1], "next_cursor": "a"}, "a": {"items": [2], "next_cursor": None}}
        self.assertEqual(collect_pages(lambda cursor: pages[cursor], max_pages=2), [1, 2])
        for limit in (0, True):
            with self.subTest(limit=limit), self.assertRaises((TypeError, ValueError)):
                collect_pages(lambda _: {"items": [], "next_cursor": None}, max_pages=limit)


if __name__ == "__main__":
    unittest.main()
