from __future__ import annotations

import re
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.benchmark import (
    BenchmarkIdentity,
    BenchmarkRunner,
    compare_benchmarks,
    finalize_hidden_evaluation,
    summarize_rework_campaign,
)
from tools.token_firewall.gates import GateResult
from tools.token_firewall.runtime import RuntimeAdapter, RuntimeRequest, RuntimeResult, RuntimeStatus
from tools.token_firewall.schema import canonical_sha256

from tests.token_firewall.fixtures import mission_contract, runtime_worker_report, verdict, work_order


def run(command: list[str], cwd: Path) -> str:
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise AssertionError(f"command failed: {command}\n{process.stdout}\n{process.stderr}")
    return process.stdout.strip()


def make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    run(["git", "init", "-q"], repo)
    run(["git", "config", "user.email", "benchmark@example.com"], repo)
    run(["git", "config", "user.name", "Benchmark"], repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.txt").write_text("one\n", encoding="utf-8")
    run(["git", "add", "src/app.txt"], repo)
    run(["git", "commit", "-q", "-m", "base"], repo)
    return repo, run(["git", "rev-parse", "HEAD"], repo)


def usage(total: int, source: str) -> dict:
    return {
        "input_tokens": total - 10,
        "output_tokens": 10,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": total,
        "native_total_tokens": total,
        "source": source,
        "complete": True,
    }


def sealed_record(group: str, *, usage_complete: bool = True) -> dict:
    def stage(role: str, model: str, total: int, counts_as_sol: bool, session: str):
        value = usage(total, "fixture")
        value["complete"] = usage_complete
        return {
            "role": role,
            "runtime": "runtime",
            "runtime_version": "1",
            "model_requested": model,
            "model_effective": model,
            "model_effective_verified": False,
            "counts_as_sol": counts_as_sol,
            "session_id": session,
            "status": "SUCCEEDED",
            "usage": value,
        }

    value = {
        "schema": "token-firewall/benchmark-record@0.1",
        "content_sha256": "0" * 64,
        "candidate_id": f"cand_{group.lower()}",
        "run_id": f"run_{group.lower()}",
        "group_id": group,
        "task_revision": 1,
        "base_sha": "a" * 40,
        "mission_content_sha256": "b" * 64,
        "task_content_sha256": "c" * 64,
        "mission_id": "msn_x",
        "task_id": "T-X",
        "started_at": "2026-07-11T12:00:00+08:00",
        "finished_at": "2026-07-11T12:01:00+08:00",
        "elapsed_seconds": 60,
        "status": "COMPLETE",
        "commit_range": {"base": "a" * 40, "head": "d" * 40},
        "diff": {"files": 1, "additions": 1, "deletions": 0},
        "public_gate": {"status": "pass", "finding_codes": []},
        "hidden_evaluation": {
            "test_id": "hidden-v1",
            "suite_sha256": "e" * 64,
            "status": "pass",
            "exit_code": 0,
            "duration_ms": 1,
            "stdout_sha256": "f" * 64,
            "stderr_sha256": "f" * 64,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "assertions_disclosed": False,
        },
        "review": {
            "verdict": "PASS",
            "findings": 0,
            "high_critical_findings": 0,
            "requested_context": 0,
            "coverage_gaps": 0,
            "rubric_revision": "r1",
            "prompt_template_sha256": "f" * 64,
        },
        "stages": {
            "worker": stage(
                "worker",
                "gpt-5.6-sol" if group == "D" else "minimax/MiniMax-M3",
                1000 if group == "D" else 500,
                group == "D",
                f"worker-{group}",
            ),
            "verifier": None if group == "D" else stage(
                "verifier", "minimax/MiniMax-M3", 300, False, "verifier-A"
            ),
            "reviewer": stage("reviewer", "gpt-5.6-sol", 100, True, f"reviewer-{group}"),
        },
        "scope_violations": [],
        "artifacts": {"run_dir": "/tmp/run"},
    }
    value["content_sha256"] = canonical_sha256(value)
    return value


class BenchmarkWorker(RuntimeAdapter):
    name = "benchmark-worker"

    def preflight(self) -> GateResult:
        return GateResult(evidence={"runtime": self.name})

    def execute(self, request: RuntimeRequest, *, on_trace=None) -> RuntimeResult:
        (request.workspace / "src" / "app.txt").write_text("two\n", encoding="utf-8")
        run(["git", "add", "src/app.txt"], request.workspace)
        run(["git", "commit", "-q", "-m", "candidate"], request.workspace)
        head = run(["git", "rev-parse", "HEAD"], request.workspace)
        report = runtime_worker_report(
            head,
            command="python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'",
        )
        total = 1000 if request.model == "gpt-5.6-sol" else 500
        return RuntimeResult(
            self.name,
            RuntimeStatus.SUCCEEDED,
            f"worker-{request.model}",
            report,
            0,
            usage=usage(total, "scripted-worker"),
        )


class BenchmarkReadOnly(RuntimeAdapter):
    name = "benchmark-read-only"

    def __init__(self, verifier_status: str = "PASS"):
        self.reviewer_workspaces: list[Path] = []
        self.calls = 0
        self.verifier_status = verifier_status

    def preflight(self) -> GateResult:
        return GateResult(evidence={"runtime": self.name})

    def execute(self, request: RuntimeRequest, *, on_trace=None) -> RuntimeResult:
        self.calls += 1
        match = re.search(r"(?:reviewed commit must be|Review commit) ([a-f0-9]{40})", request.prompt, re.IGNORECASE)
        if not match:
            return RuntimeResult(self.name, RuntimeStatus.FAILED, None, None, 1, error="missing commit")
        head = match.group(1)
        if request.output_schema_id.endswith("runtime-verifier-report@0.1"):
            output = {
                "schema": "token-firewall/runtime-verifier-report@0.1",
                "status": self.verifier_status,
                "reviewed_commit": head,
                "summary": "independent public verification passed",
                "spec_results": [{
                    "spec_id": "SPEC-001-01",
                    "status": "pass" if self.verifier_status == "PASS" else "fail",
                    "evidence": "public gate",
                }],
                "findings": [] if self.verifier_status == "PASS" else [{
                    "finding_id": "vf-1",
                    "severity": "medium",
                    "spec_id": "SPEC-001-01",
                    "file": "src/app.txt",
                    "line": 1,
                    "issue": "scripted verifier failure",
                    "evidence": "fixture",
                }],
                "coverage_gaps": [],
                "requested_context": [],
            }
            total = 300
        else:
            self.reviewer_workspaces.append(request.workspace)
            self.assert_blind(request.workspace)
            output = verdict()
            output["reviewed_commit"] = head
            total = 100
        return RuntimeResult(
            self.name,
            RuntimeStatus.SUCCEEDED,
            f"fresh-read-only-session-{id(self)}-{self.calls}",
            output,
            0,
            usage=usage(total, "scripted-read-only"),
        )

    @staticmethod
    def assert_blind(workspace: Path) -> None:
        if (workspace / ".git").exists():
            raise AssertionError("blind reviewer received a Git worktree")
        text = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in workspace.rglob("*")
            if path.is_file()
        )
        for marker in ("gpt-5.6-sol", "MiniMax-M3", "worker-gpt", "worker-minimax"):
            if marker in text:
                raise AssertionError(f"identity leaked into blind bundle: {marker}")


