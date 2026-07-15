from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .gates import (
    GateFinding,
    estimate_packet_tokens,
    validate_review_packet,
    validate_work_order_graph,
    verify_delivery,
)
from .observability import ExternalRunObserver
from .runtime import (
    RuntimeAdapter,
    RuntimeRequest,
    RuntimeStatus,
    VERDICT_SCHEMA_ID,
    WORKER_REPORT_SCHEMA_ID,
    build_reviewer_prompt,
    build_worker_prompt,
)
from .schema import SchemaRegistry, canonical_sha256
from .state import Conductor, atomic_write_json
from .worktree import GitWorktreeError, GitWorktreeManager, broker_commit_changes, inspect_commit_range, sanitize_runtime_ephemera


@dataclass
class RuntimePocResult:
    status: str
    mission_id: str
    task_id: str
    run_dir: Path
    worktree: Path | None = None
    delivery_manifest: Path | None = None
    review_packet: Path | None = None
    review_verdict: Path | None = None
    findings: list[GateFinding] = field(default_factory=list)
    runtime_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "run_dir": str(self.run_dir),
            "worktree": str(self.worktree) if self.worktree else None,
            "delivery_manifest": str(self.delivery_manifest) if self.delivery_manifest else None,
            "review_packet": str(self.review_packet) if self.review_packet else None,
            "review_verdict": str(self.review_verdict) if self.review_verdict else None,
            "findings": [
                {"code": item.code, "message": item.message, "details": item.details}
                for item in self.findings
            ],
            "runtime_error": self.runtime_error,
        }


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    value["content_sha256"] = canonical_sha256(value)
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_ref(root: Path, path: Path, *, mime_type: str = "application/json") -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"evidence path is outside run directory: {path}")
    return {
        "path": resolved_path.relative_to(resolved_root).as_posix(),
        "sha256": _file_sha256(resolved_path),
        "bytes": resolved_path.stat().st_size,
        "mime_type": mime_type,
    }


class _EventEmitter:
    def __init__(self, conductor: Conductor, run_dir: Path):
        self.conductor = conductor
        self.run_dir = run_dir.resolve()
        self.counter = len(conductor.state["applied_event_ids"])

    def emit(
        self,
        kind: str,
        *,
        role: str = "conductor",
        session_id: str = "conductor",
        task_id: str | None = None,
        payload: Path | None = None,
    ) -> None:
        self.counter += 1
        event: dict[str, Any] = {
            "schema": "token-firewall/event@0.1",
            "event_id": f"evt_{self.counter:06d}",
            "mission_id": self.conductor.mission_id,
            "task_id": task_id,
            "at": _now(),
            "producer": {"role": role, "session_id": session_id or "unknown-session"},
            "kind": kind,
        }
        if payload is not None:
            resolved = payload.resolve()
            if not resolved.is_relative_to(self.run_dir):
                raise ValueError(f"event payload is outside run directory: {payload}")
            event["payload_ref"] = resolved.relative_to(self.run_dir).as_posix()
            event["payload_sha256"] = _file_sha256(resolved)
        self.conductor.emit(event)


