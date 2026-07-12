from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .schema import SchemaRegistry, SchemaValidationError, canonical_json_bytes


@dataclass(frozen=True)
class GateFinding:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    findings: list[GateFinding] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.findings

    def add(self, code: str, message: str, **details: Any) -> None:
        self.findings.append(GateFinding(code, message, details))

    def merge(self, other: "GateResult") -> None:
        self.findings.extend(other.findings)
        self.evidence.update(other.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "findings": [
                {"code": finding.code, "message": finding.message, "details": finding.details}
                for finding in self.findings
            ],
            "evidence": self.evidence,
        }


def _normalise_repo_path(path: str) -> str | None:
    if not path or path.startswith("/") or "\\" in path:
        return None
    pure = PurePosixPath(path)
    if ".." in pure.parts:
        return None
    normalised = pure.as_posix()
    if normalised in {".", ""}:
        return None
    return normalised.removeprefix("./")


def _matches(path: str, pattern: str) -> bool:
    pattern = pattern.removeprefix("./")
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern)


def _static_prefix(pattern: str) -> str:
    wildcard_positions = [position for token in "*?[" if (position := pattern.find(token)) >= 0]
    if not wildcard_positions:
        return pattern
    return pattern[: min(wildcard_positions)].rstrip("/")


def patterns_overlap(left: str, right: str) -> bool:
    """Conservative overlap check for repository path globs.

    False positives are acceptable at the planning gate because the safe response is to
    serialize or refine Work Orders. False negatives would let parallel workers write the
    same area.
    """

    left = left.removeprefix("./")
    right = right.removeprefix("./")
    left_has_glob = any(token in left for token in "*?[")
    right_has_glob = any(token in right for token in "*?[")
    if not left_has_glob and not right_has_glob:
        return left == right
    if not left_has_glob:
        return _matches(left, right)
    if not right_has_glob:
        return _matches(right, left)
    left_prefix = _static_prefix(left)
    right_prefix = _static_prefix(right)
    if not left_prefix or not right_prefix:
        return True
    return (
        left_prefix == right_prefix
        or left_prefix.startswith(right_prefix.rstrip("/") + "/")
        or right_prefix.startswith(left_prefix.rstrip("/") + "/")
    )


