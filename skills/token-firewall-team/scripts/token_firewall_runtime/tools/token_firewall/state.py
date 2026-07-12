from __future__ import annotations

import json
import hashlib
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .schema import SchemaRegistry, SchemaValidationError, canonical_json_bytes


MISSION_TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "mission.approved": ({"DRAFT"}, "APPROVED"),
    "mission.decomposing": ({"APPROVED"}, "DECOMPOSING"),
    "mission.running": ({"DECOMPOSING"}, "RUNNING"),
    "mission.integrating": ({"RUNNING"}, "INTEGRATING"),
    "mission.reviewing": ({"INTEGRATING"}, "REVIEWING"),
    "mission.passed": ({"REVIEWING"}, "PASSED"),
    "mission.blocked": ({"DRAFT", "APPROVED", "DECOMPOSING", "RUNNING", "INTEGRATING", "REVIEWING"}, "BLOCKED"),
    "mission.needs_user_decision": (
        {"DRAFT", "APPROVED", "DECOMPOSING", "RUNNING", "INTEGRATING", "REVIEWING", "BLOCKED"},
        "NEEDS_USER_DECISION",
    ),
    "mission.aborted": (
        {"DRAFT", "APPROVED", "DECOMPOSING", "RUNNING", "INTEGRATING", "REVIEWING", "BLOCKED", "NEEDS_USER_DECISION"},
        "ABORTED",
    ),
    "mission.failed": ({"APPROVED", "DECOMPOSING", "RUNNING", "INTEGRATING", "REVIEWING", "BLOCKED"}, "FAILED"),
}

WORK_TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "work.ready": ({"DRAFT"}, "READY"),
    "work.started": ({"READY"}, "RUNNING"),
    "work.delivered": ({"RUNNING"}, "DELIVERED"),
    "test.started": ({"DELIVERED"}, "TESTING"),
    "verification.started": ({"TESTING"}, "VERIFYING"),
    "work.verified": ({"VERIFYING"}, "VERIFIED"),
    "work.accepted": ({"VERIFIED"}, "ACCEPTED"),
    "work.rework": ({"DELIVERED", "TESTING", "VERIFYING", "VERIFIED"}, "REWORK"),
    "work.rework_started": ({"REWORK"}, "RUNNING"),
    "work.needs_replan": ({"READY", "RUNNING", "DELIVERED", "TESTING", "VERIFYING", "VERIFIED", "REWORK", "BLOCKED"}, "NEEDS_REPLAN"),
    "work.blocked": ({"READY", "RUNNING", "DELIVERED", "TESTING", "VERIFYING", "REWORK"}, "BLOCKED"),
    "work.aborted": ({"DRAFT", "READY", "RUNNING", "DELIVERED", "TESTING", "VERIFYING", "VERIFIED", "REWORK", "BLOCKED", "NEEDS_REPLAN"}, "ABORTED"),
}

PROPOSAL_ROLES: dict[str, set[str]] = {
    "work.ready.proposed": {"decomposition-lead"},
    "work.delivery.proposed": {"implementer"},
    "test.completed": {"test-engineer", "conductor"},
    "verification.proposed": {"independent-verifier"},
    "review.verdict.proposed": {"chief-reviewer", "deputy-reviewer"},
    "work.replan.proposed": {"implementer", "independent-verifier", "decomposition-lead"},
}

EVIDENCE_REQUIRED = {
    "work.delivered",
    "work.verified",
    "work.accepted",
    "mission.passed",
}


class StateTransitionError(RuntimeError):
    pass


