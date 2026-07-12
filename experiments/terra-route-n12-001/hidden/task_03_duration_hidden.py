from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import parse_duration


class HiddenDurationTests(unittest.TestCase):
    def test_millisecond_unit_and_exact_limit(self):
        self.assertEqual(parse_duration("1ms"), 1)
        self.assertEqual(parse_duration("86400s"), 86_400_000)

    def test_rejects_unicode_leading_zero_and_limit_overflow(self):
        for value in ("١s", "01ms", "86400001ms", "1d", "1 ms", True):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                parse_duration(value)
        with self.assertRaises((TypeError, ValueError)):
            parse_duration("1s", max_milliseconds=True)


if __name__ == "__main__":
    unittest.main()
