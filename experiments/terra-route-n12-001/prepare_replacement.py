from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT / "replacement-repo"
DEFINITIONS = ROOT / "definitions"
CREATED_AT = "2026-07-12T15:30:00+08:00"


def digest(value: dict) -> str:
    payload = {key: item for key, item in value.items() if key != "content_sha256"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seal(value: dict) -> dict:
    value["content_sha256"] = digest(value)
    return value


def write(name: str, value: dict) -> None:
    (DEFINITIONS / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def main() -> None:
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, text=True, capture_output=True).stdout.strip()
    mission = seal({
        "schema": "token-firewall/mission-contract@0.1", "object_id": "mc_eval_13", "mission_id": "msn_eval_13_001", "revision": 1,
        "created_at": CREATED_AT, "created_by": {"role": "mission-architect", "runtime": "codex", "model": "gpt-5.6-sol", "session_id": "replacement-design-frozen"},
        "content_sha256": "0" * 64, "goal": "实现适用于一次性迭代器的稳定批处理函数。",
        "success_outcomes": [{"id": "OUT-001", "statement": "按固定正整数 size 保序分批且不产生空尾批", "evidence": "公开测试、匿名终审与延后隐藏测试通过"}],
        "invariants": [{"id": "INV-001", "statement": "不得修改测试或引入第三方依赖", "severity": "critical"}],
        "non_goals": ["不实现异步迭代", "不修改测试"],
        "risk_boundaries": [{"pattern": "size 必须是非布尔正整数；输入只能消费一次；空输入返回空列表", "review_level": "terra-then-sol"}],
        "approval_boundaries": {"external_writes": False, "destructive_actions": False, "scope_expansion": False},
        "overall_acceptance": ["OUT-001", "INV-001"], "sol_token_budget": {"planning_max": 8000, "review_max": 90000, "escalation_requires_reason": True},
    })
    order = seal({
        "schema": "token-firewall/work-order@0.2", "object_id": "wo_T_EVAL_13_r1", "mission_id": "msn_eval_13_001", "revision": 1,
        "created_at": CREATED_AT, "created_by": {"role": "decomposition-lead", "runtime": "codex", "model": "gpt-5.6-sol", "session_id": "replacement-design-frozen"},
        "content_sha256": "0" * 64, "task_id": "T-EVAL-13", "parent_task_id": None,
        "objective": "实现 batch_items：保序分批、支持一次性 iterable、保留短尾批，并严格验证 size。",
        "rationale": "替换一个在隐藏边界审计中被判定为合同不足的无效样本，不覆盖原始失败记录。",
        "dependencies": [], "context_refs": [], "allowed_paths": ["src/batching.py"], "forbidden_paths": ["tests/**"], "invariants": ["INV-001"],
        "acceptance_specs": [{
            "id": "SPEC-13-001", "statement": "按非布尔正整数 size 将 iterable 保序切分为 list[list]，空输入无批次且无空尾批。",
            "validator": {"kind": "command", "command": "python3 -m unittest tests.test_batching.BatchItemsTests -v", "timeout_seconds": 30},
            "positive_cases": [{"case_id": "POS-13-001", "setup": "[1,2,3,4,5] 且 size=2", "action": "batch_items", "expected": "[[1,2],[3,4],[5]]"}, {"case_id": "POS-13-002", "setup": "一次性生成器且 size=3", "action": "batch_items", "expected": "只消费一次并保序分批"}],
            "negative_cases": [{"case_id": "NEG-13-001", "setup": "size 为 0、负数、布尔或非整数", "action": "batch_items", "expected_rejection": "抛出 TypeError/ValueError 且不返回部分结果"}],
            "semantic_boundaries": [{"boundary_id": "BOUND-13-001", "dimension": "批次大小与迭代边界", "inside": "size 是非布尔正整数，values 可迭代", "outside": "size 非法或 values 不可迭代", "rule": "每个非尾批长度等于 size，尾批只在有元素时存在，输入仅迭代一次"}],
        }],
        "required_deliverables": ["git_commit", "patch", "test_results"], "limits": {"max_changed_files": 1, "max_diff_lines": 100, "max_rework_rounds": 1, "wall_clock_minutes": 20},
        "stop_conditions": ["需要修改测试", "需要第三方依赖"], "risk": {"level": "low", "reasons": ["局部无副作用迭代逻辑"], "required_review": "terra-then-sol"},
        "assignment": {"preferred_model": "benchmark-assigned", "workspace_mode": "isolated-worktree", "network": "deny-by-default"},
    })
    write("task-13-mission.json", mission)
    write("task-13-work-order.json", order)
    for group in ("C", "D"):
        write(f"task-13-identity-{group.lower()}.json", {"run_id": f"run_eval_13_{group.lower()}_001", "group_id": group, "task_revision": 1, "base_sha": base})
    print(base)


if __name__ == "__main__":
    main()
