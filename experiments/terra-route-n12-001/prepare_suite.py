from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT / "pilot-repo"
DEFINITIONS = ROOT / "definitions"
HIDDEN = ROOT / "hidden"
CREATED_AT = "2026-07-12T15:00:00+08:00"
MANIFEST_CREATED_AT = "2026-07-12T14:47:59+08:00"


TASKS = [
    {
        "number": 3, "slug": "duration", "risk": "low", "type": "feature",
        "goal": "实现严格、无歧义并带上限的紧凑时长解析。",
        "objective": "实现 parse_duration，解析 ms/s/m/h ASCII 语法并对非法、零值、前导零和越界输入失败关闭。",
        "validator": "python3 -m unittest tests.test_tasks.ParseDurationTests -v",
        "positive": ["parse_duration('250ms') 返回 250", "parse_duration('3m') 返回 180000"],
        "negative": ["'02s'、全角数字、零值与超过 max_milliseconds 的值抛出 ValueError"],
        "boundary": "原始值必须匹配 [1-9][0-9]*(ms|s|m|h)，换算值不得超过显式上限。",
    },
    {
        "number": 4, "slug": "canonical-query", "risk": "medium", "type": "feature",
        "goal": "生成可用于签名的确定性 RFC3986 查询串。",
        "objective": "实现 canonical_query：严格字符串二元组、UTF-8 百分号编码、按编码后 key/value 排序并保留重复项。",
        "validator": "python3 -m unittest tests.test_tasks.CanonicalQueryTests -v",
        "positive": ["空格编码为 %20、斜线编码为 %2F、~ 保留", "重复 key 全部保留并按编码值排序"],
        "negative": ["非字符串 key/value、畸形 pair 或 None 抛出 TypeError/ValueError"],
        "boundary": "排序发生在 RFC3986 编码之后；不得使用 application/x-www-form-urlencoded 的 + 空格语义。",
    },
    {
        "number": 5, "slug": "stable-unique", "risk": "low", "type": "refactor",
        "goal": "提供稳定、适用于不可哈希对象的去重函数。",
        "objective": "重构 stable_unique，按相等性保留第一次出现顺序并支持生成器和不可哈希值。",
        "validator": "python3 -m unittest tests.test_tasks.StableUniqueTests -v",
        "positive": ["['b','a','b'] 返回 ['b','a']", "[[1],[1],[2]] 返回 [[1],[2]]"],
        "negative": ["None 等不可迭代输入抛出 TypeError"],
        "boundary": "重复判定使用 Python 相等性；输出不得重排且不得要求元素可哈希。",
    },
    {
        "number": 6, "slug": "deep-merge", "risk": "medium", "type": "refactor",
        "goal": "无副作用地合并嵌套配置树。",
        "objective": "实现 deep_merge：仅映射递归合并，其他值由 override 深拷贝替换，结果与输入不共享可变对象。",
        "validator": "python3 -m unittest tests.test_tasks.DeepMergeTests -v",
        "positive": ["嵌套映射保留未覆盖 key 并覆盖指定 key", "列表整体替换而非连接"],
        "negative": ["根对象不是 dict 时抛出 TypeError"],
        "boundary": "只有两侧值均为 dict 才递归；所有输出分支必须深拷贝，输入保持不变。",
    },
    {
        "number": 7, "slug": "pagination", "risk": "medium", "type": "integration",
        "goal": "可靠地消费游标分页接口而不无限循环。",
        "objective": "实现 collect_pages：从 None 游标开始，按序聚合 items，在 next_cursor=None 结束，并拒绝循环、畸形响应和页数越界。",
        "validator": "python3 -m unittest tests.test_tasks.CollectPagesTests -v",
        "positive": ["依次请求 None、a、b 并按页序返回所有 items"],
        "negative": ["重复游标、非列表 items、空游标或超过 max_pages 抛出错误"],
        "boundary": "只有 None 表示终止；继续游标必须是非空字符串且每次唯一。",
    },
    {
        "number": 8, "slug": "retry-after", "risk": "medium", "type": "integration",
        "goal": "正确解释 HTTP Retry-After 的秒数和日期形式。",
        "objective": "实现 parse_retry_after：支持 ASCII 十进制秒数与 IMF-fixdate，过去日期归零，并按 max_delay 截断。",
        "validator": "python3 -m unittest tests.test_tasks.RetryAfterTests -v",
        "positive": ["'120' 与两分钟后的 GMT 日期都返回 120", "超大延迟截断到 max_delay"],
        "negative": ["负数、加号、小数、Unicode 数字和无效日期抛出错误"],
        "boundary": "只修剪 ASCII SP/HTAB；now 必须是 aware datetime，日期按 UTC 秒向上取整。",
    },
    {
        "number": 9, "slug": "safe-join", "risk": "high", "type": "bugfix",
        "goal": "阻止路径穿越和符号链接逃逸。",
        "objective": "加固 safe_join：仅接受非空相对路径，解析后必须仍在真实 base 目录内，并拒绝绝对路径、.. 与 symlink escape。",
        "validator": "python3 -m unittest tests.test_tasks.SafeJoinTests -v",
        "positive": ["base 内的 a/file.txt 返回规范绝对 Path"],
        "negative": ["../、绝对路径、空路径和指向外部的 symlink 抛出 ValueError"],
        "boundary": "使用路径组件的包含关系而非字符串前缀；base 必须是已存在目录。",
    },
    {
        "number": 10, "slug": "merge-patch", "risk": "medium", "type": "feature",
        "goal": "实现无副作用的 RFC 7396 JSON Merge Patch 子集。",
        "objective": "实现 merge_patch：对象递归合并、null 删除成员、非对象 patch 整体替换，并深拷贝结果。",
        "validator": "python3 -m unittest tests.test_tasks.MergePatchTests -v",
        "positive": ["嵌套对象更新且 null 删除成员", "数组 patch 整体替换目标"],
        "negative": ["不得修改或别名引用 target/patch 中的可变对象"],
        "boundary": "只有 patch 为 dict 时进入对象语义；target 非 dict 时视为空对象。",
    },
    {
        "number": 11, "slug": "topological-order", "risk": "medium", "type": "refactor",
        "goal": "稳定地排序依赖图并拒绝不完整或循环图。",
        "objective": "实现 topological_order：依赖先于使用者、无依赖平局遵循输入顺序，并检测 cycle、缺失节点和畸形依赖列表。",
        "validator": "python3 -m unittest tests.test_tasks.TopologicalOrderTests -v",
        "positive": ["lint/compile 先于 test/build", "独立节点保持映射插入顺序"],
        "negative": ["循环、self-cycle、缺失依赖、非列表依赖或重复依赖抛出错误"],
        "boundary": "图必须是 str 到唯一 str 列表的映射；稳定性以输入节点与依赖顺序为准。",
    },
    {
        "number": 12, "slug": "read-through-cache", "risk": "medium", "type": "integration",
        "goal": "原子地读取或填充带 TTL 的缓存。",
        "objective": "实现 read_through_cache：expires_at>now 才命中，过期时调用 loader，并仅在 loader 成功且 TTL 合法后提交缓存。",
        "validator": "python3 -m unittest tests.test_tasks.ReadThroughCacheTests -v",
        "positive": ["新鲜值不调用 loader", "边界过期值重新加载并写入 now+ttl"],
        "negative": ["loader 异常、畸形返回、零/布尔 TTL 不得改变 cache"],
        "boundary": "expires_at 等于 now 已过期；TTL 必须是非布尔正整数，写入是最后一步。",
    },
]


