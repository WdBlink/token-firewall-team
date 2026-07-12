from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.observability import ExternalRunLedger
from tools.token_firewall.state import Conductor, StateTransitionError
from tests.token_firewall.fixtures import event


class FaultInjectionTests(unittest.TestCase):
    def test_truncated_authoritative_jsonl_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conductor = Conductor("msn_test", root)
            conductor.emit(event("evt_001", "mission.approved"))
            with (root / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"schema":"truncated"')
            with self.assertRaisesRegex(StateTransitionError, "corrupt events.jsonl"):
                Conductor("msn_test", root)

    def test_deleted_sqlite_index_is_rebuilt_from_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = ExternalRunLedger(
                root, run_id="run-fi", mission_id="msn-fi", task_id="T-FI",
                stage="worker", runtime="claude-code", model="sonnet",
            )
            ledger.append(ledger.next_event("run.dispatched", source="broker", summary="sent"))
            ledger.database_path.unlink()
            recovered = ExternalRunLedger(root)
            self.assertEqual(recovered.state["status"], "DISPATCHED")
            self.assertTrue(recovered.database_path.is_file())

    def test_conflicting_duplicate_event_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conductor = Conductor("msn_test", root)
            original = event("evt_collision", "mission.approved")
            conductor.emit(original)
            conflicting = json.loads(json.dumps(original))
            conflicting["kind"] = "mission.blocked"
            with self.assertRaisesRegex(StateTransitionError, "collision"):
                conductor.emit(conflicting)


if __name__ == "__main__":
    unittest.main()
