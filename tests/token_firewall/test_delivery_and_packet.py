from __future__ import annotations

import copy
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.gates import estimate_packet_tokens, validate_review_packet, verify_delivery

from tests.token_firewall.fixtures import delivery_manifest, seal, task_review_packet, work_order


def run(command: list[str], cwd: Path, *, text: bool = True):
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=text, check=False)
    if process.returncode != 0:
        raise AssertionError(f"command failed: {command}\nstdout={process.stdout}\nstderr={process.stderr}")
    return process.stdout


def finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


class GitDeliveryGateTests(unittest.TestCase):
    def make_repo(self, root: Path) -> tuple[Path, Path, str, str, bytes, dict]:
        repo = root / "repo"
        artifacts = root / "artifacts"
        repo.mkdir()
        artifacts.mkdir()
        run(["git", "init", "-q"], repo)
        run(["git", "config", "user.email", "poc@example.com"], repo)
        run(["git", "config", "user.name", "Protocol POC"], repo)
        (repo / "src").mkdir()
        (repo / "src" / "app.txt").write_text("one\n", encoding="utf-8")
        run(["git", "add", "src/app.txt"], repo)
        run(["git", "commit", "-q", "-m", "base"], repo)
        base = run(["git", "rev-parse", "HEAD"], repo).strip()

        (repo / "src" / "app.txt").write_text("two\n", encoding="utf-8")
        run(["git", "add", "src/app.txt"], repo)
        run(["git", "commit", "-q", "-m", "head"], repo)
        head = run(["git", "rev-parse", "HEAD"], repo).strip()
        patch = run(
            ["git", "diff", "--binary", "--no-ext-diff", f"{base}..{head}", "--"],
            repo,
            text=False,
        )
        (artifacts / "patch.diff").write_bytes(patch)
        numstat = run(["git", "diff", "--numstat", f"{base}..{head}", "--"], repo).strip().split("\t")
        stats = {"additions": int(numstat[0]), "deletions": int(numstat[1]), "path": numstat[2]}
        return repo, artifacts, base, head, patch, stats

    def make_contracts(
        self,
        repo: Path,
        artifacts: Path,
        base: str,
        head: str,
        patch: bytes,
        stats: dict,
        *,
        command: str,
    ) -> tuple[dict, dict]:
        order = work_order(command=command)
        manifest = delivery_manifest(base, head)
        manifest["patch"] = {
            "path": "patch.diff",
            "sha256": hashlib.sha256(patch).hexdigest(),
            "bytes": len(patch),
        }
        manifest["changed_files"] = [
            {
                "path": stats["path"],
                "status": "modified",
                "additions": stats["additions"],
                "deletions": stats["deletions"],
            }
        ]
        seal(manifest)
        return order, manifest

    def test_delivery_gate_accepts_authoritative_diff_and_independent_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, artifacts, base, head, patch, stats = self.make_repo(Path(tmp))
            command = "python3 -c 'from pathlib import Path; assert Path(\"src/app.txt\").read_text() == \"two\\n\"'"
            order, manifest = self.make_contracts(repo, artifacts, base, head, patch, stats, command=command)
            result = verify_delivery(repo, artifacts, order, manifest)
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(result.evidence["git"]["diff_sha256"], hashlib.sha256(patch).hexdigest())
            self.assertEqual(result.evidence["test_reruns"][0]["exit_code"], 0)

    def test_authoritative_git_diff_mismatch_is_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, artifacts, base, head, patch, stats = self.make_repo(Path(tmp))
            reported = patch + b"\nforged runtime line\n"
            (artifacts / "patch.diff").write_bytes(reported)
            order, manifest = self.make_contracts(
                repo,
                artifacts,
                base,
                head,
                reported,
                stats,
                command="python3 -c 'raise SystemExit(0)'",
            )
            result = verify_delivery(repo, artifacts, order, manifest)
            self.assertIn("GIT_DIFF_MISMATCH", finding_codes(result))

    def test_fake_worker_test_claim_is_detected_by_independent_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, artifacts, base, head, patch, stats = self.make_repo(Path(tmp))
            order, manifest = self.make_contracts(
                repo,
                artifacts,
                base,
                head,
                patch,
                stats,
                command="python3 -c 'raise SystemExit(7)'",
            )
            self.assertEqual(manifest["spec_results"][0]["status"], "pass")
            self.assertEqual(manifest["tests"][0]["exit_code"], 0)
            result = verify_delivery(repo, artifacts, order, manifest)
            self.assertIn("TEST_RERUN_FAILED", finding_codes(result))
            self.assertEqual(result.evidence["test_reruns"][0]["exit_code"], 7)

    def test_dirty_verification_worktree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, artifacts, base, head, patch, stats = self.make_repo(Path(tmp))
            order, manifest = self.make_contracts(
                repo,
                artifacts,
                base,
                head,
                patch,
                stats,
                command="python3 -c 'raise SystemExit(0)'",
            )
            (repo / "untracked-worker-note.txt").write_text("not committed", encoding="utf-8")
            result = verify_delivery(repo, artifacts, order, manifest)
            self.assertIn("GIT_WORKTREE_DIRTY", finding_codes(result))
            self.assertEqual(result.evidence["test_reruns"], [])


class ReviewPacketGateTests(unittest.TestCase):
    def make_packet(self, root: Path) -> dict:
        content = b"small authoritative patch\n"
        (root / "patch.diff").write_bytes(content)
        reference = {
            "path": "patch.diff",
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        packet = task_review_packet(reference)
        packet["packet_budget"] = {"estimated_tokens": 100000, "max_tokens": 100000}
        return packet

    def test_packet_accepts_targeted_context_and_hashed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root)
            result = validate_review_packet(packet, root)
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(result.evidence["packet"]["evidence_refs"], 1)
            self.assertLess(result.evidence["packet"]["estimated_tokens"], 100000)

    def test_packet_budget_is_recomputed_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root)
            packet["inline_diff"] = "x" * 10000
            packet["packet_budget"] = {"estimated_tokens": 10, "max_tokens": 10}
            seal(packet)
            result = validate_review_packet(packet, root)
            self.assertIn("PACKET_TOKEN_BUDGET", finding_codes(result))
            self.assertIn("PACKET_ESTIMATE_UNDERSTATED", finding_codes(result))

    def test_packet_rejects_repository_glob_in_context_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root)
            packet["context_slices"][0]["path"] = "src/**"
            seal(packet)
            result = validate_review_packet(packet, root)
            self.assertIn("PACKET_CONTEXT_NOT_TARGETED", finding_codes(result))

    def test_packet_rejects_missing_or_changed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root)
            (root / "patch.diff").write_text("tampered", encoding="utf-8")
            result = validate_review_packet(packet, root)
            self.assertIn("EVIDENCE_HASH_MISMATCH", finding_codes(result))
            self.assertIn("EVIDENCE_SIZE_MISMATCH", finding_codes(result))

    def test_packet_schema_blocks_raw_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root)
            packet["raw_transcript"] = "worker conversation"
            seal(packet)
            result = validate_review_packet(packet, root)
            self.assertIn("SCHEMA_INVALID", finding_codes(result))


if __name__ == "__main__":
    unittest.main()
