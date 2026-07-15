from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from tools.token_firewall.observability import ExternalRunObserver  # noqa: E402
from tools.token_firewall.runtime import (  # noqa: E402
    ClaudeCodeAdapter,
    RuntimeRequest,
    RuntimeResult,
    RuntimeStatus,
    _MonitoredProcessResult,
    _run_monitored_process,
)
from tools.token_firewall.schema import SchemaRegistry  # noqa: E402


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if "--version" in sys.argv:
    print("fake-claude 1.0")
    raise SystemExit(0)

prompt = sys.argv[-1]
pid_file = os.environ.get("TOKEN_FIREWALL_TEST_PID_FILE")

def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)

def spawn_descendant():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    if pid_file:
        Path(pid_file).write_text(str(child.pid), encoding="utf-8")
    return child

if prompt == "startup-silent":
    spawn_descendant()
    time.sleep(60)
elif prompt == "silent":
    spawn_descendant()
    emit({"type": "system", "subtype": "init", "session_id": "session-silent"})
    time.sleep(60)
elif prompt == "interrupt":
    spawn_descendant()
    emit({"type": "system", "subtype": "init", "session_id": "session-interrupt"})
    time.sleep(60)
elif prompt == "malformed":
    emit({"type": "system", "subtype": "init", "session_id": "session-malformed"})
    print("not-json", flush=True)
else:
    if prompt == "devnull":
        with open(os.devnull, "w", encoding="utf-8") as sink:
            subprocess.run([sys.executable, "-c", "print('ok')"], stdin=subprocess.DEVNULL, stdout=sink, check=True)
    emit({"type": "system", "subtype": "init", "session_id": "session-ok"})
    if prompt == "periodic":
        for index in range(6):
            time.sleep(0.05)
            emit({"type": "assistant", "subtype": "progress", "index": index})
    emit({
        "type": "result",
        "session_id": "session-ok",
        "is_error": False,
        "result": "done",
        "structured_output": {"ok": True},
        "usage": {
            "input_tokens": 2,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0
        },
        "modelUsage": {"MiniMax-M3": {"inputTokens": 2, "outputTokens": 1}},
        "total_cost_usd": 0.001
    })
