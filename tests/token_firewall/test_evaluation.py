from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.evaluation import (
    build_evaluation_lab,
    pair_from_benchmark_records,
    summarize_paired_evaluation,
    write_evaluation_artifacts,
)
from tools.token_firewall.schema import canonical_sha256
from tests.token_firewall.test_benchmark import sealed_record


def seal(value: dict) -> dict:
    value["content_sha256"] = canonical_sha256(value)
    return value


def protocol() -> dict:
    return seal({
        "schema": "token-firewall/evaluation-protocol@0.1",
        "object_id": "eval_test_001",
        "revision": 1,
        "created_at": "2026-07-11T00:00:00+00:00",
        "content_sha256": "0" * 64,
        "experiment_id": "experiment-test-001",
        "control_arm": {"arm_id": "D", "route": ["Sol implementer", "Sol reviewer"]},
        "experiment_arm": {"arm_id": "A", "route": ["M3 implementer", "Terra verifier", "Sol reviewer"]},
        "primary_outcome": {
            "name": "task_success",
            "noninferiority_margin_percentage_points": 5,
            "critical_regressions_allowed": 0,
        },
        "cost_outcome": {"name": "cumulative_sol_tokens", "minimum_sol_savings_percent": 70},
        "sampling": {
            "minimum_pairs": 3,
            "bootstrap_samples": 200,
            "random_seed": 17,
            "risk_levels": ["low", "medium", "high"],
            "task_types": ["bugfix"],
        },
        "blinding": {
            "candidate_identity_hidden": True,
            "fresh_reviewer_session": True,
            "hidden_tests_after_model_stages": True,
        },
        "accounting": {"include_failures": True, "include_rework": True, "deduplicate_by": "session_id"},
        "reporting": {
            "confidence_level": 0.95,
            "charts": ["quality_token_pareto", "paired_quality", "risk_strata", "token_waterfall"],
        },
    })


def pairs() -> list[dict]:
    values = []
    for index, risk in enumerate(("low", "medium", "high"), start=1):
        values.append(seal({
            "schema": "token-firewall/evaluation-pair@0.1",
            "object_id": f"pair_object_{index}",
            "content_sha256": "0" * 64,
            "experiment_id": "experiment-test-001",
            "pair_id": f"pair-{index}",
            "task_id": f"T-{index:03d}",
            "risk": risk,
            "task_type": "bugfix",
            "task_content_sha256": f"{index:064x}",
            "provenance": {
                "normalizer_revision": "benchmark-to-pair@0.1",
                "campaign_mode": "single",
                "control_record_sha256": f"{index + 10:064x}",
                "experiment_record_sha256": [f"{index + 20:064x}"],
                "source_run_ids": [f"control-run-{index}", f"experiment-run-{index}"],
            },
            "control": {
                "arm_id": "D", "task_success": True, "quality_score": 92,
                "sol_tokens": 1000, "all_model_tokens": 1000, "elapsed_seconds": 100,
                "high_critical_findings": 0, "hidden_status": "pass", "review_verdict": "PASS",
                "usage_complete": True, "session_ids": [f"control-{index}"],
                "quality_score_source": "mechanical-gates@0.1",
            },
            "experiment": {
                "arm_id": "A", "task_success": True, "quality_score": 93,
                "sol_tokens": 200, "all_model_tokens": 1500, "elapsed_seconds": 130,
                "high_critical_findings": 0, "hidden_status": "pass", "review_verdict": "PASS",
                "usage_complete": True, "session_ids": [f"experiment-{index}"],
                "quality_score_source": "mechanical-gates@0.1",
            },
        }))
    return values


