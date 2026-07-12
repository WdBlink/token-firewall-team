from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from tools.token_firewall.schema import canonical_sha256


NOW = "2026-07-10T16:00:00+08:00"
SHA = "0" * 64
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def seal(value: dict[str, Any]) -> dict[str, Any]:
    value["content_sha256"] = canonical_sha256(value)
    return value


def creator(role: str = "decomposition-lead") -> dict[str, str]:
    return {
        "role": role,
        "runtime": "codex",
        "model": "test-model",
        "session_id": "session-test",
    }


def header(kind: str, object_id: str, role: str = "decomposition-lead") -> dict[str, Any]:
    return {
        "schema": f"token-firewall/{kind}@0.1",
        "object_id": object_id,
        "mission_id": "msn_test",
        "revision": 1,
        "created_at": NOW,
        "created_by": creator(role),
        "content_sha256": SHA,
    }


def mission_contract() -> dict[str, Any]:
    return seal({
        **header("mission-contract", "mc_test", "mission-architect"),
        "goal": "交付一个可以机械验证的 Token 防火墙协议原型",
        "success_outcomes": [
            {"id": "OUT-001", "statement": "协议对象可以校验", "evidence": "自动化测试通过"}
        ],
        "invariants": [
            {"id": "INV-001", "statement": "Worker 不能自行接受任务", "severity": "critical"}
        ],
        "non_goals": ["不调用真实模型"],
        "risk_boundaries": [
            {"pattern": "鉴权或资金变更", "review_level": "sol-deep-review"}
        ],
        "approval_boundaries": {
            "external_writes": False,
            "destructive_actions": False,
            "scope_expansion": False,
        },
        "overall_acceptance": ["OUT-001", "INV-001"],
        "sol_token_budget": {
            "planning_max": 12000,
            "review_max": 30000,
            "escalation_requires_reason": True,
        },
    })


def work_order(
    task_id: str = "T-001",
    *,
    dependencies: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    command: str = "python3 -c 'raise SystemExit(0)'",
) -> dict[str, Any]:
    return seal({
        **header("work-order", f"wo_{task_id.replace('-', '_')}_r1"),
        "task_id": task_id,
        "parent_task_id": None,
        "objective": "实现一个可以观察和机械验收的独立行为",
        "rationale": "它直接覆盖 Mission Contract 的 OUT-001",
        "dependencies": dependencies or [],
        "context_refs": [],
        "allowed_paths": allowed_paths or ["src/**"],
        "forbidden_paths": [".github/**", "migrations/**"],
        "invariants": ["INV-001"],
        "acceptance_specs": [
            {
                "id": f"SPEC-{task_id[2:]}-01",
                "statement": "批准的验证命令必须成功退出",
                "validator": {"kind": "command", "command": command, "timeout_seconds": 30},
            }
        ],
        "required_deliverables": ["git_commit", "patch", "test_results"],
        "limits": {
            "max_changed_files": 5,
            "max_diff_lines": 300,
            "max_rework_rounds": 2,
            "wall_clock_minutes": 45,
        },
        "stop_conditions": ["需要修改 forbidden_paths", "Diff 预计超过上限"],
        "risk": {
            "level": "low",
            "reasons": ["局部文件变更"],
            "required_review": "m3-then-sol",
        },
        "assignment": {
            "preferred_model": "MiniMax-M3",
            "workspace_mode": "isolated-worktree",
            "network": "deny-by-default",
        },
    })


def work_order_v02(*, risk: str = "low", command: str = "python3 -c 'raise SystemExit(0)'") -> dict[str, Any]:
    value = deepcopy(work_order(command=command))
    value["schema"] = "token-firewall/work-order@0.2"
    value["risk"] = {
        "level": risk,
        "reasons": ["用于验证新版验收合同"],
        "required_review": {
            "low": "m3-then-sol",
            "medium": "terra-then-sol",
            "high": "sol-deep-review",
            "critical": "sol-deep-review",
        }[risk],
    }
    spec = value["acceptance_specs"][0]
    spec["positive_cases"] = [{
        "case_id": "POS-001", "setup": "输入合法任务", "action": "运行批准命令", "expected": "命令成功退出",
    }]
    spec["negative_cases"] = [{
        "case_id": "NEG-001", "setup": "输入非法任务", "action": "运行批准命令", "expected_rejection": "命令非零退出或明确拒绝",
    }]
    spec["semantic_boundaries"] = [{
        "boundary_id": "BOUND-001", "dimension": "任务合法性", "inside": "满足冻结契约", "outside": "违反冻结契约", "rule": "只接受契约内部行为",
    }]
    return seal(value)


