from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from tools.token_firewall.observability import (
    ExternalRunLedger,
    ExternalRunObserver,
    ExternalRunStateError,
    format_status_card,
    project_status,
)
from tools.token_firewall.runtime import RuntimeResult, RuntimeStatus


USAGE = {
    "input_tokens": 100,
    "output_tokens": 25,
    "reasoning_tokens": 5,
    "cache_read_tokens": 10,
    "cache_write_tokens": 0,
    "total_tokens": 130,
    "native_total_tokens": 140,
    "source": "fixture",
    "complete": True,
}


class ExternalObservabilityTests(unittest.TestCase):
    def test_observer_records_delivery_and_rebuilds_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "observability" / "T-001-worker"
            payload = Path(tmp) / "worker-report.json"
            payload.write_text('{"status":"DELIVERED"}', encoding="utf-8")
            observer = ExternalRunObserver.create(
                root,
                run_id="run-001",
                mission_id="msn-001",
                task_id="T-001",
                stage="worker",
                runtime="minimax",
                model="MiniMax-M3",
            )
            observer.trace("runtime.started", {"session_id": "mavis-001"})
            observer.trace("runtime.polled", {"session_id": "mavis-001", "status": "running"})
            observer.complete(
                RuntimeResult(
                    "minimax",
                    RuntimeStatus.SUCCEEDED,
                    "mavis-001",
                    {"status": "DELIVERED"},
                    0,
                    usage=USAGE,
                ),
                payload=payload,
                delivery={"commit": "a" * 40, "changed_files": 2, "additions": 8, "deletions": 1},
            )

            self.assertEqual(observer.ledger.state["status"], "COMPLETE")
            self.assertEqual(observer.ledger.state["usage"]["native_total_tokens"], 140)
            frozen = root / observer.ledger.state["payload_ref"]
            self.assertTrue(frozen.is_file())
            recovered = ExternalRunLedger(root)
            self.assertEqual(recovered.state, observer.ledger.state)
            with closing(sqlite3.connect(recovered.database_path)) as connection:
                count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            self.assertEqual(count, recovered.state["event_count"])
            self.assertIn("状态：COMPLETE", format_status_card(recovered.state))

    def test_illegal_transition_and_payload_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            ledger = ExternalRunLedger(
                root,
                run_id="run-002",
                mission_id="msn-002",
                task_id="T-002",
                stage="worker",
                runtime="codex",
                model="cheap-codex",
            )
            with self.assertRaises(ExternalRunStateError):
                ledger.append(ledger.next_event("run.completed", source="broker", summary="invalid"))

            ledger.append(ledger.next_event("run.dispatched", source="broker", summary="sent"))
            payload = root / "payload.json"
            payload.write_text("{}", encoding="utf-8")
            event = ledger.next_event(
                "run.acknowledged",
                source="adapter",
                summary="ack",
                session_id="session-2",
                payload=payload,
            )
            payload.write_text('{"tampered":true}', encoding="utf-8")
            with self.assertRaisesRegex(ExternalRunStateError, "hash mismatch"):
                ledger.append(event)

    def test_stalled_status_is_derived_without_mutating_ledger(self) -> None:
        state = {
            "task_id": "T-003",
            "stage": "worker",
            "runtime": "minimax",
            "status": "RUNNING",
            "started_at": "2026-07-11T00:00:00+00:00",
            "updated_at": "2026-07-11T00:00:10+00:00",
            "last_activity_at": "2026-07-11T00:00:10+00:00",
            "terminal_at": None,
            "session_id": "session-3",
            "usage": None,
            "delivery": None,
            "error": None,
        }
        projected = project_status(
            state,
            now=datetime(2026, 7, 11, 0, 4, 0, tzinfo=timezone.utc),
            stalled_after_seconds=180,
        )
        self.assertEqual(projected["display_status"], "STALLED")
        self.assertEqual(state["status"], "RUNNING")

    def test_success_exit_without_structured_delivery_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            observer = ExternalRunObserver.create(
                Path(tmp) / "run",
                run_id="run-004",
                mission_id="msn-004",
                task_id="T-004",
                stage="worker",
                runtime="codex",
                model="cheap-codex",
            )
            observer.complete(RuntimeResult("codex", RuntimeStatus.SUCCEEDED, "session-4", None, 0))
            self.assertEqual(observer.ledger.state["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