def canonical_sha256(value: object) -> str:
    if isinstance(value, dict):
        value = {key: item for key, item in value.items() if key != "content_sha256"}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def seal(value: dict) -> dict:
    value["content_sha256"] = canonical_sha256(value)
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()
    if len(base_sha) != 40:
        raise SystemExit("pilot repo needs a full base commit")
    DEFINITIONS.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "token-firewall/task-suite-manifest@0.1", "base_sha": base_sha, "tasks": []}
    for item in TASKS:
        number = item["number"]
        task_id = f"T-EVAL-{number:02d}"
        mission_id = f"msn_eval_{number:02d}_001"
        mission = seal({
            "schema": "token-firewall/mission-contract@0.1",
            "object_id": f"mc_eval_{number:02d}",
            "mission_id": mission_id,
            "revision": 1,
            "created_at": CREATED_AT,
            "created_by": {"role": "mission-architect", "runtime": "codex", "model": "gpt-5.6-sol", "session_id": "suite-design-frozen"},
            "content_sha256": "0" * 64,
            "goal": item["goal"],
            "success_outcomes": [{"id": "OUT-001", "statement": item["objective"], "evidence": "公开测试、独立验证、匿名终审与延后隐藏测试通过"}],
            "invariants": [{"id": "INV-001", "statement": "不得修改公开测试或任务范围外文件，且实现不得引入第三方依赖", "severity": "critical"}],
            "non_goals": ["不修改其他基准函数", "不修改公开测试", "不引入第三方依赖"],
            "risk_boundaries": [{"pattern": item["boundary"], "review_level": "sol-deep-review" if item["risk"] == "high" else "terra-then-sol"}],
            "approval_boundaries": {"external_writes": False, "destructive_actions": False, "scope_expansion": False},
            "overall_acceptance": ["OUT-001", "INV-001"],
            "sol_token_budget": {"planning_max": 12_000, "review_max": 90_000 if item["risk"] != "high" else 140_000, "escalation_requires_reason": True},
        })
        work_order = seal({
            "schema": "token-firewall/work-order@0.2",
            "object_id": f"wo_T_EVAL_{number:02d}_r1",
            "mission_id": mission_id,
            "revision": 1,
            "created_at": CREATED_AT,
            "created_by": {"role": "decomposition-lead", "runtime": "codex", "model": "gpt-5.6-sol", "session_id": "suite-design-frozen"},
            "content_sha256": "0" * 64,
            "task_id": task_id,
            "parent_task_id": None,
            "objective": item["objective"],
            "rationale": f"补齐 {item['risk']} 风险 {item['type']} 分层，扩展配对质量—Token 证据。",
            "dependencies": [],
            "context_refs": [],
            "allowed_paths": ["src/tasks.py"],
            "forbidden_paths": ["tests/**", "src/__init__.py"],
            "invariants": ["INV-001"],
            "acceptance_specs": [{
                "id": f"SPEC-{number:02d}-001",
                "statement": item["objective"],
                "validator": {"kind": "command", "command": item["validator"], "timeout_seconds": 30},
                "positive_cases": [
                    {"case_id": f"POS-{number:02d}-{index:03d}", "setup": value, "action": "调用目标函数", "expected": "得到合同指定结果"}
                    for index, value in enumerate(item["positive"], 1)
                ],
                "negative_cases": [
                    {"case_id": f"NEG-{number:02d}-{index:03d}", "setup": value, "action": "调用目标函数", "expected_rejection": "失败关闭且不产生部分副作用"}
                    for index, value in enumerate(item["negative"], 1)
                ],
                "semantic_boundaries": [{"boundary_id": f"BOUND-{number:02d}-001", "dimension": "任务语义边界", "inside": item["positive"][0], "outside": item["negative"][0], "rule": item["boundary"]}],
            }],
            "required_deliverables": ["git_commit", "patch", "test_results"],
            "limits": {"max_changed_files": 1, "max_diff_lines": 180, "max_rework_rounds": 1, "wall_clock_minutes": 25},
            "stop_conditions": ["需要修改公开测试或其他源文件", "需要增加第三方依赖", "Diff 超过 180 行"],
            "risk": {"level": item["risk"], "reasons": [item["boundary"]], "required_review": "sol-deep-review" if item["risk"] == "high" else "terra-then-sol"},
            "assignment": {"preferred_model": "benchmark-assigned", "workspace_mode": "isolated-worktree", "network": "deny-by-default"},
        })
        write_json(DEFINITIONS / f"task-{number:02d}-mission.json", mission)
        write_json(DEFINITIONS / f"task-{number:02d}-work-order.json", work_order)
        for group in ("C", "D"):
            attempt = 2 if number == 3 and group == "C" else 1
            write_json(DEFINITIONS / f"task-{number:02d}-identity-{group.lower()}.json", {
                "run_id": f"run_eval_{number:02d}_{group.lower()}_{attempt:03d}",
                "group_id": group,
                "task_revision": 1,
                "base_sha": base_sha,
            })
        hidden = HIDDEN / f"task_{number:02d}_{item['slug'].replace('-', '_')}_hidden.py"
        if not hidden.exists():
            raise SystemExit(f"missing hidden suite: {hidden}")
        manifest["tasks"].append({
            "task_id": task_id,
            "slug": item["slug"],
            "risk": item["risk"],
            "task_type": item["type"],
            "mission": f"definitions/task-{number:02d}-mission.json",
            "work_order": f"definitions/task-{number:02d}-work-order.json",
            "identity_control": f"definitions/task-{number:02d}-identity-d.json",
            "identity_experiment": f"definitions/task-{number:02d}-identity-c.json",
            "hidden_test": str(hidden.relative_to(ROOT)),
            "hidden_suite_sha256": hashlib.sha256(hidden.read_bytes()).hexdigest(),
            "validator": item["validator"],
        })
    manifest["created_at"] = MANIFEST_CREATED_AT
    manifest["content_sha256"] = canonical_sha256(manifest)
    write_json(ROOT / "suite-manifest.json", manifest)
    print(json.dumps({"base_sha": base_sha, "tasks": len(TASKS), "manifest": str(ROOT / "suite-manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