def validate_work_order_graph(work_orders: Iterable[dict[str, Any]]) -> GateResult:
    result = GateResult()
    orders = list(work_orders)
    by_id: dict[str, dict[str, Any]] = {}
    for order in orders:
        task_id = order.get("task_id")
        if not isinstance(task_id, str):
            result.add("DAG_TASK_ID_MISSING", "every Work Order needs a task_id")
            continue
        if task_id in by_id:
            result.add("DAG_DUPLICATE_TASK", f"duplicate task id: {task_id}", task_id=task_id)
        by_id[task_id] = order

    for task_id, order in by_id.items():
        for dependency in order.get("dependencies", []):
            if dependency not in by_id:
                result.add(
                    "DAG_DEPENDENCY_MISSING",
                    f"{task_id} depends on unknown task {dependency}",
                    task_id=task_id,
                    dependency=dependency,
                )
        for allowed in order.get("allowed_paths", []):
            for forbidden in order.get("forbidden_paths", []):
                if patterns_overlap(allowed, forbidden):
                    result.add(
                        "PATH_POLICY_OVERLAP",
                        f"{task_id} has overlapping allow/forbid patterns",
                        task_id=task_id,
                        allowed=allowed,
                        forbidden=forbidden,
                    )

    indegree = {task_id: 0 for task_id in by_id}
    dependents = {task_id: [] for task_id in by_id}
    for task_id, order in by_id.items():
        for dependency in order.get("dependencies", []):
            if dependency in by_id:
                indegree[task_id] += 1
                dependents[dependency].append(task_id)
    queue = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    topological: list[str] = []
    while queue:
        task_id = queue.pop(0)
        topological.append(task_id)
        for dependent in dependents[task_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
                queue.sort()
    if len(topological) != len(by_id):
        cyclic = sorted(task_id for task_id, degree in indegree.items() if degree > 0)
        result.add("DAG_CYCLE", "dependency graph contains a cycle", tasks=cyclic)
    else:
        result.evidence["topological_order"] = topological

    ancestors: dict[str, set[str]] = {task_id: set() for task_id in by_id}

    def collect(task_id: str, visiting: set[str] | None = None) -> set[str]:
        if ancestors[task_id]:
            return ancestors[task_id]
        visiting = set() if visiting is None else visiting
        if task_id in visiting:
            return set()
        visiting.add(task_id)
        for dependency in by_id[task_id].get("dependencies", []):
            if dependency in by_id:
                ancestors[task_id].add(dependency)
                ancestors[task_id].update(collect(dependency, visiting.copy()))
        return ancestors[task_id]

    for task_id in by_id:
        collect(task_id)

    task_ids = sorted(by_id)
    for index, left_id in enumerate(task_ids):
        for right_id in task_ids[index + 1 :]:
            if left_id in ancestors[right_id] or right_id in ancestors[left_id]:
                continue
            conflicts: list[tuple[str, str]] = []
            for left_pattern in by_id[left_id].get("allowed_paths", []):
                for right_pattern in by_id[right_id].get("allowed_paths", []):
                    if patterns_overlap(left_pattern, right_pattern):
                        conflicts.append((left_pattern, right_pattern))
            if conflicts:
                result.add(
                    "DAG_PARALLEL_WRITE_CONFLICT",
                    f"parallel tasks {left_id} and {right_id} may write the same path",
                    left=left_id,
                    right=right_id,
                    patterns=conflicts,
                )
    return result


def check_changed_paths(
    work_order: dict[str, Any],
    changed_paths: Iterable[str],
    diff_lines: int,
) -> GateResult:
    result = GateResult()
    paths = list(changed_paths)
    allowed_patterns = work_order.get("allowed_paths", [])
    forbidden_patterns = work_order.get("forbidden_paths", [])

    for raw_path in paths:
        path = _normalise_repo_path(raw_path)
        if path is None:
            result.add("PATH_INVALID", f"invalid repository path: {raw_path!r}", path=raw_path)
            continue
        forbidden = [pattern for pattern in forbidden_patterns if _matches(path, pattern)]
        if forbidden:
            result.add("PATH_FORBIDDEN", f"changed path is forbidden: {path}", path=path, patterns=forbidden)
            continue
        if not any(_matches(path, pattern) for pattern in allowed_patterns):
            result.add("PATH_NOT_ALLOWED", f"changed path is outside allowed_paths: {path}", path=path)

    limits = work_order.get("limits", {})
    max_files = limits.get("max_changed_files")
    if isinstance(max_files, int) and len(paths) > max_files:
        result.add("DIFF_FILE_LIMIT", "changed file count exceeds Work Order limit", actual=len(paths), maximum=max_files)
    max_lines = limits.get("max_diff_lines")
    if isinstance(max_lines, int) and diff_lines > max_lines:
        result.add("DIFF_LINE_LIMIT", "diff line count exceeds Work Order limit", actual=diff_lines, maximum=max_lines)

    result.evidence.update({"changed_files": len(paths), "diff_lines": diff_lines})
    return result


def _safe_artifact_path(root: Path, relative: str) -> Path | None:
    normalised = _normalise_repo_path(relative)
    if normalised is None:
        return None
    root = root.resolve()
    candidate = (root / normalised).resolve()
    if not candidate.is_relative_to(root):
        return None
    return candidate


def verify_evidence_ref(root: Path | str, reference: dict[str, Any]) -> GateResult:
    result = GateResult()
    root_path = Path(root)
    relative = reference.get("path")
    if not isinstance(relative, str):
        result.add("EVIDENCE_PATH_MISSING", "evidence reference has no path")
        return result
    path = _safe_artifact_path(root_path, relative)
    if path is None:
        result.add("EVIDENCE_PATH_INVALID", "evidence path escapes artifact root", path=relative)
        return result
    if not path.is_file():
        result.add("EVIDENCE_MISSING", "referenced evidence file does not exist", path=relative)
        return result
    content = path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    actual_bytes = len(content)
    if reference.get("sha256") != actual_hash:
        result.add(
            "EVIDENCE_HASH_MISMATCH",
            "evidence sha256 does not match file",
            path=relative,
            expected=reference.get("sha256"),
            actual=actual_hash,
        )
    if reference.get("bytes") != actual_bytes:
        result.add(
            "EVIDENCE_SIZE_MISMATCH",
            "evidence byte count does not match file",
            path=relative,
            expected=reference.get("bytes"),
            actual=actual_bytes,
        )
    result.evidence[relative] = {"sha256": actual_hash, "bytes": actual_bytes}
    return result


def _git(repo_root: Path, args: list[str], *, text: bool = False) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=text,
        check=False,
    )