def atomic_write_json(path: Path | str, value: dict[str, Any]) -> None:
    """Durably replace a JSON snapshot without exposing a partial state file."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


class EventStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def read(self) -> Iterable[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StateTransitionError(f"corrupt events.jsonl at line {line_number}: {exc}") from exc
                if not isinstance(value, dict):
                    raise StateTransitionError(f"event at line {line_number} is not an object")
                yield value

    def find(self, event_id: str) -> dict[str, Any] | None:
        for event in self.read():
            if event.get("event_id") == event_id:
                return event
        return None


class Conductor:
    """Apply validated candidate events to an authoritative, replayable state."""

    def __init__(
        self,
        mission_id: str,
        run_dir: Path | str,
        *,
        registry: SchemaRegistry | None = None,
    ):
        self.mission_id = mission_id
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(self.run_dir / "events.jsonl")
        self.snapshot_path = self.run_dir / "mission-state.json"
        self.registry = registry or SchemaRegistry()
        self.state = self.recover()

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema": "token-firewall/run-state@0.1",
            "mission_id": self.mission_id,
            "mission_state": "DRAFT",
            "tasks": {},
            "applied_event_ids": [],
            "last_event_id": None,
        }

    def emit(self, event: dict[str, Any]) -> bool:
        """Persist and apply one event. Identical event IDs are idempotent."""

        try:
            self.registry.validate(event)
        except SchemaValidationError as exc:
            raise StateTransitionError(str(exc)) from exc
        if event["mission_id"] != self.mission_id:
            raise StateTransitionError("event mission_id does not match this run")
        self._verify_payload(event)

        existing = self.store.find(event["event_id"])
        if existing is not None:
            if canonical_json_bytes(existing) != canonical_json_bytes(event):
                raise StateTransitionError(f"event_id collision with different payload: {event['event_id']}")
            if event["event_id"] not in self.state["applied_event_ids"]:
                self.state = self.recover()
            return False

        candidate = self._apply(self.state, event)
        self.store.append(event)
        atomic_write_json(self.snapshot_path, candidate)
        self.state = candidate
        return True

    def recover(self) -> dict[str, Any]:
        """Rebuild state from the append-only log, then atomically refresh the snapshot."""

        state = self._initial_state()
        seen: dict[str, bytes] = {}
        for event in self.store.read():
            try:
                self.registry.validate(event)
            except SchemaValidationError as exc:
                raise StateTransitionError(f"invalid persisted event: {exc}") from exc
            if event["mission_id"] != self.mission_id:
                raise StateTransitionError("persisted event belongs to another mission")
            self._verify_payload(event)
            encoded = canonical_json_bytes(event)
            event_id = event["event_id"]
            if event_id in seen:
                if seen[event_id] != encoded:
                    raise StateTransitionError(f"event_id collision in log: {event_id}")
                continue
            state = self._apply(state, event)
            seen[event_id] = encoded
        atomic_write_json(self.snapshot_path, state)
        return state

    def _verify_payload(self, event: dict[str, Any]) -> None:
        relative = event.get("payload_ref")
        if relative is None:
            return
        if not isinstance(relative, str) or relative.startswith("/") or "\\" in relative:
            raise StateTransitionError("event payload_ref is not a safe relative path")
        root = self.run_dir.resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise StateTransitionError("event payload_ref escapes the run directory")
        if not candidate.is_file():
            raise StateTransitionError(f"event payload does not exist: {relative}")
        actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual_hash != event.get("payload_sha256"):
            raise StateTransitionError(f"event payload hash mismatch: {relative}")

    def _apply(self, current: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        state = deepcopy(current)
        event_id = event["event_id"]
        if event_id in state["applied_event_ids"]:
            return state

        kind = event["kind"]
        role = event["producer"]["role"]
        if kind in PROPOSAL_ROLES:
            if role not in PROPOSAL_ROLES[kind]:
                raise StateTransitionError(f"role {role!r} cannot produce {kind}")
        elif kind.startswith("trace."):
            pass
        elif kind in MISSION_TRANSITIONS:
            if role != "conductor":
                raise StateTransitionError(f"only conductor may execute authoritative transition {kind}")
            self._apply_mission_transition(state, kind, event)
        elif kind in WORK_TRANSITIONS:
            if role != "conductor":
                raise StateTransitionError(f"only conductor may execute authoritative transition {kind}")
            self._apply_work_transition(state, kind, event)
        else:
            raise StateTransitionError(f"unknown event kind: {kind}")

        state["applied_event_ids"].append(event_id)
        state["last_event_id"] = event_id
        return state

    def _apply_mission_transition(self, state: dict[str, Any], kind: str, event: dict[str, Any]) -> None:
        allowed, target = MISSION_TRANSITIONS[kind]
        source = state["mission_state"]
        if source not in allowed:
            raise StateTransitionError(f"illegal mission transition {source} --{kind}--> {target}")
        if kind == "mission.integrating" and state["tasks"]:
            incomplete = sorted(
                task_id
                for task_id, task in state["tasks"].items()
                if task["state"] not in {"VERIFIED", "ACCEPTED"}
            )
            if incomplete:
                raise StateTransitionError(f"cannot integrate while tasks are incomplete: {incomplete}")
        if kind == "mission.passed":
            incomplete = sorted(
                task_id for task_id, task in state["tasks"].items() if task["state"] != "ACCEPTED"
            )
            if incomplete:
                raise StateTransitionError(f"cannot pass mission while tasks are not accepted: {incomplete}")
        if kind in EVIDENCE_REQUIRED and not event.get("payload_ref"):
            raise StateTransitionError(f"{kind} requires an evidence payload reference")
        state["mission_state"] = target

    def _apply_work_transition(self, state: dict[str, Any], kind: str, event: dict[str, Any]) -> None:
        task_id = event.get("task_id")
        if not task_id:
            raise StateTransitionError(f"{kind} requires task_id")
        task = state["tasks"].setdefault(task_id, {"state": "DRAFT", "rework_rounds": 0})
        source = task["state"]
        allowed, target = WORK_TRANSITIONS[kind]
        if source not in allowed:
            raise StateTransitionError(f"illegal work transition for {task_id}: {source} --{kind}--> {target}")

        mission_state = state["mission_state"]
        if kind == "work.ready" and mission_state not in {"DECOMPOSING", "RUNNING"}:
            raise StateTransitionError("Work Order can become READY only while mission is DECOMPOSING or RUNNING")
        if kind == "work.started" and mission_state != "RUNNING":
            raise StateTransitionError("Work Order can start only while mission is RUNNING")
        if kind == "work.accepted" and mission_state != "REVIEWING":
            raise StateTransitionError("Work Order can be ACCEPTED only during mission REVIEWING")
        if kind in EVIDENCE_REQUIRED and not event.get("payload_ref"):
            raise StateTransitionError(f"{kind} requires an evidence payload reference")
        if kind == "work.rework":
            task["rework_rounds"] += 1
        task["state"] = target
        task["last_event_id"] = event["event_id"]


@dataclass(frozen=True)
class ReworkDecision:
    state: str
    reason: str
    round: int


class ReworkMonitor:
    """Detect retry exhaustion, repeated findings, A↔B oscillation and diff growth."""

    def __init__(self, max_rounds: int = 2):
        if max_rounds < 0:
            raise ValueError("max_rounds cannot be negative")
        self.max_rounds = max_rounds
        self.history: dict[str, list[dict[str, Any]]] = {}

    def record_failure(
        self,
        task_id: str,
        *,
        finding_ids: Iterable[str],
        fix_signature: str,
        diff_lines: int,
    ) -> ReworkDecision:
        records = self.history.setdefault(task_id, [])
        finding_set = set(finding_ids)
        record = {
            "finding_ids": finding_set,
            "fix_signature": fix_signature,
            "diff_lines": diff_lines,
        }
        next_round = len(records) + 1

        if any(finding_set.intersection(previous["finding_ids"]) for previous in records):
            records.append(record)
            return ReworkDecision("NEEDS_REPLAN", "repeated_finding", next_round)
        if len(records) >= 2 and fix_signature == records[-2]["fix_signature"] != records[-1]["fix_signature"]:
            records.append(record)
            return ReworkDecision("NEEDS_REPLAN", "fix_oscillation", next_round)
        if len(records) >= 2 and records[-2]["diff_lines"] < records[-1]["diff_lines"] < diff_lines:
            records.append(record)
            return ReworkDecision("NEEDS_REPLAN", "diff_growth", next_round)
        if len(records) >= self.max_rounds:
            records.append(record)
            return ReworkDecision("NEEDS_REPLAN", "retry_budget_exhausted", next_round)

        records.append(record)
        return ReworkDecision("REWORK", "retry_allowed", next_round)

    def record_success(self, task_id: str) -> None:
        self.history.pop(task_id, None)
