import unittest

from src.batching import batch_items


class BatchItemsTests(unittest.TestCase):
    def test_splits_sequence_and_keeps_short_final_batch(self):
        self.assertEqual(batch_items([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(batch_items([], 3), [])

    def test_supports_one_shot_iterables(self):
        self.assertEqual(batch_items((value for value in range(4)), 3), [[0, 1, 2], [3]])

    def test_rejects_invalid_size_and_non_iterable(self):
        for size in (0, -1, True, 1.5):
            with self.subTest(size=size), self.assertRaises((TypeError, ValueError)):
                batch_items([1], size)
        with self.assertRaises(TypeError):
            batch_items(None, 2)


if __name__ == "__main__":
    unittest.main()