def _git_diff_stats(repo_root: Path, base: str, head: str) -> tuple[list[dict[str, Any]], int, str | None]:
    process = _git(repo_root, ["diff", "--numstat", "--no-ext-diff", f"{base}..{head}", "--"], text=True)
    if process.returncode != 0:
        return [], 0, process.stderr.strip()
    stats: list[dict[str, Any]] = []
    total_lines = 0
    for line in process.stdout.splitlines():
        additions_raw, deletions_raw, path = line.split("\t", 2)
        additions = 0 if additions_raw == "-" else int(additions_raw)
        deletions = 0 if deletions_raw == "-" else int(deletions_raw)
        stats.append({"path": path, "additions": additions, "deletions": deletions})
        total_lines += additions + deletions
    return stats, total_lines, None


def _git_name_status(repo_root: Path, base: str, head: str) -> tuple[dict[str, str], str | None]:
    process = _git(repo_root, ["diff", "--name-status", "--no-ext-diff", f"{base}..{head}", "--"], text=True)
    if process.returncode != 0:
        return {}, process.stderr.strip()
    status_names = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type-changed",
    }
    statuses: dict[str, str] = {}
    for line in process.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            return {}, f"cannot parse name-status line: {line!r}"
        code = parts[0][0]
        path = parts[-1]
        statuses[path] = status_names.get(code, code)
    return statuses, None


