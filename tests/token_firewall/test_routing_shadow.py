from __future__ import annotations

import unittest

from tools.token_firewall.routing_shadow import (
    build_typesafe_request,
    attach_typesafe_requests,
    current_policy_route,
    route_from_typesafe,
    summarize_shadow,
    write_standard_experiment_report,
)


def task(**overrides):
    value = {
        "id": "T-1", "category": "bugfix", "request": "修复一个有确定性回归测试的解析错误。",
        "mutation": "repository", "scope_bounded": True, "deterministic_oracle": True,
        "semantic_boundary_defined": True, "risk_signals": [], "external_harness_requested": None,
        "current_task_shape": "routine", "expert_reference_route": "m3", "expert_reason": "bounded",
    }
    value.update(overrides)
    return value


def response(choice="bounded_implementation", confidence=0.9, ambiguity=0.1, oracle=0.9, bounded=0.9, risk=0.1):
    return {"answers": {
        "task_shape": {"type": "choice", "choice": choice, "probabilities": {choice: 0.9}, "confidence": confidence},
        "has_semantic_ambiguity": {"type": "noul", "noul": ambiguity},
        "has_sufficient_oracle": {"type": "noul", "noul": oracle},
        "is_safely_bounded": {"type": "noul", "noul": bounded},
        "has_high_impact_risk": {"type": "noul", "noul": risk},
    }}


class RoutingShadowTests(unittest.TestCase):
    def test_current_policy_routes_three_native_tiers(self):
        self.assertEqual(current_policy_route(task()), "m3")
        self.assertEqual(current_policy_route(task(mutation="none", current_task_shape="read-heavy")), "luna")
        self.assertEqual(current_policy_route(task(risk_signals=["security"])), "sol")

    def test_typesafe_route_is_conservative(self):
        self.assertEqual(route_from_typesafe(task(), response()), "m3")
        self.assertEqual(route_from_typesafe(task(), response(confidence=0.3)), "sol")
        self.assertEqual(route_from_typesafe(task(), response(risk=0.5)), "sol")

    def test_prompt_does_not_leak_reference_route(self):
        encoded = str(build_typesafe_request(task(), model="jev-1.13.0"))
        self.assertNotIn("expert_reference_route", encoded)
        self.assertNotIn("current_task_shape", encoded)

    def test_summary_counts_route_agreement(self):
        rows = [{
            "task_id": "T-1", "current_route": "m3", "jev_route": "sol",
            "expert_reference_route": "m3", "usage": {"input_tokens": 10, "output_tokens": 2},
        }]
        summary = summarize_shadow(rows)
        self.assertEqual(summary["current_vs_expert"]["matches"], 1)
        self.assertEqual(summary["jev_vs_expert"]["matches"], 0)
        self.assertEqual(summary["usage"]["input_tokens"], 10)

    def test_archived_records_can_reconstruct_exact_requests(self):
        rows = [{
            "task_id": "T-1", "category": "bugfix", "current_route": "m3", "jev_route": "m3",
            "expert_reference_route": "m3", "expert_reason": "bounded", "model": "jev-1.13.0",
            "answers": response()["answers"], "usage": {"input_tokens": 10, "output_tokens": 2}, "latency_ms": 5,
        }]
        attach_typesafe_requests([task()], rows)
        self.assertEqual(rows[0]["typesafe_request"]["state"]["request"], task()["request"])

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.md"
            write_standard_experiment_report(rows, report)
            text = report.read_text(encoding="utf-8")
            self.assertIn("逐任务完整 Jev 输入与输出", text)
            self.assertIn('"questions"', text)


if __name__ == "__main__":
    unittest.main()
