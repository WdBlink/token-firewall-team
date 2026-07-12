from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.token_firewall.schema import SchemaRegistry, SchemaValidationError

from tests.token_firewall.fixtures import (
    SHA,
    delivery_manifest,
    event,
    header,
    mission_contract,
    runtime_worker_report,
    seal,
    task_review_packet,
    verdict,
    work_order,
    work_order_v02,
)


class ProtocolSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def assert_invalid(self, value: dict) -> SchemaValidationError:
        with self.assertRaises(SchemaValidationError) as caught:
            self.registry.validate(value)
        return caught.exception

    def test_mission_contract_positive_and_negative_examples(self) -> None:
        value = mission_contract()
        self.registry.validate(value)

        missing_evidence = copy.deepcopy(value)
        del missing_evidence["success_outcomes"][0]["evidence"]
        error = self.assert_invalid(missing_evidence)
        self.assertTrue(any(issue.keyword == "required" for issue in error.issues))

        unknown_acceptance = copy.deepcopy(value)
        unknown_acceptance["overall_acceptance"].append("OUT-999")
        error = self.assert_invalid(unknown_acceptance)
        self.assertTrue(any(issue.keyword == "reference" for issue in error.issues))

        tampered = mission_contract()
        tampered["goal"] += "（被验证后篡改）"
        error = self.assert_invalid(tampered)
        self.assertTrue(any(issue.keyword == "contentHash" for issue in error.issues))

    def test_work_order_positive_and_negative_examples(self) -> None:
        value = work_order()
        self.registry.validate(value)

        no_validator = copy.deepcopy(value)
        del no_validator["acceptance_specs"][0]["validator"]
        self.assert_invalid(no_validator)

        duplicate_specs = copy.deepcopy(value)
        duplicate_specs["acceptance_specs"].append(copy.deepcopy(duplicate_specs["acceptance_specs"][0]))
        error = self.assert_invalid(duplicate_specs)
        self.assertTrue(any(issue.keyword == "unique" for issue in error.issues))

    def test_work_order_v02_requires_cases_and_real_semantic_boundary(self) -> None:
        value = work_order_v02()
        self.registry.validate(value)

        missing_negative = copy.deepcopy(value)
        missing_negative["acceptance_specs"][0]["negative_cases"] = []
        seal(missing_negative)
        self.assert_invalid(missing_negative)

        fake_boundary = copy.deepcopy(value)
        boundary = fake_boundary["acceptance_specs"][0]["semantic_boundaries"][0]
        boundary["outside"] = boundary["inside"]
        seal(fake_boundary)
        error = self.assert_invalid(fake_boundary)
        self.assertTrue(any(issue.keyword == "semanticBoundary" for issue in error.issues))

    def test_delivery_manifest_positive_and_negative_examples(self) -> None:
        value = delivery_manifest()
        self.registry.validate(value)

        forged_proposal = copy.deepcopy(value)
        forged_proposal["worker_proposal"] = "VERIFIED"
        self.assert_invalid(forged_proposal)

        same_commit = copy.deepcopy(value)
        same_commit["head_commit"] = same_commit["base_commit"]
        error = self.assert_invalid(same_commit)
        self.assertTrue(any(issue.keyword == "commitRange" for issue in error.issues))

    def test_task_and_mission_review_packet_branches(self) -> None:
        task_packet = task_review_packet()
        self.registry.validate(task_packet)

        mission_packet = copy.deepcopy(task_packet)
        mission_packet["object_id"] = "rp_mission_r1"
        mission_packet["scope"] = "mission"
        mission_packet.pop("task_id")
        mission_packet.pop("objective")
        mission_packet.pop("verifier_findings")
        mission_packet["integration_commit"] = "c" * 40
        mission_packet["included_tasks"] = [
            {
                "task_id": "T-001",
                "delivery_manifest_ref": {"path": "delivery.json", "sha256": SHA, "bytes": 0},
            }
        ]
        mission_packet["full_regression"] = {
            "status": "pass",
            "evidence_ref": {"path": "regression.json", "sha256": SHA, "bytes": 0},
        }
        mission_packet["unresolved_risks"] = []
        seal(mission_packet)
        self.registry.validate(mission_packet)

        missing_regression = copy.deepcopy(mission_packet)
        del missing_regression["full_regression"]
        self.assert_invalid(missing_regression)

    def test_review_verdict_semantics(self) -> None:
        self.registry.validate(verdict())

        unsafe_pass = verdict()
        unsafe_pass["findings"] = [
            {
                "finding_id": "F-001",
                "severity": "critical",
                "spec_id": "SPEC-001-01",
                "file": "src/app.txt",
                "line": 1,
                "issue": "关键不变量被破坏",
                "required_fix": "恢复不变量",
                "evidence": "patch.diff#L1",
            }
        ]
        error = self.assert_invalid(unsafe_pass)
        self.assertTrue(any(issue.keyword == "verdict" for issue in error.issues))

        empty_rework = verdict("REWORK")
        self.assert_invalid(empty_rework)

        escalation = verdict("ESCALATE")
        escalation["escalation_reason"] = "需要用户批准外部写入"
        self.registry.validate(escalation)

    def test_event_evidence_pair_and_datetime(self) -> None:
        self.registry.validate(event("evt_001", "trace.started", role="implementer"))

        incomplete = event("evt_002", "work.delivery.proposed", role="implementer", task_id="T-001")
        incomplete["payload_ref"] = "delivery.json"
        error = self.assert_invalid(incomplete)
        self.assertTrue(any(issue.keyword == "evidenceRef" for issue in error.issues))

        no_timezone = event("evt_003", "trace.started", role="implementer")
        no_timezone["at"] = "2026-07-10T16:00:00"
        self.assert_invalid(no_timezone)

    def test_runtime_worker_report_authority_and_blockers(self) -> None:
        self.registry.validate(runtime_worker_report())
        self.registry.validate(runtime_worker_report(status="CHANGES_READY"))
        self.registry.validate(runtime_worker_report(status="NEEDS_REPLAN"))

        invalid = runtime_worker_report(status="BLOCKED")
        invalid["blockers"] = []
        self.assert_invalid(invalid)

        invalid_range = runtime_worker_report()
        invalid_range["context_slices"][0].update({"start": 20, "end": 10})
        error = self.assert_invalid(invalid_range)
        self.assertTrue(any(issue.keyword == "range" for issue in error.issues))

    def test_frozen_evaluation_and_observability_policies(self) -> None:
        root = Path(__file__).resolve().parents[2]
        design = root / "evidence" / "policies"
        evaluation = json.loads((design / "evaluation-protocol-0.1.json").read_text(encoding="utf-8"))
        observability = json.loads(
            (design / "external-observability-policy-0.1.json").read_text(encoding="utf-8")
        )
        self.registry.validate(evaluation)
        self.registry.validate(observability)

        unsafe = copy.deepcopy(observability)
        unsafe["privacy"]["record_chain_of_thought"] = True
        seal(unsafe)
        error = self.assert_invalid(unsafe)
        self.assertTrue(any(issue.keyword == "privacy" for issue in error.issues))

        unblinded = copy.deepcopy(evaluation)
        unblinded["blinding"]["candidate_identity_hidden"] = False
        seal(unblinded)
        error = self.assert_invalid(unblinded)
        self.assertTrue(any(issue.keyword == "experimentDesign" for issue in error.issues))


    def test_unknown_schema_is_rejected(self) -> None:
        value = {**header("unknown", "mc_test"), "schema": "token-firewall/unknown@0.1"}
        self.assert_invalid(value)


if __name__ == "__main__":
    unittest.main()