def verify_delivery(
    repo_root: Path | str,
    artifact_root: Path | str,
    work_order: dict[str, Any],
    manifest: dict[str, Any],
    *,
    rerun_tests: bool = True,
    registry: SchemaRegistry | None = None,
) -> GateResult:
    """Independently verify Git truth, evidence, scope and acceptance commands."""

    result = GateResult()
    repo = Path(repo_root).resolve()
    artifacts = Path(artifact_root).resolve()
    registry = registry or SchemaRegistry()
    for value, name in ((work_order, "Work Order"), (manifest, "Delivery Manifest")):
        try:
            registry.validate(value)
        except SchemaValidationError as exc:
            result.add("SCHEMA_INVALID", f"{name} failed schema validation", errors=[str(item) for item in exc.issues])
    if result.findings:
        return result

    if manifest["task_id"] != work_order["task_id"] or manifest["mission_id"] != work_order["mission_id"]:
        result.add("DELIVERY_ID_MISMATCH", "Delivery Manifest does not belong to the Work Order")

    base = manifest["base_commit"]
    head = manifest["head_commit"]
    for label, commit in (("base", base), ("head", head)):
        process = _git(repo, ["cat-file", "-e", f"{commit}^{{commit}}"])
        if process.returncode != 0:
            result.add("GIT_COMMIT_INVALID", f"{label} commit cannot be resolved", commit=commit)
    if any(finding.code == "GIT_COMMIT_INVALID" for finding in result.findings):
        return result
    ancestor = _git(repo, ["merge-base", "--is-ancestor", base, head])
    if ancestor.returncode != 0:
        result.add("GIT_RANGE_INVALID", "head is not a descendant of base", base=base, head=head)
        return result

    checked_out = _git(repo, ["rev-parse", "HEAD"], text=True)
    current_head = checked_out.stdout.strip() if checked_out.returncode == 0 else None
    if current_head != head:
        result.add(
            "GIT_HEAD_MISMATCH",
            "verification worktree is not checked out at Delivery Manifest head",
            expected=head,
            actual=current_head,
        )
    working_tree = _git(repo, ["status", "--porcelain", "--untracked-files=all"], text=True)
    if working_tree.returncode != 0:
        result.add("GIT_STATUS_FAILED", "could not inspect verification worktree status")
    elif working_tree.stdout.strip():
        result.add(
            "GIT_WORKTREE_DIRTY",
            "verification worktree contains uncommitted or untracked changes",
            entries=working_tree.stdout.splitlines()[:50],
        )

    actual_diff_process = _git(repo, ["diff", "--binary", "--no-ext-diff", f"{base}..{head}", "--"])
    if actual_diff_process.returncode != 0:
        result.add("GIT_DIFF_FAILED", "could not calculate authoritative Git diff")
        return result
    actual_diff = actual_diff_process.stdout
    patch_result = verify_evidence_ref(artifacts, manifest["patch"])
    result.merge(patch_result)
    patch_path = _safe_artifact_path(artifacts, manifest["patch"]["path"])
    if patch_path is not None and patch_path.is_file():
        reported_patch = patch_path.read_bytes()
        if reported_patch != actual_diff:
            result.add(
                "GIT_DIFF_MISMATCH",
                "reported patch is not the authoritative base..head Git diff",
                authoritative_sha256=hashlib.sha256(actual_diff).hexdigest(),
                reported_sha256=hashlib.sha256(reported_patch).hexdigest(),
            )

    stats, total_lines, stats_error = _git_diff_stats(repo, base, head)
    if stats_error:
        result.add("GIT_STATS_FAILED", "could not calculate diff statistics", error=stats_error)
        return result
    authoritative_paths = [item["path"] for item in stats]
    reported_paths = [item["path"] for item in manifest["changed_files"]]
    if sorted(authoritative_paths) != sorted(reported_paths):
        result.add(
            "CHANGED_FILES_MISMATCH",
            "reported changed_files differ from authoritative Git diff",
            authoritative=sorted(authoritative_paths),
            reported=sorted(reported_paths),
        )
    else:
        reported_by_path = {item["path"]: item for item in manifest["changed_files"]}
        for stat in stats:
            reported = reported_by_path[stat["path"]]
            if (reported["additions"], reported["deletions"]) != (stat["additions"], stat["deletions"]):
                result.add(
                    "DIFF_STATS_MISMATCH",
                    "reported line statistics differ from Git",
                    path=stat["path"],
                    authoritative={"additions": stat["additions"], "deletions": stat["deletions"]},
                    reported={"additions": reported["additions"], "deletions": reported["deletions"]},
                )
        statuses, status_error = _git_name_status(repo, base, head)
        if status_error:
            result.add("GIT_STATUS_FAILED", "could not calculate changed-file statuses", error=status_error)
        else:
            for path, authoritative_status in statuses.items():
                reported_status = reported_by_path[path]["status"]
                if reported_status != authoritative_status:
                    result.add(
                        "CHANGED_STATUS_MISMATCH",
                        "reported file status differs from Git",
                        path=path,
                        authoritative=authoritative_status,
                        reported=reported_status,
                    )
    result.merge(check_changed_paths(work_order, authoritative_paths, total_lines))

    required = set(work_order["required_deliverables"])
    if "artifacts" in required and not manifest["artifacts"]:
        result.add("ARTIFACTS_MISSING", "Work Order requires artifacts")
    for reference in manifest["artifacts"]:
        result.merge(verify_evidence_ref(artifacts, reference))

    expected_specs = {item["id"] for item in work_order["acceptance_specs"]}
    reported_specs = {item["spec_id"] for item in manifest["spec_results"]}
    missing_specs = sorted(expected_specs - reported_specs)
    unknown_specs = sorted(reported_specs - expected_specs)
    if missing_specs:
        result.add("SPEC_RESULT_MISSING", "acceptance specs have no result", specs=missing_specs)
    if unknown_specs:
        result.add("SPEC_RESULT_UNKNOWN", "manifest reports unknown specs", specs=unknown_specs)
    failed_specs = sorted(item["spec_id"] for item in manifest["spec_results"] if item["status"] != "pass")
    if failed_specs:
        result.add("SPEC_NOT_PASSING", "one or more acceptance specs did not pass", specs=failed_specs)

    reruns: list[dict[str, Any]] = []
    workspace_is_trusted = not any(
        finding.code in {"GIT_HEAD_MISMATCH", "GIT_WORKTREE_DIRTY", "GIT_STATUS_FAILED"}
        for finding in result.findings
    )
    if rerun_tests and workspace_is_trusted:
        for spec in work_order["acceptance_specs"]:
            validator = spec["validator"]
            if validator["kind"] != "command":
                continue
            try:
                command = shlex.split(validator["command"])
            except ValueError as exc:
                result.add("TEST_COMMAND_INVALID", "acceptance command cannot be parsed", spec_id=spec["id"], error=str(exc))
                continue
            if not command:
                result.add("TEST_COMMAND_INVALID", "acceptance command is empty", spec_id=spec["id"])
                continue
            try:
                process = subprocess.run(
                    command,
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=validator.get("timeout_seconds", 300),
                )
                rerun = {
                    "spec_id": spec["id"],
                    "command": validator["command"],
                    "exit_code": process.returncode,
                    "stdout_tail": process.stdout[-2000:],
                    "stderr_tail": process.stderr[-2000:],
                }
                reruns.append(rerun)
                if process.returncode != 0:
                    result.add(
                        "TEST_RERUN_FAILED",
                        "independent acceptance command failed",
                        spec_id=spec["id"],
                        command=validator["command"],
                        exit_code=process.returncode,
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                result.add("TEST_RERUN_ERROR", "independent acceptance command could not complete", spec_id=spec["id"], error=str(exc))
    result.evidence["git"] = {
        "base": base,
        "head": head,
        "diff_sha256": hashlib.sha256(actual_diff).hexdigest(),
        "changed_files": len(stats),
        "diff_lines": total_lines,
    }
    result.evidence["test_reruns"] = reruns
    if "test_results" in required and not manifest["tests"] and not reruns:
        result.add("TEST_RESULTS_MISSING", "Work Order requires test results")
    return result


def estimate_packet_tokens(packet: dict[str, Any]) -> int:
    """Conservative offline approximation; benchmark adapters should replace it with tokenizer counts."""

    text = canonical_json_bytes(packet).decode("utf-8")
    ascii_count = sum(ord(character) < 128 for character in text)
    non_ascii_count = len(text) - ascii_count
    return math.ceil(ascii_count / 4) + non_ascii_count


def _walk_keys(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            yield child, key
            yield from _walk_keys(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_keys(item, f"{path}[{index}]")


def _collect_evidence_refs(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"}.issubset(value):
            yield value
        for item in value.values():
            yield from _collect_evidence_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _collect_evidence_refs(item)


def validate_review_packet(
    packet: dict[str, Any],
    artifact_root: Path | str,
    *,
    registry: SchemaRegistry | None = None,
) -> GateResult:
    result = GateResult()
    registry = registry or SchemaRegistry()
    try:
        registry.validate(packet)
    except SchemaValidationError as exc:
        result.add("SCHEMA_INVALID", "Review Packet failed schema validation", errors=[str(item) for item in exc.issues])
        return result

    prohibited = {
        "transcript", "raw_transcript", "worker_transcript", "reasoning", "chain_of_thought",
        "full_log", "full_logs", "full_repo", "repository_dump", "task_packets",
    }
    for path, key in _walk_keys(packet):
        if key.lower() in prohibited:
            result.add("PACKET_PROHIBITED_CONTENT", "Review Packet contains prohibited bulk context", path=path, key=key)

    actual_tokens = estimate_packet_tokens(packet)
    budget = packet["packet_budget"]
    if actual_tokens > budget["max_tokens"]:
        result.add(
            "PACKET_TOKEN_BUDGET",
            "Review Packet exceeds token budget",
            actual=actual_tokens,
            maximum=budget["max_tokens"],
        )
    if budget["estimated_tokens"] < actual_tokens:
        result.add(
            "PACKET_ESTIMATE_UNDERSTATED",
            "declared packet estimate is lower than deterministic estimate",
            declared=budget["estimated_tokens"],
            actual=actual_tokens,
        )

    for index, context in enumerate(packet["context_slices"]):
        path = context["path"]
        if any(token in path for token in "*?[") or path in {".", "./"}:
            result.add(
                "PACKET_CONTEXT_NOT_TARGETED",
                "context slice must name one concrete file",
                index=index,
                path=path,
            )
        line_count = context["end"] - context["start"] + 1
        if line_count > 240:
            result.add(
                "PACKET_CONTEXT_TOO_LARGE",
                "one context slice exceeds 240 lines",
                index=index,
                path=path,
                lines=line_count,
            )

    seen_refs: set[tuple[str, str]] = set()
    for reference in _collect_evidence_refs(packet):
        marker = (reference["path"], reference["sha256"])
        if marker in seen_refs:
            continue
        seen_refs.add(marker)
        result.merge(verify_evidence_ref(artifact_root, reference))
    result.evidence["packet"] = {
        "scope": packet["scope"],
        "estimated_tokens": actual_tokens,
        "evidence_refs": len(seen_refs),
    }
    return result
