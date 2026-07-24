from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "token-firewall-team" / "SKILL.md"
RUNBOOK = ROOT / "skills" / "token-firewall-team" / "references" / "runbook.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
MINIMAX_GUIDE = ROOT / "docs" / "native-minimax-m3.md"
MINIMAX_AGENT = ROOT / "examples" / "codex" / "minimax-m3.toml"
MINIMAX_PROVIDER = ROOT / "examples" / "codex" / "minimax-provider.toml"
MINIMAX_CATALOG = ROOT / "examples" / "codex" / "minimax-m3-model-catalog.json"
CLI = (
    ROOT
    / "skills"
    / "token-firewall-team"
    / "scripts"
    / "token_firewall_runtime"
    / "tools"
    / "token_firewall"
    / "cli.py"
)


class NativePolicyTests(unittest.TestCase):
    def test_native_codex_is_the_default_control_plane(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("Use Codex's native Agent lifecycle", skill)
        self.assertIn("Terra for read-heavy reconnaissance", skill)
        self.assertIn("GPT-5.6 for ambiguous semantic implementation", skill)

    def test_external_adapters_require_an_explicit_third_party_request(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("only when the user explicitly requests execution through an external harness", skill)
        self.assertIn("never silently falls back", skill)
        cli = CLI.read_text(encoding="utf-8")
        self.assertNotIn('default="minimax"', cli)
        self.assertIn(
            'runtime_run.add_argument("--worker-runtime", choices=["codex", "claude", "minimax"], required=True)',
            cli,
        )

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

    def test_native_minimax_agent_uses_current_custom_agent_schema(self) -> None:
        agent = tomllib.loads(MINIMAX_AGENT.read_text(encoding="utf-8"))
        self.assertEqual(agent["name"], "minimax_m3")
        self.assertEqual(agent["model"], "MiniMax-M3")
        self.assertEqual(agent["model_provider"], "minimax")
        for required in ("name", "description", "developer_instructions"):
            self.assertTrue(agent[required])

        provider = tomllib.loads(MINIMAX_PROVIDER.read_text(encoding="utf-8"))
        minimax = provider["model_providers"]["minimax"]
        self.assertEqual(minimax["wire_api"], "responses")
        self.assertEqual(minimax["env_key"], "MINIMAX_API_KEY")
        self.assertNotIn("experimental_bearer_token", minimax)

    def test_native_minimax_catalog_and_supervision_policy(self) -> None:
        catalog = json.loads(MINIMAX_CATALOG.read_text(encoding="utf-8"))
        model = catalog["models"][0]
        self.assertEqual(model["slug"], "MiniMax-M3")
        self.assertEqual(model["input_modalities"], ["text", "image"])
        self.assertTrue(model["supports_parallel_tool_calls"])

        active = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL, RUNBOOK, ARCHITECTURE, MINIMAX_GUIDE)
        )
        self.assertIn("minimax_m3", active)
        self.assertIn("fresh non-M3 Verifier", active)
        self.assertIn("No Claude Code or MiniMax Code process is required", active)


if __name__ == "__main__":
    unittest.main()
