from __future__ import annotations

import re
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.gates import GateResult
from tools.token_firewall.orchestrator import RuntimePocRunner
from tools.token_firewall.runtime import RuntimeAdapter, RuntimeRequest, RuntimeResult, RuntimeStatus
from tools.token_firewall.worktree import (
    GitWorktreeError,
    GitWorktreeManager,
    inspect_commit_range,
    sanitize_runtime_ephemera,
)

from tests.token_firewall.fixtures import mission_contract, runtime_worker_report, seal, verdict, work_order, work_order_v02


def run(command: list[str], cwd: Path) -> str:
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise AssertionError(f"command failed: {command}\n{process.stdout}\n{process.stderr}")
    return process.stdout


def make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    run(["git", "init", "-q"], repo)
    run(["git", "config", "user.email", "runtime@example.com"], repo)
    run(["git", "config", "user.name", "Runtime POC"], repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.txt").write_text("one\n", encoding="utf-8")
    run(["git", "add", "src/app.txt"], repo)
    run(["git", "commit", "-q", "-m", "base"], repo)
    return repo, run(["git", "rev-parse", "HEAD"], repo).strip()


class ScriptedWorker(RuntimeAdapter):
    name = "scripted-worker"

    def __init__(self, command: str):
        self.command = command

    def preflight(self) -> GateResult:
        return GateResult(evidence={"runtime": self.name})

    def execute(self, request: RuntimeRequest, *, on_trace=None) -> RuntimeResult:
        if on_trace:
            on_trace("runtime.started", {"runtime": self.name})
        (request.workspace / "src" / "app.txt").write_text("two\n", encoding="utf-8")
        run(["git", "add", "src/app.txt"], request.workspace)
        run(["git", "commit", "-q", "-m", "implement work order"], request.workspace)
        head = run(["git", "rev-parse", "HEAD"], request.workspace).strip()
        (request.workspace / "src" / ".DS_Store").write_bytes(b"runtime metadata")
        cache = request.workspace / "tests" / "__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "test.pyc").write_bytes(b"bytecode")
        report = runtime_worker_report(head, command=self.command)
        if on_trace:
            on_trace("runtime.finished", {"runtime": self.name})
        return RuntimeResult(
            self.name, RuntimeStatus.SUCCEEDED, "worker-session", report, 0,
            model_effective="cheap-model", model_effective_verified=True,
        )


class ScriptedReviewer(RuntimeAdapter):
    name = "scripted-reviewer"

    def preflight(self) -> GateResult:
        return GateResult(evidence={"runtime": self.name})

    def execute(self, request: RuntimeRequest, *, on_trace=None) -> RuntimeResult:
        match = re.search(r"reviewed commit must be ([a-f0-9]{40,64})", request.prompt, re.IGNORECASE)
        if not match:
            return RuntimeResult(self.name, RuntimeStatus.FAILED, "review-session", None, 1, error="missing commit")
        value = verdict()
        value["reviewed_commit"] = match.group(1)
        return RuntimeResult(self.name, RuntimeStatus.SUCCEEDED, "review-session", value, 0)


class ChangesReadyWorker(RuntimeAdapter):
    name = "sandboxed-worker"

    def __init__(self, command: str):
        self.command = command

    def preflight(self) -> GateResult:
        return GateResult()

    def execute(self, request: RuntimeRequest, *, on_trace=None) -> RuntimeResult:
        (request.workspace / "src" / "app.txt").write_text("two\n", encoding="utf-8")
        return RuntimeResult(
            self.name, RuntimeStatus.SUCCEEDED, "sandboxed-session",
            runtime_worker_report(status="CHANGES_READY", command=self.command), 0,
        )


class WorktreeAndRuntimeOrchestratorTests(unittest.TestCase):
    def test_worktree_manager_creates_isolated_branch_and_reads_git_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            manager = GitWorktreeManager(repo, root / "worktrees")
            handle = manager.create("msn_test", "T-001", base)
            (handle.path / "src" / "app.txt").write_text("two\n", encoding="utf-8")
            run(["git", "add", "src/app.txt"], handle.path)
            run(["git", "commit", "-q", "-m", "change"], handle.path)
            delivery = inspect_commit_range(handle)
            self.assertNotEqual(delivery["head_commit"], base)
            self.assertEqual(delivery["changed_files"][0]["path"], "src/app.txt")
            self.assertEqual(run(["git", "status", "--porcelain"], repo), "")

    def test_runtime_sanitizer_removes_only_known_untracked_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            handle = GitWorktreeManager(repo, root / "worktrees").create("msn_test", "T-001", base)
            (handle.path / "src" / ".DS_Store").write_bytes(b"metadata")
            cache = handle.path / "src" / "__pycache__"
            cache.mkdir()
            (cache / "text_utils.pyc").write_bytes(b"bytecode")
            (handle.path / "unexpected.txt").write_text("preserve and reject", encoding="utf-8")
            result = sanitize_runtime_ephemera(handle)
            self.assertIn("src/.DS_Store", result["removed"])
            self.assertIn("src/__pycache__", result["removed"])
            self.assertEqual(result["remaining"], ["unexpected.txt"])
            self.assertTrue((handle.path / "unexpected.txt").exists())

    def test_worktree_manager_fails_closed_on_dirty_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
            with self.assertRaises(GitWorktreeError):
                GitWorktreeManager(repo, root / "worktrees").create("msn_test", "T-001", base)

    def test_worktree_manager_detects_non_git_directory_permission_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            handle = GitWorktreeManager(repo, root / "worktrees").create("msn_test", "T-001", base)
            (handle.path / "src").chmod(0o555)
            try:
                with self.assertRaises(GitWorktreeError):
                    sanitize_runtime_ephemera(handle)
            finally:
                (handle.path / "src").chmod(0o755)

    def test_full_runtime_vertical_slice_reaches_sol_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            order = work_order(command=command)
            runner = RuntimePocRunner(
                repo_root=repo,
                run_dir=root / "run",
                worktree_root=root / "worktrees",
                worker=ScriptedWorker(command),
                reviewer=ScriptedReviewer(),
            )
            result = runner.run(mission_contract(), order, base_commit=base, timeout_seconds=30)
            self.assertEqual(result.status, "PASSED", result.to_dict())
            self.assertTrue(result.delivery_manifest.is_file())
            self.assertTrue(result.review_packet.is_file())
            self.assertTrue(result.review_verdict.is_file())
            state = (root / "run" / "mission-state.json").read_text(encoding="utf-8")
            self.assertIn('"mission_state": "PASSED"', state)
            packet_text = result.review_packet.read_text(encoding="utf-8")
            self.assertNotIn("transcript", packet_text)
            self.assertIn('"scope": "mission"', packet_text)
            manifest = json.loads(result.delivery_manifest.read_text())
            self.assertEqual(manifest["created_by"]["runtime"], "scripted-worker")
            self.assertEqual(manifest["created_by"]["model"], "cheap-model")
            self.assertEqual(manifest["usage"]["model"], "cheap-model")

    def test_fake_worker_pass_claim_stops_at_rework(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            failing = "python3 -c 'raise SystemExit(9)'"
            runner = RuntimePocRunner(
                repo_root=repo,
                run_dir=root / "run",
                worktree_root=root / "worktrees",
                worker=ScriptedWorker(failing),
            )
            result = runner.run(mission_contract(), work_order(command=failing), base_commit=base, timeout_seconds=30)
            self.assertEqual(result.status, "REWORK", result.to_dict())
            self.assertIn("TEST_RERUN_FAILED", {finding.code for finding in result.findings})
            self.assertIsNone(result.review_packet)

    def test_v02_acceptance_contract_reaches_worker_and_review_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            order = work_order_v02(command=command)
            runner = RuntimePocRunner(
                repo_root=repo, run_dir=root / "run", worktree_root=root / "worktrees",
                worker=ScriptedWorker(command), reviewer=ScriptedReviewer(),
            )
            result = runner.run(mission_contract(), order, base_commit=base, timeout_seconds=30)
            self.assertEqual(result.status, "PASSED", result.to_dict())
            packet = json.loads(result.review_packet.read_text())
            contract = packet["acceptance_contract"][0]
            self.assertEqual(contract["negative_cases"][0]["case_id"], "NEG-001")
            self.assertEqual(contract["semantic_boundaries"][0]["boundary_id"], "BOUND-001")

    def test_broker_commits_changes_ready_without_worker_git_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            result = RuntimePocRunner(
                repo_root=repo, run_dir=root / "run", worktree_root=root / "worktrees",
                worker=ChangesReadyWorker(command),
            ).run(mission_contract(), work_order(command=command), base_commit=base, timeout_seconds=30)
            self.assertEqual(result.status, "REVIEW_READY", result.to_dict())
            manifest = json.loads(result.delivery_manifest.read_text())
            self.assertNotEqual(manifest["head_commit"], base)
            message = run(["git", "log", "-1", "--pretty=%s"], result.worktree).strip()
            self.assertEqual(message, "token-firewall: deliver T-001")


if __name__ == "__main__":
    unittest.main()
