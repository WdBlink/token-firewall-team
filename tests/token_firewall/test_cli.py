from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.token_firewall.fixtures import mission_contract, work_order_v02
from tests.token_firewall.test_evaluation import pairs, protocol
from tests.token_firewall.test_benchmark import sealed_record
from tools.token_firewall.cli import build_parser
from tools.token_firewall.observability import ExternalRunObserver


ROOT = Path(__file__).resolve().parents[2]


class TokenFirewallCliTests(unittest.TestCase):
    def test_runtime_run_requires_explicit_worker_runtime(self) -> None:
        argv = [
            "runtime-run",
            "mission.json",
            "work-order.json",
            "--repo", ".",
            "--base", "main",
            "--run-dir", "/tmp/token-firewall-run",
            "--worktree-root", "/tmp/token-firewall-worktrees",
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                build_parser().parse_args(argv)
        self.assertEqual(raised.exception.code, 2)

    def test_validate_command_returns_machine_readable_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "mission.json"
            contract.write_text(json.dumps(mission_contract(), ensure_ascii=False), encoding="utf-8")
            process = subprocess.run(
                ["python3", "-m", "tools.token_firewall", "validate", str(contract)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)
            self.assertTrue(response["ok"])
            self.assertEqual(response["schema"], "token-firewall/mission-contract@0.1")

    def test_validate_command_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "mission.json"
            value = mission_contract()
            del value["goal"]
            contract.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            process = subprocess.run(
                ["python3", "-m", "tools.token_firewall", "validate", str(contract)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 2)
            response = json.loads(process.stdout)
            self.assertFalse(response["ok"])
            self.assertIn("missing required property", response["error"])

    def test_observe_status_returns_projected_external_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "campaign"
            ExternalRunObserver.create(
                run_dir / "observability" / "T-001-worker",
                run_id="run-cli",
                mission_id="msn-cli",
                task_id="T-001",
                stage="worker",
                runtime="minimax",
                model="MiniMax-M3",
            )
            process = subprocess.run(
                [
                    "python3", "-m", "tools.token_firewall", "observe-status",
                    str(run_dir), "--format", "json",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)
            self.assertEqual(response["runs"][0]["display_status"], "DISPATCHED")

    def test_evaluation_summarize_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protocol_path = root / "protocol.json"
            pairs_path = root / "pairs.json"
            output = root / "report"
            protocol_path.write_text(json.dumps(protocol()), encoding="utf-8")
            pairs_path.write_text(json.dumps(pairs()), encoding="utf-8")
            process = subprocess.run(
                [
                    "python3", "-m", "tools.token_firewall", "evaluation-summarize",
                    str(protocol_path), str(pairs_path), "--out-dir", str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)
            self.assertEqual(response["verdict"], "PASS")
            self.assertTrue((output / "evaluation-report.md").is_file())

    def test_evaluation_import_uses_frozen_benchmark_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protocol_path = root / "protocol.json"
            control_path = root / "control.json"
            experiment_path = root / "experiment.json"
            output = root / "pair.json"
            protocol_path.write_text(json.dumps(protocol()), encoding="utf-8")
            control_path.write_text(json.dumps(sealed_record("D")), encoding="utf-8")
            experiment_path.write_text(json.dumps(sealed_record("A")), encoding="utf-8")
            process = subprocess.run(
                [
                    "python3", "-m", "tools.token_firewall", "evaluation-import",
                    str(protocol_path), str(control_path), str(experiment_path),
                    "--pair-id", "cli-pair", "--risk", "low", "--task-type", "bugfix",
                    "--out", str(output),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            pair = json.loads(output.read_text())
            self.assertEqual(pair["provenance"]["normalizer_revision"], "benchmark-to-pair@0.1")

    def test_evaluation_export_inspect_writes_structured_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protocol_path = root / "protocol.json"
            pair_paths = []
            protocol_path.write_text(json.dumps(protocol()), encoding="utf-8")
            for index, pair in enumerate(pairs(), 1):
                path = root / f"pair-{index}.json"
                path.write_text(json.dumps(pair), encoding="utf-8")
                pair_paths.append(path)
            output = root / "inspect"
            process = subprocess.run(
                [
                    "python3", "-m", "tools.token_firewall", "evaluation-export-inspect",
                    str(protocol_path), *(str(path) for path in pair_paths),
                    "--out-dir", str(output),
                ],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)
            self.assertTrue(response["ok"])
            self.assertEqual(response["manifest"]["compatibility_role"], "analysis-only")
            self.assertEqual(len((output / "token-firewall-pairs.jsonl").read_text().splitlines()), 3)

    def test_gate_budget_returns_machine_readable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            order = root / "order.json"
            stages = root / "stages.json"
            order.write_text(json.dumps(work_order_v02(risk="low")), encoding="utf-8")
            stages.write_text(json.dumps([{
                "role": "reviewer", "model_requested": "gpt-5.6-sol", "counts_as_sol": True,
                "session_id": "sol-review-1", "usage": {"total_tokens": 40000, "complete": True},
            }]), encoding="utf-8")
            process = subprocess.run(
                [
                    "python3", "-m", "tools.token_firewall", "gate-budget",
                    str(ROOT / "evidence/policies/risk-token-budget-policy-0.1.json"),
                    str(order), str(stages), "--baseline-sol-tokens", "300000",
                ], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)
            self.assertEqual(response["evidence"]["total_sol_tokens"], 40000)


if __name__ == "__main__":
    unittest.main()
