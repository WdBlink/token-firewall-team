from __future__ import annotations

import copy
import unittest

from tools.token_firewall.gates import check_changed_paths, validate_work_order_graph

from tests.token_firewall.fixtures import work_order


def codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


class DelegationGateTests(unittest.TestCase):
    def test_dag_accepts_serialized_shared_path(self) -> None:
        first = work_order("T-001", allowed_paths=["src/auth/**"])
        second = work_order("T-002", dependencies=["T-001"], allowed_paths=["src/auth/**"])
        result = validate_work_order_graph([first, second])
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.evidence["topological_order"], ["T-001", "T-002"])

    def test_dag_rejects_cycle_and_missing_dependency(self) -> None:
        first = work_order("T-001", dependencies=["T-002"], allowed_paths=["src/a/**"])
        second = work_order("T-002", dependencies=["T-001"], allowed_paths=["src/b/**"])
        cycle = validate_work_order_graph([first, second])
        self.assertIn("DAG_CYCLE", codes(cycle))

        missing = validate_work_order_graph([work_order("T-003", dependencies=["T-999"])])
        self.assertIn("DAG_DEPENDENCY_MISSING", codes(missing))

    def test_dag_rejects_parallel_write_conflict(self) -> None:
        first = work_order("T-001", allowed_paths=["src/auth/**"])
        second = work_order("T-002", allowed_paths=["src/auth/token/**"])
        result = validate_work_order_graph([first, second])
        self.assertIn("DAG_PARALLEL_WRITE_CONFLICT", codes(result))

    def test_work_order_rejects_overlapping_allow_and_forbid(self) -> None:
        value = work_order(allowed_paths=["src/**"])
        value["forbidden_paths"] = ["src/secrets/**"]
        result = validate_work_order_graph([value])
        self.assertIn("PATH_POLICY_OVERLAP", codes(result))

    def test_path_gate_enforces_forbidden_scope_and_limits(self) -> None:
        value = work_order(allowed_paths=["src/**"])
        value["forbidden_paths"] = ["src/secrets/**"]
        value["limits"]["max_changed_files"] = 1
        value["limits"]["max_diff_lines"] = 10
        result = check_changed_paths(
            value,
            ["src/app.py", "src/secrets/key.py", "tests/test_app.py"],
            diff_lines=42,
        )
        self.assertEqual(
            codes(result),
            {"PATH_FORBIDDEN", "PATH_NOT_ALLOWED", "DIFF_FILE_LIMIT", "DIFF_LINE_LIMIT"},
        )

    def test_path_gate_rejects_traversal(self) -> None:
        result = check_changed_paths(work_order(), ["../outside.py"], diff_lines=1)
        self.assertIn("PATH_INVALID", codes(result))


if __name__ == "__main__":
    unittest.main()
