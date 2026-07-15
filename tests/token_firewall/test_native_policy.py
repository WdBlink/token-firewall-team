from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "token-firewall-team" / "SKILL.md"
RUNBOOK = ROOT / "skills" / "token-firewall-team" / "references" / "runbook.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"


class NativePolicyTests(unittest.TestCase):
    def test_native_codex_is_the_default_control_plane(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("Use Codex's native Agent lifecycle", skill)
        self.assertIn("Terra for read-heavy reconnaissance", skill)
        self.assertIn("GPT-5.6 for ambiguous semantic implementation", skill)

    def test_external_adapters_require_an_explicit_third_party_request(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("only when the user explicitly requests a third-party platform", skill)
        self.assertIn("never silently falls back", skill)

    def test_no_file_mailbox_native_scheduler_is_documented(self) -> None:
        active = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL, RUNBOOK, ARCHITECTURE)
        )
        forbidden = (
            "--worker-runtime native",
            "runtime-preflight --runtime native",
            "host-dispatch.json",
            "host-result.json",
            "native-host-unknown",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, active)

    def test_runtime_has_no_native_host_adapter(self) -> None:
        runtime = (
            ROOT
            / "skills"
            / "token-firewall-team"
            / "scripts"
            / "token_firewall_runtime"
            / "tools"
            / "token_firewall"
            / "runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("class NativeHostAdapter", runtime)


if __name__ == "__main__":
    unittest.main()