def delivery_manifest(base: str = "a" * 40, head: str = "b" * 40) -> dict[str, Any]:
    return seal({
        **header("delivery-manifest", "dm_T_001_r1", "implementer"),
        "task_id": "T-001",
        "attempt": 1,
        "base_commit": base,
        "head_commit": head,
        "patch": {"path": "patch.diff", "sha256": SHA, "bytes": 0},
        "changed_files": [
            {"path": "src/app.txt", "status": "modified", "additions": 1, "deletions": 1}
        ],
        "spec_results": [
            {"spec_id": "SPEC-001-01", "status": "pass", "evidence_ref": "spec-results.json#SPEC-001-01"}
        ],
        "tests": [
            {"command": "python3 -m unittest", "exit_code": 0, "evidence_ref": "test-results/unittest.json"}
        ],
        "deviations": [],
        "uncertainties": [],
        "failed_attempts_summary": [],
        "artifacts": [],
        "usage": {
            "model": "MiniMax-M3",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 0,
            "total_tokens": 150,
            "native_total_tokens": 150,
            "cost_usd": 0.001,
            "usage_source": "fixture",
            "usage_complete": True,
        },
        "worker_proposal": "DELIVERED",
    })


def task_review_packet(reference: dict[str, Any] | None = None) -> dict[str, Any]:
    reference = reference or {"path": "patch.diff", "sha256": SHA, "bytes": 0}
    return seal({
        **header("review-packet", "rp_T_001_r1", "packetizer"),
        "scope": "task",
        "task_id": "T-001",
        "mission_summary": "实现并验证一个低风险的局部行为。",
        "objective": "实现一个可以观察和机械验收的独立行为",
        "risk": {"level": "low", "reasons": ["局部文件变更"]},
        "commit_range": {"base": "a" * 40, "head": "b" * 40},
        "diff_summary": {"files": 1, "additions": 1, "deletions": 1, "patch_ref": reference},
        "context_slices": [
            {"path": "src/app.txt", "start": 1, "end": 20, "reason": "修改位置及相邻不变量"}
        ],
        "requirements_coverage": [
            {"spec_id": "SPEC-001-01", "status": "pass", "evidence_ref": "spec-results.json#SPEC-001-01"}
        ],
        "verifier_findings": [],
        "unresolved_disagreements": [],
        "previous_review_delta": None,
        "evidence_index": [reference],
        "packet_budget": {"estimated_tokens": 100000, "max_tokens": 100000},
    })


def verdict(value: str = "PASS") -> dict[str, Any]:
    return {
        "schema": "token-firewall/review-verdict@0.1",
        "verdict": value,
        "reviewed_commit": "b" * 40,
        "findings": [],
        "coverage_gaps": [],
        "residual_risks": [],
        "requested_context": [],
        "escalation_reason": "not_applicable",
        "reviewer": {"model": "gpt-5.6-sol", "session_id": "review-test"},
    }


def runtime_worker_report(
    head_commit: str = "b" * 40,
    *,
    status: str = "DELIVERED",
    command: str = "python3 -c 'raise SystemExit(0)'",
) -> dict[str, Any]:
    delivered = status == "DELIVERED"
    changes_ready = status == "CHANGES_READY"
    return {
        "schema": "token-firewall/runtime-worker-report@0.1",
        "status": status,
        "summary": "完成一个局部、可机械验收的行为",
        "spec_results": [
            {
                "spec_id": "SPEC-001-01",
                "status": "pass" if delivered or changes_ready else "blocked",
                "evidence_summary": "批准的命令已执行",
            }
        ],
        "tests": [
            {"command": command, "exit_code": 0 if delivered or changes_ready else 1, "summary": "测试结果摘要"}
        ],
        "deviations": [],
        "uncertainties": [],
        "failed_attempts_summary": [],
        "changed_files_claim": ["src/app.txt"] if delivered or changes_ready else [],
        "context_slices": [
            {"path": "src/app.txt", "start": 1, "end": 2, "reason": "修改的行为位置"}
        ] if delivered or changes_ready else [],
        "commit": {"head_commit": head_commit, "message": "implement runtime POC task"} if delivered else None,
        "blockers": [] if delivered or changes_ready else ["需要重新拆解任务"],
        "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 0, "cost_usd": 0.001},
    }


def event(
    event_id: str,
    kind: str,
    *,
    role: str = "conductor",
    task_id: str | None = None,
    evidence: bool = False,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": "token-firewall/event@0.1",
        "event_id": event_id,
        "mission_id": "msn_test",
        "task_id": task_id,
        "at": NOW,
        "producer": {"role": role, "session_id": "session-test"},
        "kind": kind,
    }
    if evidence:
        value.update({"payload_ref": "evidence/object.json", "payload_sha256": EMPTY_SHA})
    return value
