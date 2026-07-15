from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from copy import deepcopy
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .runtime import RuntimeResult, RuntimeStatus, normalize_usage
from .schema import SchemaRegistry, SchemaValidationError, canonical_json_bytes
from .state import EventStore, atomic_write_json


EXTERNAL_EVENT_SCHEMA_ID = "token-firewall/external-run-event@0.1"
TERMINAL_STATES = {"COMPLETE", "BLOCKED", "FAILED", "TIMED_OUT", "CANCELLED"}

TRANSITIONS: dict[str, tuple[set[str], str | None]] = {
    "run.dispatched": ({"QUEUED"}, "DISPATCHED"),
    "run.acknowledged": ({"DISPATCHED"}, "ACKNOWLEDGED"),
    "run.activity": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED"}, "RUNNING"),
    "run.idle": ({"ACKNOWLEDGED", "RUNNING"}, "IDLE"),
    "run.stalled": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE"}, "STALLED"),
    "run.recovered": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "FAILED", "TIMED_OUT"}, "RECOVERED"),
    "run.usage_updated": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED", "DELIVERING", "DELIVERED", "COMPLETE", "BLOCKED", "FAILED", "TIMED_OUT"}, None),
    "run.delivery_received": ({"ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED"}, "DELIVERING"),
    "run.snapshot_frozen": ({"DELIVERING"}, "DELIVERED"),
    "run.completed": ({"DELIVERED"}, "COMPLETE"),
    "run.blocked": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED", "DELIVERING"}, "BLOCKED"),
    "run.failed": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED", "DELIVERING"}, "FAILED"),
    "run.timed_out": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED", "DELIVERING"}, "TIMED_OUT"),
    "run.cancelled": ({"DISPATCHED", "ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED", "DELIVERING"}, "CANCELLED"),
}


