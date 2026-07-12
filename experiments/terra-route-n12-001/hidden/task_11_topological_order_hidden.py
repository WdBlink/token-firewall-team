from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import topological_order


class HiddenTopologicalOrderTests(unittest.TestCase):
    def test_stability_uses_dependency_and_node_input_order(self):
        graph = {"deploy": ["test", "build"], "build": [], "test": [], "docs": []}
        self.assertEqual(topological_order(graph), ["test", "build", "deploy", "docs"])

    def test_rejects_self_cycle_duplicate_dependency_and_non_string_nodes(self):
        for graph in ({"a": ["a"]}, {"a": [], "b": ["a", "a"]}, {1: []}, {"a": [1]}):
            with self.subTest(graph=graph), self.assertRaises((TypeError, ValueError)):
                topological_order(graph)


if __name__ == "__main__":
    unittest.main()
