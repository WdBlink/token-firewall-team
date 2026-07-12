from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import parse_retry_after


class HiddenRetryAfterTests(unittest.TestCase):
    def test_date_uses_utc_and_rounds_fractional_delay_up(self):
        now = datetime(2026, 7, 12, 1, 59, 58, 500000, tzinfo=timezone.utc)
        self.assertEqual(parse_retry_after("Sun, 12 Jul 2026 02:00:00 GMT", now=now), 2)

    def test_requires_aware_now_positive_integer_limit_and_ascii_ows(self):
        aware = datetime(2026, 7, 12, tzinfo=timezone.utc)
        with self.assertRaises((TypeError, ValueError)):
            parse_retry_after("1", now=datetime(2026, 7, 12))
        for limit in (0, True):
            with self.subTest(limit=limit), self.assertRaises((TypeError, ValueError)):
                parse_retry_after("1", now=aware, max_delay=limit)
        with self.assertRaises((TypeError, ValueError)):
            parse_retry_after("\u00a01\u00a0", now=aware)


if __name__ == "__main__":
    unittest.main()
