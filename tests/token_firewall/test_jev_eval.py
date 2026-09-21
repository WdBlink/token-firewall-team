import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.token_firewall.jev_eval import build_eval_request, eval_key, run_eval


class JevEvalTests(unittest.TestCase):
    def packet(self):
        return dict(task="Fix parser", acceptance_spec="Accept 1, reject empty; integer only", delivery="Bounded patch", evidence="pytest: 3 passed", risk="low", worker_model="private")

    def response(self):
        return {"model": "jev-1.13.0", "usage": {"input_tokens": 10}, "answers": {
            **{key: {"type": "score", "score": 3, "confidence": .9} for key in ("requirements", "boundary", "grounding")},
            "feedback": {"type": "choice", "choice": "no_gap_observed", "confidence": .9}}}

    def test_scoring_keeps_review_and_exact_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "eval.json"
            result = run_eval(self.packet(), out, api_key="secret-key", post=lambda *args: self.response())
            self.assertEqual(result["status"], "SCORED")
            self.assertTrue(result["requires_independent_review"])
            self.assertFalse(result["authoritative"])
            self.assertEqual(json.loads(out.read_text())["request"], build_eval_request(self.packet()))
            self.assertNotIn("worker_model", out.read_text())
            self.assertNotIn("secret-key", out.read_text())
            with self.assertRaises(FileExistsError):
                run_eval(self.packet(), out, api_key="secret-key")

    def test_service_failure_and_bad_answers_escalate(self):
        def failing(*args):
            raise RuntimeError("secret-key private response")
        bad = self.response()
        bad["answers"]["grounding"]["score"] = float("nan")
        for post in (failing, lambda *args: bad, lambda *args: {}):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "eval.json"
                result = run_eval(self.packet(), out, api_key="secret-key", post=post)
                self.assertEqual(result["status"], "ESCALATE")
                self.assertNotIn("secret-key", out.read_text())

    def test_missing_key_and_terminal_prompt(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.stdin.isatty", return_value=False):
            with self.assertRaisesRegex(ValueError, "TYPESAFE_API_KEY_REQUIRED"):
                eval_key()
        with patch.dict(os.environ, {}, clear=True), patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", return_value="secret-key"):
            self.assertEqual(eval_key(), "secret-key")

    def test_rejects_invalid_packet_before_network(self):
        for packet in ({}, self.packet() | {"risk": "unknown"}, self.packet() | {"evidence": ""}, self.packet() | {"delivery": "x" * 64000}):
            with self.assertRaises(ValueError):
                build_eval_request(packet)
