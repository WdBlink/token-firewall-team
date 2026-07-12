from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.token_firewall.budget import gate_sol_budget, risk_budget
from tools.token_firewall.schema import SchemaRegistry
from tests.token_firewall.fixtures import seal, work_order_v02


ROOT = Path(__file__).resolve().parents[2]


def stage(session: str, tokens: int, *, role: str = "reviewer") -> dict:
    return {
        "role": role,
        "model_requested": "gpt-5.6-sol",
        "counts_as_sol": True,
        "session_id": session,
        "usage": {"total_tokens": tokens, "complete": True},
    }


class RiskTokenBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = json.loads(
            (ROOT / "evidence/policies/risk-token-budget-policy-0.1.json").read_text()
        )
        SchemaRegistry().validate(cls.policy)

    def test_risk_tiers_select_different_absolute_and_savings_budgets(self) -> None:
        low = risk_budget(self.policy, work_order_v02(risk="low"))
        high = risk_budget(self.policy, work_order_v02(risk="high"))
        self.assertLess(low["total_sol_max"], high["total_sol_max"])
        self.assertGreater(low["minimum_sol_savings_percent"], high["minimum_sol_savings_percent"])

    def test_budget_passes_and_deduplicates_same_session(self) -> None:
        order = work_order_v02(risk="medium")
        stages = [stage("review-1", 100000), stage("review-1", 100000)]
        result = gate_sol_budget(self.policy, order, stages, baseline_sol_tokens=705719, rework_rounds=1)
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.evidence["total_sol_tokens"], 100000)
        self.assertEqual(result.evidence["deduplicated_sol_sessions"], 1)

    def test_budget_fails_on_limit_savings_route_and_conflicting_session(self) -> None:
        order = work_order_v02(risk="low")
        order["risk"]["required_review"] = "sol-deep-review"
        seal(order)
        stages = [stage("same", 70000), stage("same", 71000)]
        result = gate_sol_budget(self.policy, order, stages, baseline_sol_tokens=100000, rework_rounds=2)
        codes = {finding.code for finding in result.findings}
        self.assertIn("BUDGET_REVIEW_ROUTE_MISMATCH", codes)
        self.assertIn("BUDGET_SESSION_CONFLICT", codes)
        self.assertIn("BUDGET_SOL_LIMIT_EXCEEDED", codes)
        self.assertIn("BUDGET_SAVINGS_MISSED", codes)
        self.assertIn("BUDGET_REWORK_EXCEEDED", codes)

    def test_policy_tamper_is_rejected(self) -> None:
        tampered = copy.deepcopy(self.policy)
        tampered["tiers"]["low"]["total_sol_max"] = 1
        with self.assertRaises(ValueError):
            SchemaRegistry().validate(tampered)


if __name__ == "__main__":
    unittest.main()