class FailingBenchmarkWorker(RuntimeAdapter):
    name = "failing-worker"

    def preflight(self) -> GateResult:
        return GateResult(evidence={"runtime": self.name})

    def execute(self, request: RuntimeRequest, *, on_trace=None) -> RuntimeResult:
        return RuntimeResult(
            self.name,
            RuntimeStatus.FAILED,
            "failed-worker-session",
            None,
            1,
            usage=usage(777, "failed-worker-fixture"),
            error="intentional failure",
        )

class BenchmarkHarnessTests(unittest.TestCase):
    def test_rework_summary_counts_cumulative_sol_and_validates_chain(self) -> None:
        control = sealed_record("D")
        initial = sealed_record("A")
        rework = sealed_record("B")
        rework["base_sha"] = initial["commit_range"]["head"]
        rework["commit_range"]["base"] = rework["base_sha"]
        rework["task_revision"] = 2
        rework["stages"]["verifier"]["role"] = "deputy"
        rework["stages"]["verifier"]["model_requested"] = "gpt-5.6-terra"
        rework["stages"]["verifier"]["model_effective"] = "gpt-5.6-terra"
        rework["content_sha256"] = canonical_sha256(rework)
        summary = summarize_rework_campaign(control, initial, rework)
        self.assertTrue(summary["chain_valid"])
        self.assertEqual(summary["control_sol_tokens"], 1100)
        self.assertEqual(summary["cumulative_a_plus_rework_sol_tokens"], 200)
        self.assertEqual(summary["cumulative_sol_savings_percent"], 81.82)
        self.assertTrue(summary["campaign_pass"])

        correction = copy.deepcopy(rework)
        correction["run_id"] = "run_rework_erratum"
        correction["task_revision"] = 3
        correction["content_sha256"] = canonical_sha256(correction)
        multi = summarize_rework_campaign(control, initial, [rework, correction])
        self.assertTrue(multi["chain_valid"])
        self.assertEqual(multi["rework_sol_tokens"], 100)
        self.assertEqual(multi["rework_rounds"], 2)
        self.assertEqual(multi["deduplicated_model_sessions"], 3)

    def test_group_b_routes_m3_through_terra_deputy_before_sol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            hidden = root / "hidden.py"
            hidden.write_text("raise SystemExit(0)\n", encoding="utf-8")
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            deputy = BenchmarkReadOnly()
            reviewer = BenchmarkReadOnly()
            record = BenchmarkRunner(
                repo_root=repo,
                run_dir=root / "run",
                worktree_root=root / "worktrees",
                worker=BenchmarkWorker(),
                verifier=deputy,
                reviewer=reviewer,
            ).run(
                BenchmarkIdentity("run_group_b", "B", 1, base),
                mission_contract(),
                work_order(command=command),
                worker_model="minimax/MiniMax-M3",
                verifier_model="gpt-5.6-terra",
                reviewer_model="gpt-5.6-sol",
                hidden_command=[sys.executable, "-B", str(hidden)],
                hidden_test_id="hidden-v1",
                timeout_seconds=30,
            )
            self.assertEqual(record["status"], "COMPLETE")
            self.assertEqual(record["stages"]["verifier"]["role"], "deputy")
            self.assertEqual(record["stages"]["verifier"]["model_requested"], "gpt-5.6-terra")
            self.assertFalse(record["stages"]["verifier"]["counts_as_sol"])
            self.assertEqual(len(reviewer.reviewer_workspaces), 1)
            observed = sorted((root / "run" / "observability").glob("*/external-run-state.json"))
            self.assertEqual(len(observed), 3)
            self.assertTrue(all(json.loads(path.read_text())["status"] == "COMPLETE" for path in observed))

    def test_da_pair_is_blind_metered_and_comparable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            order = work_order(command=command)
            hidden = root / "hidden.py"
            hidden.write_text(
                "from pathlib import Path\nassert Path('src/app.txt').read_text() == 'two\\n'\n",
                encoding="utf-8",
            )

            d_reviewer = BenchmarkReadOnly()
            d_record = BenchmarkRunner(
                repo_root=repo,
                run_dir=root / "runs" / "random-one",
                worktree_root=root / "worktrees",
                worker=BenchmarkWorker(),
                reviewer=d_reviewer,
            ).run(
                BenchmarkIdentity("run_random_one", "D", 1, base),
                mission_contract(),
                order,
                worker_model="gpt-5.6-sol",
                reviewer_model="gpt-5.6-sol",
                hidden_command=[sys.executable, "-B", str(hidden)],
                hidden_test_id="hidden-v1",
                timeout_seconds=30,
            )

            a_reviewer = BenchmarkReadOnly()
            a_record = BenchmarkRunner(
                repo_root=repo,
                run_dir=root / "runs" / "random-two",
                worktree_root=root / "worktrees",
                worker=BenchmarkWorker(),
                verifier=BenchmarkReadOnly(),
                reviewer=a_reviewer,
            ).run(
                BenchmarkIdentity("run_random_two", "A", 1, base),
                mission_contract(),
                order,
                worker_model="minimax/MiniMax-M3",
                verifier_model="minimax/MiniMax-M3",
                reviewer_model="gpt-5.6-sol",
                hidden_command=[sys.executable, "-B", str(hidden)],
                hidden_test_id="hidden-v1",
                timeout_seconds=30,
            )

            self.assertEqual(d_record["status"], "COMPLETE")
            self.assertEqual(a_record["status"], "COMPLETE")
            self.assertEqual(d_record["hidden_evaluation"]["status"], "pass")
            self.assertEqual(a_record["hidden_evaluation"]["status"], "pass")
            self.assertTrue(d_record["stages"]["worker"]["usage"]["complete"])
            self.assertTrue(a_record["stages"]["verifier"]["usage"]["complete"])
            comparison = compare_benchmarks(d_record, a_record)
            self.assertTrue(comparison["comparable"])
            self.assertGreaterEqual(comparison["sol_token_savings_percent"], 70)
            self.assertTrue(comparison["pilot_pass"])

    def test_compare_fails_closed_on_identity_or_usage_mismatch(self) -> None:
        base_record = sealed_record("D", usage_complete=False)
        experiment = sealed_record("A")
        result = compare_benchmarks(base_record, experiment)
        self.assertIsNone(result["sol_token_savings_percent"])
        self.assertFalse(result["pilot_pass"])
        mismatched = copy.deepcopy(experiment)
        mismatched["task_content_sha256"] = "d" * 64
        mismatched["content_sha256"] = canonical_sha256(mismatched)
        self.assertFalse(compare_benchmarks(base_record, mismatched)["comparable"])

    def test_compare_supports_terra_and_claude_experiment_groups(self) -> None:
        control = sealed_record("D")
        for group in ("C", "E"):
            experiment = sealed_record(group)
            result = compare_benchmarks(control, experiment)
            self.assertTrue(result["comparable"])
            self.assertIn(group, result["sol_tokens"])
            self.assertIn(group, result["hidden_evaluation"])

    def test_verifier_fail_blocks_chief_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            hidden = root / "hidden.py"
            hidden.write_text("raise SystemExit(0)\n", encoding="utf-8")
            reviewer = BenchmarkReadOnly()
            record = BenchmarkRunner(
                repo_root=repo,
                run_dir=root / "run",
                worktree_root=root / "worktrees",
                worker=BenchmarkWorker(),
                verifier=BenchmarkReadOnly(verifier_status="FAIL"),
                reviewer=reviewer,
            ).run(
                BenchmarkIdentity("run_verifier_fail", "A", 1, base),
                mission_contract(),
                work_order(command=command),
                worker_model="minimax/MiniMax-M3",
                verifier_model="minimax/MiniMax-M3",
                reviewer_model="gpt-5.6-sol",
                hidden_command=[sys.executable, "-B", str(hidden)],
                hidden_test_id="hidden-v1",
                timeout_seconds=30,
            )
            self.assertEqual(record["status"], "VERIFIER_FAILED")
            self.assertIsNone(record["stages"]["reviewer"])
            self.assertEqual(reviewer.reviewer_workspaces, [])

    def test_failed_worker_usage_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            hidden = root / "hidden.py"
            hidden.write_text("raise SystemExit(0)\n", encoding="utf-8")
            record = BenchmarkRunner(
                repo_root=repo,
                run_dir=root / "run",
                worktree_root=root / "worktrees",
                worker=FailingBenchmarkWorker(),
                reviewer=BenchmarkReadOnly(),
            ).run(
                BenchmarkIdentity("run_worker_fail", "D", 1, base),
                mission_contract(),
                work_order(),
                worker_model="gpt-5.6-sol",
                reviewer_model="gpt-5.6-sol",
                hidden_command=[sys.executable, "-B", str(hidden)],
                hidden_test_id="hidden-v1",
                timeout_seconds=30,
            )
            self.assertEqual(record["status"], "WORKER_FAILED")
            self.assertEqual(record["stages"]["worker"]["usage"]["total_tokens"], 777)
            self.assertTrue(record["stages"]["worker"]["usage"]["complete"])

    def test_hidden_suite_can_be_deferred_until_all_models_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, base = make_repo(root)
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            hidden = root / "hidden.py"
            hidden.write_text("from pathlib import Path\nassert Path('src/app.txt').read_text() == 'two\\n'\n", encoding="utf-8")
            suite_sha = hashlib.sha256(hidden.read_bytes()).hexdigest()
            run_dir = root / "run"
            record = BenchmarkRunner(
                repo_root=repo,
                run_dir=run_dir,
                worktree_root=root / "worktrees",
                worker=BenchmarkWorker(),
                reviewer=BenchmarkReadOnly(),
            ).run(
                BenchmarkIdentity("run_deferred", "D", 1, base),
                mission_contract(),
                work_order(command=command),
                worker_model="gpt-5.6-sol",
                reviewer_model="gpt-5.6-sol",
                hidden_command=None,
                hidden_test_id="hidden-v1",
                hidden_suite_sha256=suite_sha,
                timeout_seconds=30,
            )
            self.assertEqual(record["status"], "MODEL_STAGES_COMPLETE")
            self.assertEqual(record["hidden_evaluation"]["status"], "not_run")
            final = finalize_hidden_evaluation(
                run_dir / "benchmark-record.json",
                [sys.executable, "-B", str(hidden)],
            )
            self.assertEqual(final["status"], "COMPLETE")
            self.assertEqual(final["hidden_evaluation"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