class RuntimePocRunner:
    def __init__(
        self,
        *,
        repo_root: Path | str,
        run_dir: Path | str,
        worktree_root: Path | str,
        worker: RuntimeAdapter,
        reviewer: RuntimeAdapter | None = None,
        registry: SchemaRegistry | None = None,
    ):
        self.repo_root = Path(repo_root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.worktree_manager = GitWorktreeManager(self.repo_root, worktree_root)
        self.worker = worker
        self.reviewer = reviewer
        self.registry = registry or SchemaRegistry()

    def run(
        self,
        mission_contract: dict[str, Any],
        work_order: dict[str, Any],
        *,
        base_commit: str,
        worker_model: str | None = None,
        reviewer_model: str | None = None,
        timeout_seconds: int = 1800,
        startup_timeout_seconds: float = 30.0,
        stall_timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 2.0,
        run_id: str | None = None,
        defer_external_verification: bool = False,
    ) -> RuntimePocResult:
        self.registry.validate(mission_contract)
        self.registry.validate(work_order)
        if mission_contract["mission_id"] != work_order["mission_id"]:
            raise ValueError("Mission Contract and Work Order mission_id differ")
        graph = validate_work_order_graph([work_order])
        if not graph.ok:
            return RuntimePocResult(
                "PREFLIGHT_FAILED",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                findings=graph.findings,
            )
        if self.run_dir.exists() and any(self.run_dir.iterdir()):
            raise ValueError(f"run_dir must be new or empty: {self.run_dir}")
        self.run_dir.mkdir(parents=True, exist_ok=True)

        worker_preflight = self.worker.preflight()
        if not worker_preflight.ok:
            return RuntimePocResult(
                "PREFLIGHT_FAILED",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                findings=worker_preflight.findings,
            )
        if self.reviewer is not None:
            reviewer_preflight = self.reviewer.preflight()
            if not reviewer_preflight.ok:
                return RuntimePocResult(
                    "PREFLIGHT_FAILED",
                    mission_contract["mission_id"],
                    work_order["task_id"],
                    self.run_dir,
                    findings=reviewer_preflight.findings,
                )

        mission_path = self.run_dir / "mission-contract.json"
        task_dir = self.run_dir / "work-orders" / work_order["task_id"]
        work_order_path = task_dir / "work-order.json"
        task_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(mission_path, mission_contract)
        atomic_write_json(work_order_path, work_order)

        conductor = Conductor(mission_contract["mission_id"], self.run_dir, registry=self.registry)
        events = _EventEmitter(conductor, self.run_dir)
        events.emit("mission.approved", payload=mission_path)
        events.emit("mission.decomposing")
        events.emit("work.ready", task_id=work_order["task_id"], payload=work_order_path)

        try:
            worktree = self.worktree_manager.create(
                mission_contract["mission_id"],
                work_order["task_id"],
                base_commit,
                run_id=run_id,
            )
        except GitWorktreeError as exc:
            events.emit("mission.blocked")
            return RuntimePocResult(
                "PREFLIGHT_FAILED",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                runtime_error=str(exc),
            )

        events.emit("mission.running")
        events.emit("work.started", task_id=work_order["task_id"])
        runtime_dir = task_dir / "runtime-worker"

        def make_trace(observer: ExternalRunObserver):
            def trace(kind: str, details: dict[str, Any]) -> None:
                observer.trace(kind, details)
                safe_kind = re.sub(r"[^a-z0-9_.-]+", "_", kind.lower())
                events.emit(
                    f"trace.{safe_kind.replace('.', '_')}",
                    role="conductor",
                    task_id=work_order["task_id"],
                )

            return trace

        worker_observer = ExternalRunObserver.create(
            self.run_dir / "observability" / f"{_safe_id(work_order['task_id'])}-worker",
            run_id=run_id or mission_contract["mission_id"],
            mission_id=mission_contract["mission_id"],
            task_id=work_order["task_id"],
            stage="worker",
            runtime=self.worker.name,
            model=worker_model,
            registry=self.registry,
        )
        worker_trace = make_trace(worker_observer)

        worker_request = RuntimeRequest(
            role="worker",
            workspace=worktree.path,
            artifact_dir=runtime_dir,
            prompt=build_worker_prompt(work_order, worktree.base_commit),
            output_schema_path=Path(__file__).with_name("schemas") / "runtime-worker-report.schema.json",
            output_schema_id=WORKER_REPORT_SCHEMA_ID,
            title=f"Token Firewall {mission_contract['mission_id']} {work_order['task_id']}",
            model=worker_model,
            timeout_seconds=timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            network_allowed=work_order["assignment"]["network"] == "allowed",
        )
        worker_result = self.worker.execute(worker_request, on_trace=worker_trace)
        worker_stage_result_path = runtime_dir / "stage-result.json"
        atomic_write_json(
            worker_stage_result_path,
            {
                "stage": "worker",
                "runtime": worker_result.runtime,
                "model_requested": worker_model or "runtime-default",
                "model_effective": worker_result.model_effective or worker_model or "runtime-default",
                "model_effective_verified": worker_result.model_effective_verified,
                "session_id": worker_result.session_id,
                "status": worker_result.status.value,
                "usage": worker_result.usage,
                "error": worker_result.error,
            },
        )
        if not worker_result.ok:
            worker_observer.complete(worker_result, payload=worker_stage_result_path)
            events.emit("work.blocked", task_id=work_order["task_id"])
            return RuntimePocResult(
                "RUNTIME_FAILED",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                runtime_error=worker_result.error,
            )

        worker_report = worker_result.final_output or {}
        worker_report_path = runtime_dir / "worker-report.json"
        atomic_write_json(worker_report_path, worker_report)
        worker_commit = worker_report.get("commit") or {}
        worker_observer.complete(
            worker_result,
            payload=worker_report_path,
            delivery={
                "commit": worker_commit.get("head_commit"),
                "changed_files": len(worker_report.get("changed_files_claim", [])),
                "additions": 0,
                "deletions": 0,
            },
        )
        if worker_report["status"] == "NEEDS_REPLAN":
            events.emit(
                "work.replan.proposed",
                role="implementer",
                session_id=worker_result.session_id or self.worker.name,
                task_id=work_order["task_id"],
                payload=worker_report_path,
            )
            events.emit("work.needs_replan", task_id=work_order["task_id"])
            return RuntimePocResult(
                "NEEDS_REPLAN",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
            )
        if worker_report["status"] == "BLOCKED":
            events.emit("work.blocked", task_id=work_order["task_id"], payload=worker_report_path)
            return RuntimePocResult(
                "BLOCKED",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
            )

        events.emit(
            "work.delivery.proposed",
            role="implementer",
            session_id=worker_result.session_id or self.worker.name,
            task_id=work_order["task_id"],
            payload=worker_report_path,
        )
        try:
            sanitization = sanitize_runtime_ephemera(worktree)
            sanitization_path = runtime_dir / "sanitization.json"
            atomic_write_json(sanitization_path, sanitization)
            if sanitization["removed"]:
                events.emit(
                    "trace.runtime_ephemera_sanitized",
                    task_id=work_order["task_id"],
                    payload=sanitization_path,
                )
            if worker_report["status"] == "CHANGES_READY":
                broker_commit_changes(worktree, work_order["task_id"])
            git_delivery = inspect_commit_range(worktree)
        except GitWorktreeError as exc:
            events.emit("work.needs_replan", task_id=work_order["task_id"])
            return RuntimePocResult(
                "NEEDS_REPLAN",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                runtime_error=str(exc),
            )

        claim_findings: list[GateFinding] = []
        claimed_head = (
            worker_report["commit"]["head_commit"]
            if worker_report["status"] == "DELIVERED"
            else git_delivery["head_commit"]
        )
        if claimed_head != git_delivery["head_commit"]:
            claim_findings.append(
                GateFinding(
                    "RUNTIME_COMMIT_CLAIM_MISMATCH",
                    "worker-reported commit differs from worktree HEAD",
                    {"claimed": claimed_head, "actual": git_delivery["head_commit"]},
                )
            )
        claimed_files = sorted(worker_report["changed_files_claim"])
        actual_files = sorted(item["path"] for item in git_delivery["changed_files"])
        if claimed_files != actual_files:
            claim_findings.append(
                GateFinding(
                    "RUNTIME_CHANGED_FILES_CLAIM_MISMATCH",
                    "worker-reported changed files differ from Git",
                    {"claimed": claimed_files, "actual": actual_files},
                )
            )
        if claim_findings:
            events.emit("work.needs_replan", task_id=work_order["task_id"])
            return RuntimePocResult(
                "NEEDS_REPLAN",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                findings=claim_findings,
            )

        patch_path = task_dir / "patch.diff"
        patch_path.write_bytes(git_delivery["patch"])
        manifest = self._build_delivery_manifest(
            work_order,
            worker_report,
            worker_result,
            git_delivery,
            patch_path,
            task_dir,
        )
        manifest_path = task_dir / "delivery-manifest.json"
        atomic_write_json(manifest_path, manifest)
        events.emit("work.delivered", task_id=work_order["task_id"], payload=manifest_path)
        events.emit("test.started", task_id=work_order["task_id"])

        delivery_gate = verify_delivery(
            worktree.path,
            task_dir,
            work_order,
            manifest,
            registry=self.registry,
        )
        gate_path = task_dir / "delivery-gate.json"
        atomic_write_json(gate_path, delivery_gate.to_dict())
        if not delivery_gate.ok:
            events.emit("work.rework", task_id=work_order["task_id"], payload=gate_path)
            return RuntimePocResult(
                "REWORK",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                delivery_manifest=manifest_path,
                findings=delivery_gate.findings,
            )

        if not defer_external_verification:
            events.emit("verification.started", task_id=work_order["task_id"])
            events.emit("work.verified", task_id=work_order["task_id"], payload=gate_path)
            events.emit("mission.integrating")
            events.emit("mission.reviewing")

        final_dir = self.run_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        review_packet = self._build_review_packet(
            mission_contract,
            work_order,
            worker_report,
            git_delivery,
            patch_path,
            manifest_path,
            gate_path,
        )
        review_packet_path = final_dir / "review-packet.json"
        atomic_write_json(review_packet_path, review_packet)
        packet_gate = validate_review_packet(review_packet, self.run_dir, registry=self.registry)
        if not packet_gate.ok:
            events.emit("mission.blocked")
            return RuntimePocResult(
                "PACKET_FAILED",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                delivery_manifest=manifest_path,
                review_packet=review_packet_path,
                findings=packet_gate.findings,
            )

        if self.reviewer is None:
            return RuntimePocResult(
                "REVIEW_READY",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                delivery_manifest=manifest_path,
                review_packet=review_packet_path,
            )

        review_runtime_dir = final_dir / "runtime-reviewer"
        review_observer = ExternalRunObserver.create(
            self.run_dir / "observability" / f"{_safe_id(work_order['task_id'])}-reviewer",
            run_id=run_id or mission_contract["mission_id"],
            mission_id=mission_contract["mission_id"],
            task_id=work_order["task_id"],
            stage="reviewer",
            runtime=self.reviewer.name,
            model=reviewer_model,
            registry=self.registry,
        )
        review_request = RuntimeRequest(
            role="reviewer",
            workspace=worktree.path,
            artifact_dir=review_runtime_dir,
            prompt=build_reviewer_prompt(review_packet_path, git_delivery["head_commit"]),
            output_schema_path=Path(__file__).with_name("schemas") / "review-verdict.schema.json",
            output_schema_id=VERDICT_SCHEMA_ID,
            title=f"Token Firewall review {mission_contract['mission_id']}",
            model=reviewer_model,
            timeout_seconds=timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            network_allowed=False,
        )
        review_result = self.reviewer.execute(review_request, on_trace=make_trace(review_observer))
        review_stage_result_path = review_runtime_dir / "stage-result.json"
        atomic_write_json(
            review_stage_result_path,
            {
                "stage": "reviewer",
                "runtime": review_result.runtime,
                "model_requested": reviewer_model or "runtime-default",
                "model_effective": review_result.model_effective or reviewer_model or "runtime-default",
                "model_effective_verified": review_result.model_effective_verified,
                "session_id": review_result.session_id,
                "status": review_result.status.value,
                "usage": review_result.usage,
                "error": review_result.error,
            },
        )
        if not review_result.ok:
            review_observer.complete(review_result, payload=review_stage_result_path)
            events.emit("mission.blocked")
            return RuntimePocResult(
                "REVIEW_RUNTIME_FAILED",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                delivery_manifest=manifest_path,
                review_packet=review_packet_path,
                runtime_error=review_result.error,
            )
        verdict = review_result.final_output or {}
        verdict_path = final_dir / "review-verdict.json"
        atomic_write_json(verdict_path, verdict)
        review_observer.complete(
            review_result,
            payload=verdict_path,
            delivery={"commit": verdict.get("reviewed_commit"), "changed_files": 0, "additions": 0, "deletions": 0},
        )
        if verdict["reviewed_commit"] != git_delivery["head_commit"]:
            events.emit("mission.blocked")
            return RuntimePocResult(
                "REVIEW_COMMIT_MISMATCH",
                mission_contract["mission_id"],
                work_order["task_id"],
                self.run_dir,
                worktree=worktree.path,
                delivery_manifest=manifest_path,
                review_packet=review_packet_path,
                review_verdict=verdict_path,
            )
        events.emit(
            "review.verdict.proposed",
            role="chief-reviewer",
            session_id=review_result.session_id or self.reviewer.name,
            task_id=work_order["task_id"],
            payload=verdict_path,
        )
        if verdict["verdict"] == "PASS":
            events.emit("work.accepted", task_id=work_order["task_id"], payload=verdict_path)
            events.emit("mission.passed", payload=verdict_path)
            final_status = "PASSED"
        elif verdict["verdict"] == "REWORK":
            events.emit("work.rework", task_id=work_order["task_id"], payload=verdict_path)
            final_status = "REWORK"
        else:
            events.emit("mission.needs_user_decision", payload=verdict_path)
            final_status = "NEEDS_USER_DECISION"
        return RuntimePocResult(
            final_status,
            mission_contract["mission_id"],
            work_order["task_id"],
            self.run_dir,
            worktree=worktree.path,
            delivery_manifest=manifest_path,
            review_packet=review_packet_path,
            review_verdict=verdict_path,
        )

    def _build_delivery_manifest(
        self,
        work_order: dict[str, Any],
        report: dict[str, Any],
        runtime_result: Any,
        git_delivery: dict[str, Any],
        patch_path: Path,
        task_dir: Path,
    ) -> dict[str, Any]:
        # Runtime metering is authoritative. A Worker-authored usage claim is
        # untrusted and must never become the benchmark fact source.
        usage = runtime_result.usage if isinstance(runtime_result.usage, dict) else {}
        approved_commands = {
            spec["validator"]["command"]
            for spec in work_order["acceptance_specs"]
            if spec["validator"]["kind"] == "command"
        }
        manifest: dict[str, Any] = {
            "schema": "token-firewall/delivery-manifest@0.1",
            "object_id": f"dm_{_safe_id(work_order['task_id'])}_r1",
            "mission_id": work_order["mission_id"],
            "revision": 1,
            "created_at": _now(),
            "created_by": {
                "role": "implementer",
                "runtime": runtime_result.runtime,
                "model": str(runtime_result.model_effective or runtime_result.runtime),
                "session_id": runtime_result.session_id or runtime_result.runtime,
            },
            "content_sha256": "0" * 64,
            "task_id": work_order["task_id"],
            "attempt": 1,
            "base_commit": git_delivery["base_commit"],
            "head_commit": git_delivery["head_commit"],
            "patch": _evidence_ref(task_dir, patch_path, mime_type="text/x-diff"),
            "changed_files": git_delivery["changed_files"],
            "spec_results": [
                {
                    "spec_id": item["spec_id"],
                    "status": item["status"],
                    "evidence_ref": f"runtime-worker/worker-report.json#{item['spec_id']}",
                }
                for item in report["spec_results"]
            ],
            "tests": [
                {
                    "command": item["command"],
                    "exit_code": item["exit_code"],
                    "evidence_ref": "runtime-worker/worker-report.json",
                }
                for item in report["tests"]
                if item["command"] in approved_commands
            ],
            "deviations": report["deviations"],
            "uncertainties": report["uncertainties"],
            "failed_attempts_summary": report["failed_attempts_summary"],
            "artifacts": [],
            "usage": {
                "model": str(runtime_result.model_effective or runtime_result.runtime),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read_tokens": usage.get("cache_read_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "cost_usd": usage.get("cost_usd", 0),
                "usage_source": usage.get("source", "unknown"),
                "usage_complete": bool(usage.get("complete", False)),
                "native_total_tokens": usage.get("native_total_tokens", usage.get("total_tokens", 0)),
            },
            "worker_proposal": "DELIVERED",
        }
        return _seal(manifest)

    def _build_review_packet(
        self,
        mission: dict[str, Any],
        work_order: dict[str, Any],
        report: dict[str, Any],
        git_delivery: dict[str, Any],
        patch_path: Path,
        manifest_path: Path,
        gate_path: Path,
    ) -> dict[str, Any]:
        patch_ref = _evidence_ref(self.run_dir, patch_path, mime_type="text/x-diff")
        manifest_ref = _evidence_ref(self.run_dir, manifest_path)
        gate_ref = _evidence_ref(self.run_dir, gate_path)
        additions = sum(item["additions"] for item in git_delivery["changed_files"])
        deletions = sum(item["deletions"] for item in git_delivery["changed_files"])
        packet: dict[str, Any] = {
            "schema": "token-firewall/review-packet@0.1",
            "object_id": f"rp_{_safe_id(mission['mission_id'])}_r1",
            "mission_id": mission["mission_id"],
            "revision": 1,
            "created_at": _now(),
            "created_by": {
                "role": "packetizer",
                "runtime": "token-firewall",
                "model": "deterministic",
                "session_id": "conductor",
            },
            "content_sha256": "0" * 64,
            "scope": "mission",
            "mission_summary": mission["goal"][:4000],
            "risk": {"level": work_order["risk"]["level"], "reasons": work_order["risk"]["reasons"]},
            "commit_range": {"base": git_delivery["base_commit"], "head": git_delivery["head_commit"]},
            "diff_summary": {
                "files": len(git_delivery["changed_files"]),
                "additions": additions,
                "deletions": deletions,
                "patch_ref": patch_ref,
            },
            "context_slices": report["context_slices"],
            "requirements_coverage": [
                {
                    "spec_id": spec["id"],
                    "status": "pass",
                    "evidence_ref": f"{gate_ref['path']}#test_reruns",
                }
                for spec in work_order["acceptance_specs"]
            ],
            "unresolved_disagreements": [],
            "previous_review_delta": None,
            "evidence_index": [patch_ref, manifest_ref, gate_ref],
            "packet_budget": {
                "estimated_tokens": 0,
                "max_tokens": mission["sol_token_budget"]["review_max"],
            },
            "integration_commit": git_delivery["head_commit"],
            "included_tasks": [
                {"task_id": work_order["task_id"], "delivery_manifest_ref": manifest_ref}
            ],
            "full_regression": {"status": "pass", "evidence_ref": gate_ref},
            "unresolved_risks": [*report["deviations"], *report["uncertainties"]],
        }
        if work_order["schema"] == "token-firewall/work-order@0.2":
            packet["acceptance_contract"] = [
                {
                    "spec_id": spec["id"],
                    "statement": spec["statement"],
                    "positive_cases": [
                        {"case_id": case["case_id"], "action": case["action"], "expected": case["expected"]}
                        for case in spec["positive_cases"]
                    ],
                    "negative_cases": [
                        {"case_id": case["case_id"], "action": case["action"], "expected_rejection": case["expected_rejection"]}
                        for case in spec["negative_cases"]
                    ],
                    "semantic_boundaries": spec["semantic_boundaries"],
                }
                for spec in work_order["acceptance_specs"]
            ]
        for _ in range(4):
            _seal(packet)
            estimate = estimate_packet_tokens(packet)
            if packet["packet_budget"]["estimated_tokens"] == estimate:
                break
            packet["packet_budget"]["estimated_tokens"] = estimate
        return _seal(packet)