'''


class ClaudeRuntimeWatchdogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.artifacts = self.root / "artifacts"
        self.schema_dir = self.root / "schemas"
        self.schema_dir.mkdir()
        self.schema_path = self.schema_dir / "result.schema.json"
        self.schema_path.write_text(
            json.dumps(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "test/result@0.1",
                    "type": "object",
                    "required": ["ok"],
                    "properties": {"ok": {"const": True}},
                    "additionalProperties": False,
                }
            ),
            encoding="utf-8",
        )
        self.executable = self.root / "fake-claude"
        self.executable.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.executable.chmod(self.executable.stat().st_mode | stat.S_IXUSR)
        self.registry = SchemaRegistry(self.schema_dir)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def request(
        self,
        prompt: str,
        *,
        startup: float = 1.0,
        stall: float = 0.5,
        timeout: float = 2.0,
        grace: float = 0.1,
    ) -> RuntimeRequest:
        return RuntimeRequest(
            role="worker",
            workspace=self.workspace,
            artifact_dir=self.artifacts,
            prompt=prompt,
            output_schema_path=self.schema_path,
            output_schema_id="test/result@0.1",
            title="watchdog test",
            model="MiniMax-M3",
            timeout_seconds=timeout,
            startup_timeout_seconds=startup,
            stall_timeout_seconds=stall,
            termination_grace_seconds=grace,
            poll_interval_seconds=0.02,
        )

    def adapter(self) -> ClaudeCodeAdapter:
        return ClaudeCodeAdapter(str(self.executable), registry=self.registry)

    @staticmethod
    def assert_pid_gone(test: unittest.TestCase, path: Path) -> None:
        deadline = time.monotonic() + 2.0
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        test.assertTrue(path.exists(), "fake Claude did not record its descendant PID")
        pid = int(path.read_text(encoding="utf-8"))
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        test.fail(f"descendant PID {pid} survived Runtime shutdown")

    @mock.patch("tools.token_firewall.runtime.platform.system", return_value="Linux")
    def test_silent_child_stalls_and_process_group_is_cleaned(self, _platform) -> None:
        pid_file = self.root / "silent-child.pid"
        traces = []
        started = time.monotonic()
        with mock.patch.dict(os.environ, {"TOKEN_FIREWALL_TEST_PID_FILE": str(pid_file)}):
            result = self.adapter().execute(
                self.request("silent", stall=0.2),
                on_trace=lambda kind, details: traces.append((kind, details)),
            )

        self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(result.status, RuntimeStatus.FAILED)
        self.assertIn("no stdout/stderr activity", result.error or "")
        self.assertIn("runtime.stalled", [kind for kind, _ in traces])
        self.assert_pid_gone(self, pid_file)

    @mock.patch("tools.token_firewall.runtime.platform.system", return_value="Linux")
    def test_startup_without_any_output_has_a_separate_deadline(self, _platform) -> None:
        pid_file = self.root / "startup-child.pid"
        with mock.patch.dict(os.environ, {"TOKEN_FIREWALL_TEST_PID_FILE": str(pid_file)}):
            result = self.adapter().execute(
                self.request("startup-silent", startup=0.6, stall=0.1),
            )

        self.assertEqual(result.status, RuntimeStatus.FAILED)
        self.assertIn("startup produced no stdout/stderr activity", result.error or "")
        self.assert_pid_gone(self, pid_file)

    @mock.patch("tools.token_firewall.runtime.platform.system", return_value="Linux")
    def test_periodic_stream_activity_prevents_false_stall(self, _platform) -> None:
        traces = []
        result = self.adapter().execute(
            self.request("periodic", stall=0.15),
            on_trace=lambda kind, details: traces.append((kind, details)),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.session_id, "session-ok")
        self.assertEqual(result.model_effective, "MiniMax-M3")
        self.assertTrue(result.model_effective_verified)
        self.assertEqual(result.final_output, {"ok": True})
        self.assertIn("runtime.polled", [kind for kind, _ in traces])
        self.assertNotIn("runtime.stalled", [kind for kind, _ in traces])

    @mock.patch("tools.token_firewall.runtime.platform.system", return_value="Linux")
    def test_normal_stream_result_keeps_schema_and_usage_contract(self, _platform) -> None:
        result = self.adapter().execute(self.request("success"))

        self.assertTrue(result.ok)
        self.assertEqual(result.usage["input_tokens"], 2)
        self.assertEqual(result.usage["output_tokens"], 1)
        self.assertTrue(result.usage["complete"])
        events = Path(result.artifact_refs["result"]).read_text(encoding="utf-8")
        self.assertIn('"type":"system"', events)
        self.assertIn('"type":"result"', events)

    @unittest.skipUnless(sys.platform == "darwin", "sandbox-exec is macOS-only")
    def test_macos_sandbox_allows_devnull_for_nested_tools(self) -> None:
        event = {
            "type": "result",
            "session_id": "session-ok",
            "is_error": False,
            "result": "done",
            "structured_output": {"ok": True},
            "usage": {"input_tokens": 2, "output_tokens": 1},
            "modelUsage": {"MiniMax-M3": {"inputTokens": 2, "outputTokens": 1}},
            "total_cost_usd": 0.001,
        }
        monitored = _MonitoredProcessResult(
            returncode=0,
            stdout=json.dumps(event),
            stderr="",
            elapsed_seconds=0.01,
        )
        with mock.patch("tools.token_firewall.runtime._run_monitored_process", return_value=monitored):
            result = self.adapter().execute(self.request("devnull", startup=2.0, stall=2.0))

        self.assertTrue(result.ok, result.error)
        isolation = json.loads(Path(result.artifact_refs["isolation"]).read_text(encoding="utf-8"))
        profile = Path(isolation["profile"]).read_text(encoding="utf-8")
        self.assertIn("(allow signal (target same-sandbox))", profile)
        self.assertIn('(allow file-read* (literal "/dev/null"))', profile)
        self.assertIn('(allow file-write* (literal "/dev/null"))', profile)
        self.assertIn(
            '(allow file-write* (regex #"^/tmp/claude-[^/]+-cwd$") '
            '(regex #"^/private/tmp/claude-[^/]+-cwd$"))',
            profile,
        )

    @mock.patch("tools.token_firewall.runtime.platform.system", return_value="Linux")
    def test_overall_timeout_is_distinct_from_inactivity(self, _platform) -> None:
        pid_file = self.root / "timeout-child.pid"
        with mock.patch.dict(os.environ, {"TOKEN_FIREWALL_TEST_PID_FILE": str(pid_file)}):
            result = self.adapter().execute(self.request("silent", stall=0, timeout=1.0))

        self.assertEqual(result.status, RuntimeStatus.TIMED_OUT)
        self.assertIn("overall timeout", result.error or "")
        self.assert_pid_gone(self, pid_file)

    @mock.patch("tools.token_firewall.runtime.platform.system", return_value="Linux")
    def test_malformed_stream_fails_after_exit_not_as_stall(self, _platform) -> None:
        result = self.adapter().execute(self.request("malformed"))

        self.assertEqual(result.status, RuntimeStatus.FAILED)
        self.assertNotIn("activity", result.error or "")
        self.assertIn("no JSON object", result.error or "")

    def test_callback_interrupt_cleans_the_process_group(self) -> None:
        pid_file = self.root / "interrupt-child.pid"

        def interrupt(_stream: str, _count: int) -> None:
            raise KeyboardInterrupt

        with mock.patch.dict(os.environ, {"TOKEN_FIREWALL_TEST_PID_FILE": str(pid_file)}):
            with self.assertRaises(KeyboardInterrupt):
                _run_monitored_process(
                    [str(self.executable), "interrupt"],
                    cwd=self.workspace,
                    env=os.environ.copy(),
                    timeout_seconds=2.0,
                    startup_timeout_seconds=1.0,
                    stall_timeout_seconds=1.0,
                    poll_interval_seconds=0.02,
                    termination_grace_seconds=0.1,
                    on_activity=interrupt,
                )
        self.assert_pid_gone(self, pid_file)

    def test_observer_records_stall_then_terminal_failure(self) -> None:
        observer = ExternalRunObserver.create(
            self.root / "observer",
            run_id="run-watchdog",
            mission_id="mission-watchdog",
            task_id="T-WATCHDOG",
            stage="worker",
            runtime="claude-code",
            model="MiniMax-M3",
            heartbeat_seconds=1,
        )
        observer.trace("runtime.started", {"runtime": "claude-code"})
        observer.trace("runtime.stalled", {"runtime": "claude-code"})
        observer.complete(
            RuntimeResult(
                runtime="claude-code",
                status=RuntimeStatus.FAILED,
                session_id=None,
                final_output=None,
                exit_code=-15,
                error="inactivity stall",
            )
        )

        self.assertEqual(observer.ledger.state["status"], "FAILED")
        kinds = [event["kind"] for event in observer.ledger.events()]
        self.assertIn("run.stalled", kinds)
        self.assertEqual(kinds[-1], "run.failed")


if __name__ == "__main__":
    unittest.main()
