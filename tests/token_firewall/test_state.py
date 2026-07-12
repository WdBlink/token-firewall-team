from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.state import Conductor, ReworkMonitor, StateTransitionError

from tests.token_firewall.fixtures import event


def drive_to_verified(conductor: Conductor) -> None:
    evidence = conductor.run_dir / "evidence" / "object.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"")
    sequence = [
        event("evt_001", "mission.approved"),
        event("evt_002", "mission.decomposing"),
        event("evt_003", "work.ready", task_id="T-001"),
        event("evt_004", "mission.running"),
        event("evt_005", "work.started", task_id="T-001"),
        event("evt_006", "work.delivered", task_id="T-001", evidence=True),
        event("evt_007", "test.started", task_id="T-001"),
        event("evt_008", "verification.started", task_id="T-001"),
        event("evt_009", "work.verified", task_id="T-001", evidence=True),
    ]
    for item in sequence:
        conductor.emit(item)


class StateMachineTests(unittest.TestCase):
    def test_full_authoritative_flow_and_event_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor = Conductor("msn_test", tmp)
            drive_to_verified(conductor)
            conductor.emit(event("evt_010", "mission.integrating"))
            conductor.emit(event("evt_011", "mission.reviewing"))
            accepted = event("evt_012", "work.accepted", task_id="T-001", evidence=True)
            self.assertTrue(conductor.emit(accepted))
            self.assertFalse(conductor.emit(accepted))
            conductor.emit(event("evt_013", "mission.passed", evidence=True))

            self.assertEqual(conductor.state["mission_state"], "PASSED")
            self.assertEqual(conductor.state["tasks"]["T-001"]["state"], "ACCEPTED")
            lines = Path(tmp, "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 13)
            snapshot = json.loads(Path(tmp, "mission-state.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot, conductor.state)
            self.assertFalse(list(Path(tmp).glob("*.tmp")))

    def test_agent_cannot_accept_its_own_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor = Conductor("msn_test", tmp)
            drive_to_verified(conductor)
            conductor.emit(event("evt_010", "mission.integrating"))
            conductor.emit(event("evt_011", "mission.reviewing"))
            forged = event(
                "evt_012",
                "work.accepted",
                role="implementer",
                task_id="T-001",
                evidence=True,
            )
            with self.assertRaises(StateTransitionError):
                conductor.emit(forged)
            self.assertIsNone(conductor.store.find("evt_012"))
            self.assertEqual(conductor.state["tasks"]["T-001"]["state"], "VERIFIED")

    def test_illegal_transition_is_rejected_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor = Conductor("msn_test", tmp)
            with self.assertRaises(StateTransitionError):
                conductor.emit(event("evt_001", "mission.running"))
            self.assertIsNone(conductor.store.find("evt_001"))

    def test_crash_after_event_append_recovers_from_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor = Conductor("msn_test", tmp)
            conductor.emit(event("evt_001", "mission.approved"))
            stale_snapshot = json.loads(Path(tmp, "mission-state.json").read_text(encoding="utf-8"))
            conductor.store.append(event("evt_002", "mission.decomposing"))
            self.assertEqual(stale_snapshot["mission_state"], "APPROVED")

            recovered = Conductor("msn_test", tmp)
            self.assertEqual(recovered.state["mission_state"], "DECOMPOSING")
            refreshed = json.loads(Path(tmp, "mission-state.json").read_text(encoding="utf-8"))
            self.assertEqual(refreshed["last_event_id"], "evt_002")

    def test_event_id_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor = Conductor("msn_test", tmp)
            original = event("evt_001", "trace.started", role="implementer")
            conductor.emit(original)
            collision = event("evt_001", "trace.finished", role="implementer")
            with self.assertRaises(StateTransitionError):
                conductor.emit(collision)

    def test_event_payload_hash_is_verified_and_rechecked_on_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conductor = Conductor("msn_test", tmp)
            evidence = Path(tmp, "evidence", "object.json")
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(b"")
            conductor.emit(event("evt_001", "trace.evidence", role="implementer", evidence=True))
            evidence.write_text("tampered", encoding="utf-8")
            with self.assertRaises(StateTransitionError):
                Conductor("msn_test", tmp)


class ReworkMonitorTests(unittest.TestCase):
    def test_two_rework_rounds_then_retry_budget_exhaustion(self) -> None:
        monitor = ReworkMonitor(max_rounds=2)
        first = monitor.record_failure("T-001", finding_ids=["F-1"], fix_signature="A", diff_lines=10)
        second = monitor.record_failure("T-001", finding_ids=["F-2"], fix_signature="B", diff_lines=8)
        third = monitor.record_failure("T-001", finding_ids=["F-3"], fix_signature="C", diff_lines=7)
        self.assertEqual([first.state, second.state, third.state], ["REWORK", "REWORK", "NEEDS_REPLAN"])
        self.assertEqual(third.reason, "retry_budget_exhausted")

    def test_repeated_finding_and_oscillation_trigger_replan(self) -> None:
        repeated = ReworkMonitor(max_rounds=5)
        repeated.record_failure("T-001", finding_ids=["F-1"], fix_signature="A", diff_lines=10)
        decision = repeated.record_failure("T-001", finding_ids=["F-1"], fix_signature="B", diff_lines=9)
        self.assertEqual((decision.state, decision.reason), ("NEEDS_REPLAN", "repeated_finding"))

        oscillating = ReworkMonitor(max_rounds=5)
        oscillating.record_failure("T-002", finding_ids=["F-1"], fix_signature="A", diff_lines=10)
        oscillating.record_failure("T-002", finding_ids=["F-2"], fix_signature="B", diff_lines=9)
        decision = oscillating.record_failure("T-002", finding_ids=["F-3"], fix_signature="A", diff_lines=8)
        self.assertEqual((decision.state, decision.reason), ("NEEDS_REPLAN", "fix_oscillation"))

    def test_continuous_diff_growth_triggers_replan(self) -> None:
        monitor = ReworkMonitor(max_rounds=5)
        monitor.record_failure("T-001", finding_ids=["F-1"], fix_signature="A", diff_lines=10)
        monitor.record_failure("T-001", finding_ids=["F-2"], fix_signature="B", diff_lines=20)
        decision = monitor.record_failure("T-001", finding_ids=["F-3"], fix_signature="C", diff_lines=30)
        self.assertEqual((decision.state, decision.reason), ("NEEDS_REPLAN", "diff_growth"))


if __name__ == "__main__":
    unittest.main()