class PairedEvaluationTests(unittest.TestCase):
    def test_benchmark_records_are_normalized_with_provenance(self) -> None:
        pair = pair_from_benchmark_records(
            protocol(),
            sealed_record("D"),
            [sealed_record("A")],
            pair_id="pilot-001",
            risk="medium",
            task_type="bugfix",
        )
        self.assertEqual(pair["provenance"]["campaign_mode"], "single")
        self.assertEqual(pair["control"]["sol_tokens"], 1100)
        self.assertEqual(pair["experiment"]["sol_tokens"], 100)
        self.assertTrue(pair["experiment"]["task_success"])

    def test_terra_and_claude_records_require_matching_protocol_arms(self) -> None:
        for group in ("C", "E"):
            value = protocol()
            value["experiment_arm"]["arm_id"] = group
            seal(value)
            pair = pair_from_benchmark_records(
                value,
                sealed_record("D"),
                [sealed_record(group)],
                pair_id=f"pilot-{group.lower()}",
                risk="medium",
                task_type="bugfix",
            )
            self.assertEqual(pair["experiment"]["arm_id"], group)
        with self.assertRaisesRegex(ValueError, "protocol arms"):
            pair_from_benchmark_records(
                protocol(), sealed_record("D"), [sealed_record("C")],
                pair_id="wrong-arm", risk="medium", task_type="bugfix",
            )

    def test_rework_normalization_deduplicates_reused_sessions(self) -> None:
        control = sealed_record("D")
        initial = sealed_record("A")
        rework = sealed_record("B")
        rework["base_sha"] = initial["commit_range"]["head"]
        rework["commit_range"]["base"] = rework["base_sha"]
        rework["task_revision"] = 2
        rework["stages"]["verifier"]["role"] = "deputy"
        rework["stages"]["verifier"]["session_id"] = "deputy-B"
        rework["stages"]["verifier"]["model_requested"] = "gpt-5.6-terra"
        rework["stages"]["verifier"]["model_effective"] = "gpt-5.6-terra"
        rework["content_sha256"] = canonical_sha256(rework)
        repeated = copy.deepcopy(rework)
        repeated["run_id"] = "run_rework_repeat"
        repeated["task_revision"] = 3
        repeated["content_sha256"] = canonical_sha256(repeated)
        pair = pair_from_benchmark_records(
            protocol(), control, [initial, rework, repeated],
            pair_id="pilot-rework", risk="high", task_type="bugfix",
        )
        self.assertEqual(pair["provenance"]["campaign_mode"], "rework")
        self.assertEqual(len(pair["experiment"]["session_ids"]), 6)

    def test_failed_attempts_are_included_and_reused_sessions_are_deduplicated(self) -> None:
        failed = sealed_record("A")
        failed["run_id"] = "run_a_failed"
        failed["status"] = "VERIFIER_FAILED"
        failed["stages"]["reviewer"] = None
        failed["stages"]["verifier"]["session_id"] = "failed-verifier"
        failed["content_sha256"] = canonical_sha256(failed)
        final = sealed_record("A")
        pair = pair_from_benchmark_records(
            protocol(), sealed_record("D"), [final],
            failed_attempts=[failed], pair_id="with-failure", risk="low", task_type="bugfix",
        )
        self.assertEqual(pair["provenance"]["normalizer_revision"], "benchmark-to-pair@0.2")
        self.assertEqual(pair["provenance"]["failed_attempt_record_sha256"], [failed["content_sha256"]])
        self.assertIn("failed-verifier", pair["experiment"]["session_ids"])
        self.assertEqual(pair["experiment"]["all_model_tokens"], 1200)

    def test_failed_control_attempt_is_included_and_can_fail_usage_closed(self) -> None:
        failed = sealed_record("D")
        failed["run_id"] = "run_d_timeout"
        failed["status"] = "REVIEW_FAILED"
        failed["stages"]["reviewer"]["session_id"] = "timed-out-reviewer"
        failed["stages"]["reviewer"]["usage"]["complete"] = False
        failed["content_sha256"] = canonical_sha256(failed)
        pair = pair_from_benchmark_records(
            protocol(), sealed_record("D"), [sealed_record("A")],
            failed_control_attempts=[failed], pair_id="control-failure", risk="low", task_type="bugfix",
        )
        self.assertFalse(pair["control"]["usage_complete"])
        self.assertIn("timed-out-reviewer", pair["control"]["session_ids"])
        self.assertEqual(
            pair["provenance"]["failed_control_attempt_record_sha256"],
            [failed["content_sha256"]],
        )

    def test_normalizer_rejects_tampered_record_and_invalid_rework_chain(self) -> None:
        control = sealed_record("D")
        tampered = copy.deepcopy(control)
        tampered["elapsed_seconds"] += 1
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            pair_from_benchmark_records(
                protocol(), tampered, [sealed_record("A")],
                pair_id="tampered", risk="low", task_type="bugfix",
            )

        initial = sealed_record("A")
        rework = sealed_record("B")
        rework["base_sha"] = "f" * 40
        rework["content_sha256"] = canonical_sha256(rework)
        with self.assertRaisesRegex(ValueError, "chain is invalid"):
            pair_from_benchmark_records(
                protocol(), control, [initial, rework],
                pair_id="bad-chain", risk="low", task_type="bugfix",
            )

    def test_pass_requires_noninferiority_savings_and_complete_usage(self) -> None:
        summary = summarize_paired_evaluation(protocol(), pairs())
        self.assertEqual(summary["verdict"], "PASS")
        self.assertTrue(summary["quality"]["noninferior"])
        self.assertEqual(summary["cost"]["sol_savings_percent"], 80.0)

    def test_quality_regression_fails_even_when_tokens_are_saved(self) -> None:
        values = pairs()
        values[0]["experiment"]["task_success"] = False
        values[0]["experiment"]["high_critical_findings"] = 1
        seal(values[0])
        summary = summarize_paired_evaluation(protocol(), values)
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertFalse(summary["quality"]["noninferior"])

    def test_duplicate_session_marks_usage_incomplete(self) -> None:
        values = pairs()
        values[1]["experiment"]["session_ids"] = values[0]["experiment"]["session_ids"][:]
        seal(values[1])
        summary = summarize_paired_evaluation(protocol(), values)
        self.assertFalse(summary["usage_complete"])
        self.assertEqual(summary["verdict"], "FAIL")

    def test_report_writes_deterministic_svg_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = write_evaluation_artifacts(protocol(), pairs(), tmp)
            output = Path(tmp)
            self.assertTrue((output / "evaluation-summary.json").is_file())
            self.assertTrue((output / "evaluation-report.md").is_file())
            self.assertEqual(len(summary["artifacts"]["charts"]), 4)
            for name in summary["artifacts"]["charts"]:
                self.assertTrue((output / name).read_text(encoding="utf-8").startswith("<svg"))

    def test_lab_freezes_protocol_pairs_manifest_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lab"
            result = build_evaluation_lab(protocol(), pairs(), root, lab_id="test-lab-001")
            self.assertEqual(result["summary"]["verdict"], "PASS")
            self.assertTrue((root / "lab-manifest.json").is_file())
            self.assertEqual(len(list((root / "pairs").glob("*.json"))), 3)
            self.assertTrue((root / "report" / "evaluation-report.md").is_file())

    def test_lab_rejects_duplicate_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            duplicate = pairs()[0]
            with self.assertRaisesRegex(ValueError, "duplicate pair_id"):
                build_evaluation_lab(protocol(), [duplicate, duplicate], Path(tmp) / "lab", lab_id="duplicate")


if __name__ == "__main__":
    unittest.main()
