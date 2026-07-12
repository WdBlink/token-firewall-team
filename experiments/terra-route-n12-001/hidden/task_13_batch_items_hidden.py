from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.batching import batch_items


class HiddenBatchItemsTests(unittest.TestCase):
    def test_size_larger_than_input_and_exact_boundary(self):
        self.assertEqual(batch_items(iter([1, 2]), 5), [[1, 2]])
        self.assertEqual(batch_items(iter([1, 2, 3, 4]), 2), [[1, 2], [3, 4]])

    def test_consumes_iterable_once_without_empty_tail(self):
        seen = []

        def values():
            for item in range(3):
                seen.append(item)
                yield item

        self.assertEqual(batch_items(values(), 1), [[0], [1], [2]])
        self.assertEqual(seen, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