class ExternalRunStateError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _payload_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExternalRunLedger:
    """Append-only external Runtime lifecycle ledger with a rebuildable SQLite index."""

    def __init__(
        self,
        root: Path | str,
        *,
        run_id: str | None = None,
        mission_id: str | None = None,
        task_id: str | None = None,
        stage: str | None = None,
        runtime: str | None = None,
        model: str | None = None,
        registry: SchemaRegistry | None = None,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(self.root / "external-events.jsonl")
        self.snapshot_path = self.root / "external-run-state.json"
        self.database_path = self.root / "external-run.sqlite3"
        self.registry = registry or SchemaRegistry()
        self.metadata = {
            "run_id": run_id,
            "mission_id": mission_id,
            "task_id": task_id,
            "stage": stage,
            "runtime": runtime,
            "model": model,
        }
        events = list(self.store.read())
        if events:
            first = events[0]
            for key in self.metadata:
                recorded = first.get(key)
                supplied = self.metadata[key]
                if supplied is not None and supplied != recorded:
                    raise ExternalRunStateError(f"{key} differs from persisted external run")
                self.metadata[key] = recorded
        missing = [key for key in ("run_id", "task_id", "stage", "runtime") if not self.metadata[key]]
        if missing:
            raise ExternalRunStateError(f"external run metadata is incomplete: {missing}")
        self.state = self._recover(events)

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema": "token-firewall/external-run-state@0.1",
            **self.metadata,
            "session_id": None,
            "status": "QUEUED",
            "started_at": None,
            "updated_at": None,
            "last_activity_at": None,
            "terminal_at": None,
            "sequence": 0,
            "event_count": 0,
            "last_event_id": None,
            "native_status": None,
            "usage": None,
            "delivery": None,
            "payload_ref": None,
            "payload_sha256": None,
            "error": None,
        }

    def _recover(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        state = self._initial_state()
        seen: dict[str, bytes] = {}
        for event in events:
            self._validate_event(event)
            encoded = canonical_json_bytes(event)
            event_id = event["event_id"]
            if event_id in seen:
                if seen[event_id] != encoded:
                    raise ExternalRunStateError(f"event_id collision in external ledger: {event_id}")
                continue
            state = self._apply(state, event)
            seen[event_id] = encoded
        atomic_write_json(self.snapshot_path, state)
        self._rebuild_sqlite(events, state)
        return state

    def append(self, event: dict[str, Any]) -> bool:
        self._validate_event(event)
        existing = self.store.find(event["event_id"])
        if existing is not None:
            if canonical_json_bytes(existing) != canonical_json_bytes(event):
                raise ExternalRunStateError(f"event_id collision with different payload: {event['event_id']}")
            return False
        candidate = self._apply(self.state, event)
        self.store.append(event)
        atomic_write_json(self.snapshot_path, candidate)
        self.state = candidate
        self._append_sqlite(event, candidate)
        return True

    def events(self, *, after_sequence: int = 0) -> Iterable[dict[str, Any]]:
        for event in self.store.read():
            if event["sequence"] > after_sequence:
                yield event

    def next_event(
        self,
        kind: str,
        *,
        source: str,
        summary: str,
        session_id: str | None = None,
        native_status: str | None = None,
        payload: Path | None = None,
        usage: dict[str, Any] | None = None,
        delivery: dict[str, Any] | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        sequence = self.state["sequence"] + 1
        event: dict[str, Any] = {
            "schema": EXTERNAL_EVENT_SCHEMA_ID,
            "event_id": f"xevt_{sequence:06d}",
            "run_id": self.metadata["run_id"],
            "mission_id": self.metadata["mission_id"],
            "task_id": self.metadata["task_id"],
            "stage": self.metadata["stage"],
            "runtime": self.metadata["runtime"],
            "model": self.metadata["model"],
            "session_id": session_id if session_id is not None else self.state["session_id"],
            "sequence": sequence,
            "at": at or _now(),
            "kind": kind,
            "source": source,
            "summary": summary,
        }
        if native_status:
            event["native_status"] = native_status
        if payload is not None:
            resolved = payload.resolve()
            root = self.root.resolve()
            if not resolved.is_relative_to(root):
                raise ExternalRunStateError("external event payload must be inside the ledger directory")
            event["payload_ref"] = resolved.relative_to(root).as_posix()
            event["payload_sha256"] = _payload_sha256(resolved)
        if usage is not None:
            event["usage"] = usage
        if delivery is not None:
            event["delivery"] = delivery
        return event

    def _validate_event(self, event: dict[str, Any]) -> None:
        try:
            self.registry.validate(event, EXTERNAL_EVENT_SCHEMA_ID)
        except SchemaValidationError as exc:
            raise ExternalRunStateError(str(exc)) from exc
        for key in ("run_id", "mission_id", "task_id", "stage", "runtime", "model"):
            if event.get(key) != self.metadata[key]:
                raise ExternalRunStateError(f"external event {key} differs from ledger")
        relative = event.get("payload_ref")
        if relative is not None:
            candidate = (self.root / relative).resolve()
            if not candidate.is_relative_to(self.root.resolve()) or not candidate.is_file():
                raise ExternalRunStateError("external event payload is missing or escapes ledger")
            if _payload_sha256(candidate) != event["payload_sha256"]:
                raise ExternalRunStateError("external event payload hash mismatch")

    def _apply(self, current: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        if event["sequence"] != current["sequence"] + 1:
            raise ExternalRunStateError("external event sequence is not contiguous")
        transition = TRANSITIONS.get(event["kind"])
        if transition is None:
            raise ExternalRunStateError(f"unknown external event kind: {event['kind']}")
        allowed, target = transition
        if current["status"] not in allowed:
            raise ExternalRunStateError(
                f"illegal external transition {current['status']} --{event['kind']}--> {target or current['status']}"
            )
        state = deepcopy(current)
        if target is not None:
            state["status"] = target
        state["sequence"] = event["sequence"]
        state["event_count"] += 1
        state["last_event_id"] = event["event_id"]
        state["updated_at"] = event["at"]
        if state["started_at"] is None and event["kind"] == "run.dispatched":
            state["started_at"] = event["at"]
        if event["kind"] in {"run.acknowledged", "run.activity", "run.idle", "run.recovered", "run.delivery_received"}:
            state["last_activity_at"] = event["at"]
        if event["session_id"] is not None:
            state["session_id"] = event["session_id"]
        if "native_status" in event:
            state["native_status"] = event["native_status"]
        if "usage" in event:
            state["usage"] = event["usage"]
        if "delivery" in event:
            state["delivery"] = event["delivery"]
        if "payload_ref" in event:
            state["payload_ref"] = event["payload_ref"]
            state["payload_sha256"] = event["payload_sha256"]
        if event["kind"] in {"run.failed", "run.timed_out", "run.blocked", "run.cancelled"}:
            state["error"] = event["summary"]
        if state["status"] in TERMINAL_STATES:
            state["terminal_at"] = event["at"]
        return state

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL, body_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS run_state (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), status TEXT NOT NULL, updated_at TEXT, body_json TEXT NOT NULL)"
        )
        return connection

    def _rebuild_sqlite(self, events: list[dict[str, Any]], state: dict[str, Any]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM events")
            connection.executemany(
                "INSERT INTO events(sequence, event_id, kind, at, body_json) VALUES (?, ?, ?, ?, ?)",
                [
                    (event["sequence"], event["event_id"], event["kind"], event["at"], json.dumps(event, ensure_ascii=False, sort_keys=True))
                    for event in events
                ],
            )
            connection.execute(
                "INSERT OR REPLACE INTO run_state(singleton, status, updated_at, body_json) VALUES (1, ?, ?, ?)",
                (state["status"], state["updated_at"], json.dumps(state, ensure_ascii=False, sort_keys=True)),
            )

    def _append_sqlite(self, event: dict[str, Any], state: dict[str, Any]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO events(sequence, event_id, kind, at, body_json) VALUES (?, ?, ?, ?, ?)",
                (event["sequence"], event["event_id"], event["kind"], event["at"], json.dumps(event, ensure_ascii=False, sort_keys=True)),
            )
            connection.execute(
                "INSERT OR REPLACE INTO run_state(singleton, status, updated_at, body_json) VALUES (1, ?, ?, ?)",
                (state["status"], state["updated_at"], json.dumps(state, ensure_ascii=False, sort_keys=True)),
            )


@dataclass
class ExternalRunObserver:
    ledger: ExternalRunLedger
    heartbeat_seconds: int = 60
    _last_native_status: str | None = None
    _last_activity_emit: datetime | None = None

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        run_id: str,
        mission_id: str | None,
        task_id: str,
        stage: str,
        runtime: str,
        model: str | None,
        heartbeat_seconds: int = 60,
        registry: SchemaRegistry | None = None,
    ) -> "ExternalRunObserver":
        ledger = ExternalRunLedger(
            root,
            run_id=run_id,
            mission_id=mission_id,
            task_id=task_id,
            stage=stage,
            runtime=runtime,
            model=model,
            registry=registry,
        )
        observer = cls(ledger, heartbeat_seconds=heartbeat_seconds)
        if ledger.state["status"] == "QUEUED":
            ledger.append(ledger.next_event("run.dispatched", source="broker", summary="任务已派发给外部 Runtime"))
        return observer

    def trace(self, kind: str, details: dict[str, Any]) -> None:
        session_id = details.get("session_id") if isinstance(details.get("session_id"), str) else None
        if kind == "runtime.started" and self.ledger.state["status"] == "DISPATCHED":
            self.ledger.append(
                self.ledger.next_event(
                    "run.acknowledged",
                    source="adapter",
                    summary="外部 Runtime 已接受任务",
                    session_id=session_id,
                )
            )
            return
        if kind == "runtime.polled":
            status = str(details.get("status", "unknown"))
            now = datetime.now(timezone.utc)
            due = self._last_activity_emit is None or (now - self._last_activity_emit).total_seconds() >= self.heartbeat_seconds
            if status != self._last_native_status or due:
                if self.ledger.state["status"] == "DISPATCHED":
                    self.ledger.append(
                        self.ledger.next_event(
                            "run.acknowledged",
                            source="adapter",
                            summary="外部 Runtime 已创建会话",
                            session_id=session_id,
                            native_status=status,
                        )
                    )
                if self.ledger.state["status"] not in TERMINAL_STATES | {"DELIVERING", "DELIVERED"}:
                    self.ledger.append(
                        self.ledger.next_event(
                            "run.activity",
                            source="adapter",
                            summary="外部 Runtime 正常工作",
                            session_id=session_id,
                            native_status=status,
                        )
                    )
                self._last_native_status = status
                self._last_activity_emit = now
            return
        if kind in {"runtime.recovered", "runtime.snapshot_recovered"}:
            if self.ledger.state["status"] == "DISPATCHED":
                self.ledger.append(
                    self.ledger.next_event(
                        "run.acknowledged",
                        source="recovery",
                        summary="已定位外部 Runtime 交付快照",
                        session_id=session_id,
                    )
                )
            self.ledger.append(
                self.ledger.next_event(
                    "run.recovered",
                    source="recovery",
                    summary="外部 Runtime 会话已恢复",
                    session_id=session_id,
                )
            )
            return
        if kind == "runtime.timed_out" and self.ledger.state["status"] not in TERMINAL_STATES:
            self.ledger.append(
                self.ledger.next_event(
                    "run.timed_out",
                    source="watchdog",
                    summary="外部 Runtime 超时",
                    session_id=session_id,
                )
            )
            return
        if kind == "runtime.stalled" and self.ledger.state["status"] not in TERMINAL_STATES:
            self.ledger.append(
                self.ledger.next_event(
                    "run.stalled",
                    source="watchdog",
                    summary="外部 Runtime 因持续无活动被终止",
                    session_id=session_id,
                )
            )
            return
        if kind == "runtime.cancelled" and self.ledger.state["status"] not in TERMINAL_STATES:
            self.ledger.append(
                self.ledger.next_event(
                    "run.cancelled",
                    source="watchdog",
                    summary="外部 Runtime 已取消并清理子进程",
                    session_id=session_id,
                )
            )

    def complete(
        self,
        result: RuntimeResult,
        *,
        payload: Path | None = None,
        delivery: dict[str, Any] | None = None,
    ) -> None:
        session_id = result.session_id or self.ledger.state["session_id"]
        frozen_payload = self._freeze_payload(payload) if payload is not None else None
        if result.usage:
            required_usage = {
                "input_tokens", "output_tokens", "reasoning_tokens", "cache_read_tokens",
                "cache_write_tokens", "total_tokens", "native_total_tokens", "source", "complete",
            }
            usage = (
                dict(result.usage)
                if required_usage <= result.usage.keys()
                else normalize_usage(result.usage, source=str(result.usage.get("source", "runtime-result")))
            )
            self.ledger.append(
                self.ledger.next_event(
                    "run.usage_updated",
                    source="adapter",
                    summary="已记录外部 Runtime 用量",
                    session_id=session_id,
                    usage=usage,
                )
            )
        if self.ledger.state["status"] in TERMINAL_STATES:
            return
        if result.ok:
            if self.ledger.state["status"] == "DISPATCHED":
                self.ledger.append(
                    self.ledger.next_event(
                        "run.acknowledged",
                        source="adapter",
                        summary="外部 Runtime 已返回会话",
                        session_id=session_id,
                    )
                )
            if self.ledger.state["status"] in {"ACKNOWLEDGED", "RUNNING", "IDLE", "STALLED", "RECOVERED"}:
                self.ledger.append(
                    self.ledger.next_event(
                        "run.delivery_received",
                        source="broker",
                        summary="已收到外部 Runtime 交付报告",
                        session_id=session_id,
                        delivery=delivery,
                    )
                )
            self.ledger.append(
                self.ledger.next_event(
                    "run.snapshot_frozen",
                    source="broker",
                    summary="外部 Runtime 交付快照已冻结",
                    session_id=session_id,
                    payload=frozen_payload,
                    delivery=delivery,
                )
            )
            self.ledger.append(
                self.ledger.next_event(
                    "run.completed",
                    source="broker",
                    summary="外部 Runtime 阶段完成",
                    session_id=session_id,
                    delivery=delivery,
                )
            )
            return
        kind = {
            RuntimeStatus.BLOCKED: "run.blocked",
            RuntimeStatus.TIMED_OUT: "run.timed_out",
        }.get(result.status, "run.failed")
        summary = result.error or (
            "外部 Runtime 未返回可验证的结构化交付物"
            if result.status == RuntimeStatus.SUCCEEDED
            else f"外部 Runtime 结束：{result.status.value}"
        )
        self.ledger.append(
            self.ledger.next_event(
                kind,
                source="adapter",
                summary=summary,
                session_id=session_id,
                payload=frozen_payload,
            )
        )

    def _freeze_payload(self, source: Path) -> Path:
        destination_dir = self.ledger.root / "payloads"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            destination = destination_dir / f"{self.ledger.state['sequence'] + 1:06d}-{source.name}"
        if not destination.exists():
            shutil.copyfile(source, destination)
        return destination


def project_status(
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    stalled_after_seconds: int = 180,
) -> dict[str, Any]:
    projected = deepcopy(state)
    now = now or datetime.now().astimezone()
    reference = state.get("last_activity_at") or state.get("updated_at") or state.get("started_at")
    age = None
    if reference:
        age = max(0, int((now - _parse_time(reference)).total_seconds()))
    projected["seconds_since_activity"] = age
    projected["stalled_derived"] = bool(
        state["status"] not in TERMINAL_STATES | {"DELIVERED"}
        and age is not None
        and age >= stalled_after_seconds
    )
    projected["display_status"] = "STALLED" if projected["stalled_derived"] else state["status"]
    if state.get("started_at"):
        end = _parse_time(state["terminal_at"]) if state.get("terminal_at") else now
        projected["elapsed_seconds"] = max(0, int((end - _parse_time(state["started_at"])).total_seconds()))
    else:
        projected["elapsed_seconds"] = 0
    return projected


def format_status_card(state: dict[str, Any], *, stalled_after_seconds: int = 180) -> str:
    status = project_status(state, stalled_after_seconds=stalled_after_seconds)
    lines = [
        f"[{status['task_id']} · {status['stage']} · {status['runtime']}]",
        f"状态：{status['display_status']}",
        f"已运行：{status['elapsed_seconds']} 秒",
    ]
    if status.get("seconds_since_activity") is not None:
        lines.append(f"最后活动：{status['seconds_since_activity']} 秒前")
    if status.get("session_id"):
        lines.append(f"Session：{status['session_id']}")
    usage = status.get("usage")
    if usage:
        lines.append(
            f"Token：{usage['native_total_tokens']} native / {usage['total_tokens']} accounted"
        )
    delivery = status.get("delivery")
    if delivery:
        lines.append(
            f"交付：commit={delivery.get('commit') or 'n/a'}，files={delivery['changed_files']}，+{delivery['additions']}/-{delivery['deletions']}"
        )
    if status.get("error"):
        lines.append(f"异常：{status['error']}")
    return "\n".join(lines)


def discover_ledgers(path: Path | str) -> list[ExternalRunLedger]:
    root = Path(path)
    if (root / "external-events.jsonl").is_file():
        return [ExternalRunLedger(root)]
    return [
        ExternalRunLedger(events.parent)
        for events in sorted(root.glob("observability/**/external-events.jsonl"))
    ]
