from __future__ import annotations

import json
import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.runtime import (
    CodexCliAdapter,
    ClaudeCodeAdapter,
    MavisSessionAdapter,
    RecoveredPatchAdapter,
    RecoveredMavisReadOnlyAdapter,
    RuntimeRequest,
    RuntimeStatus,
    WORKER_REPORT_SCHEMA_ID,
    VERIFIER_REPORT_SCHEMA_ID,
    extract_codex_usage,
    extract_json_object,
    extract_mavis_usage,
)

from tests.token_firewall.fixtures import runtime_worker_report


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = (
    ROOT
    / "skills"
    / "token-firewall-team"
    / "scripts"
    / "token_firewall_runtime"
    / "tools"
    / "token_firewall"
)
SCHEMA = PACKAGE / "schemas" / "runtime-worker-report.schema.json"
VERIFIER_SCHEMA = PACKAGE / "schemas" / "runtime-verifier-report.schema.json"


def executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class RuntimeAdapterContractTests(unittest.TestCase):
    def test_extract_json_accepts_fenced_or_wrapped_object(self) -> None:
        self.assertEqual(extract_json_object('```json\n{"ok": true}\n```'), {"ok": True})
        self.assertEqual(extract_json_object('summary\n{"ok": true}\nend'), {"ok": True})
        nested = {"status": "DELIVERED", "commit": {"head_commit": "b" * 40, "message": "ok"}}
        self.assertEqual(extract_json_object(f"summary\n{json.dumps(nested)}\nend"), nested)

    def test_extract_json_repairs_source_literal_escape_without_selecting_nested_object(self) -> None:
        text = '''report\n```json
{"schema":"example@1","finding":{"evidence":"reject \\x1f input"}}
```\nVERDICT'''
        self.assertEqual(
            extract_json_object(text),
            {"schema": "example@1", "finding": {"evidence": r"reject \x1f input"}},
        )
        quoted = '{"schema":"example@1","evidence":"line 11 "=" in segment","items":[]}'
        self.assertEqual(
            extract_json_object(quoted),
            {"schema": "example@1", "evidence": 'line 11 "=" in segment', "items": []},
        )

    def test_codex_usage_uses_subset_semantics_without_double_counting(self) -> None:
        usage = extract_codex_usage([
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 10,
                },
            }
        ])
        self.assertEqual(usage["total_tokens"], 120)
        self.assertEqual(usage["cache_read_tokens"], 80)
        self.assertEqual(usage["reasoning_tokens"], 10)
        self.assertTrue(usage["complete"])

    def test_codex_usage_fails_closed_on_missing_or_duplicate_terminal_event(self) -> None:
        self.assertFalse(extract_codex_usage([])["complete"])
        event = {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 5,
                "reasoning_output_tokens": 0,
            },
        }
        self.assertFalse(extract_codex_usage([event, event])["complete"])

    def test_mavis_usage_cross_checks_rows_and_messages(self) -> None:
        payload = {
            "summary": {
                "inputTokens": 200,
                "outputTokens": 121,
                "reasoningTokens": 0,
                "cacheReadTokens": 10,
                "cacheWriteTokens": 0,
                "totalTokens": 321,
                "costUsd": 0.01,
                "turns": 1,
            },
            "rows": [{
                "sessionId": "mvs_test",
                "turnId": "msg_test",
                "model": "minimax/MiniMax-M3",
                "inputTokens": 200,
                "outputTokens": 121,
                "reasoningTokens": 0,
                "cacheReadTokens": 10,
                "cacheWriteTokens": 0,
                "costUsd": 0.01,
            }],
        }
        usage = extract_mavis_usage(
            payload,
            [{"role": "assistant", "msg_id": "msg_test", "usage": {"total_tokens": 1}}],
            "mvs_test",
        )
        self.assertTrue(usage["complete"])
        self.assertEqual(usage["native_total_tokens"], 321)
        self.assertEqual(usage["total_tokens"], 331)

        usage_with_unbilled_snapshot = extract_mavis_usage(
            payload,
            [
                {"role": "assistant", "msg_id": "msg_test", "usage": {"total_tokens": 1}},
                {
                    "role": "assistant",
                    "msg_id": "msg_interrupted_snapshot",
                    "usage": {"total_tokens": 99},
                },
            ],
            "mvs_test",
        )
        self.assertTrue(usage_with_unbilled_snapshot["complete"])

        usage_missing_billed_message = extract_mavis_usage(payload, [], "mvs_test")
        self.assertFalse(usage_missing_billed_message["complete"])

    def test_codex_adapter_uses_structured_noninteractive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = executable(
                root / "fake-codex",
                """#!/usr/bin/env python3
import json, pathlib, sys
if '--version' in sys.argv:
    print('codex-cli test')
    raise SystemExit(0)
args = sys.argv
workspace = pathlib.Path(args[args.index('-C') + 1])
output = pathlib.Path(args[args.index('--output-last-message') + 1])
prompt = sys.stdin.read()
assert 'Immutable Work Order' in prompt
report = {
  'schema': 'token-firewall/runtime-worker-report@0.1',
  'status': 'DELIVERED',
  'summary': 'fake codex delivered',
  'spec_results': [{'spec_id':'SPEC-001-01','status':'pass','evidence_summary':'ok'}],
  'tests': [{'command':'python3 -c "raise SystemExit(0)"','exit_code':0,'summary':'ok'}],
  'deviations': [], 'uncertainties': [], 'failed_attempts_summary': [],
  'changed_files_claim': ['src/app.txt'],
  'context_slices': [{'path':'src/app.txt','start':1,'end':1,'reason':'changed behavior'}],
  'commit': {'head_commit':'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','message':'fake'},
  'blockers': []
}
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report))
print(json.dumps({'type':'thread.started','thread_id':'codex-test-session'}))
""",
            )
            workspace = root / "workspace"
            artifacts = root / "artifacts"
            workspace.mkdir()
            adapter = CodexCliAdapter(str(fake))
            self.assertTrue(adapter.preflight().ok)
            result = adapter.execute(
                RuntimeRequest(
                    role="worker",
                    workspace=workspace,
                    artifact_dir=artifacts,
                    prompt="Immutable Work Order: test",
                    output_schema_path=SCHEMA,
                    output_schema_id=WORKER_REPORT_SCHEMA_ID,
                    title="adapter test",
                    timeout_seconds=10,
                )
            )
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.session_id, "codex-test-session")
            self.assertTrue(Path(result.artifact_refs["events"]).exists())

    def test_codex_timeout_preserves_thread_id_from_partial_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = executable(
                root / "slow-codex",
                """#!/usr/bin/env python3
import json, sys, time
if '--version' in sys.argv:
    print('codex-cli test')
    raise SystemExit(0)
print(json.dumps({'type':'thread.started','thread_id':'codex-timeout-session'}), flush=True)
time.sleep(5)
""",
            )
            workspace = root / "workspace"
            workspace.mkdir()
            result = CodexCliAdapter(str(fake)).execute(RuntimeRequest(
                role="worker", workspace=workspace, artifact_dir=root / "artifacts",
                prompt="Immutable Work Order: test", output_schema_path=SCHEMA,
                output_schema_id=WORKER_REPORT_SCHEMA_ID, title="timeout", timeout_seconds=1,
            ))
            self.assertEqual(result.status, RuntimeStatus.TIMED_OUT)
            self.assertEqual(result.session_id, "codex-timeout-session")
            self.assertFalse(result.usage["complete"])

    def test_recovered_patch_adapter_replays_frozen_delivery_without_model_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
            (workspace / "src").mkdir()
            target = workspace / "src" / "app.txt"
            target.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "src/app.txt"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=workspace, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            target.write_text("after\n", encoding="utf-8")
            patch_path = root / "worker.patch"
            patch_path.write_text(
                subprocess.run(
                    ["git", "diff", "--binary"], cwd=workspace, check=True,
                    capture_output=True, text=True,
                ).stdout,
                encoding="utf-8",
            )
            subprocess.run(["git", "restore", "src/app.txt"], cwd=workspace, check=True)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            report = runtime_worker_report(base)
            (snapshot / "worker-report.json").write_text(json.dumps(report), encoding="utf-8")
            (snapshot / "stage-result.json").write_text(json.dumps({
                "runtime": "minimax-mavis",
                "session_id": "mvs_frozen",
                "usage": {
                    "input_tokens": 10, "output_tokens": 2, "reasoning_tokens": 0,
                    "cache_read_tokens": 0, "cache_write_tokens": 0,
                    "total_tokens": 12, "native_total_tokens": 12,
                    "source": "fixture", "complete": True,
                },
            }), encoding="utf-8")
            adapter = RecoveredPatchAdapter(snapshot, patch_path, expected_base_commit=base)
            self.assertTrue(adapter.preflight().ok)
            result = adapter.execute(RuntimeRequest(
                role="worker", workspace=workspace, artifact_dir=root / "artifacts",
                prompt="unused", output_schema_path=SCHEMA,
                output_schema_id=WORKER_REPORT_SCHEMA_ID, title="recover",
            ))
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.session_id, "mvs_frozen")
            self.assertEqual(result.final_output["status"], "CHANGES_READY")
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")

    def test_read_only_snapshot_remaps_commit_only_for_identical_frozen_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
            target = workspace / "value.txt"
            target.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "value.txt"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=workspace, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            target.write_text("after\n", encoding="utf-8")
            patch = subprocess.run(
                ["git", "diff", "--binary"], cwd=workspace, check=True,
                capture_output=True,
            ).stdout
            source_patch = root / "source.patch"
            source_patch.write_bytes(patch)
            subprocess.run(["git", "add", "value.txt"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "replayed candidate"], cwd=workspace, check=True)
            current = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, check=True,
                capture_output=True, text=True,
            ).stdout.strip()

            source_commit = "a" * 40
            session_id = "mvs_verifier_snapshot"
            report = {
                "schema": VERIFIER_REPORT_SCHEMA_ID, "status": "PASS",
                "reviewed_commit": source_commit, "summary": "verified frozen patch",
                "spec_results": [{"spec_id": "SPEC-001-01", "status": "pass", "evidence": "ok"}],
                "findings": [], "coverage_gaps": [], "requested_context": [],
            }
            snapshot = root / "final" / "runtime-verifier"
            snapshot.mkdir(parents=True)
            (snapshot / "session-info.json").write_text(
                json.dumps({"session": {"sessionId": session_id}}), encoding="utf-8",
            )
            (snapshot / "session-messages.json").write_text(json.dumps({"messages": [{
                "role": "assistant", "msg_id": "msg_verifier", "msg_type": 1,
                "msg_content": json.dumps(report), "usage": {"total_tokens": 30},
            }]}), encoding="utf-8")
            (snapshot / "session-usage.stdout.json").write_text(json.dumps({
                "summary": {
                    "inputTokens": 20, "outputTokens": 10, "reasoningTokens": 0,
                    "cacheReadTokens": 0, "cacheWriteTokens": 0, "totalTokens": 30,
                    "costUsd": 0.01, "turns": 1,
                },
                "rows": [{
                    "sessionId": session_id, "turnId": "msg_verifier", "model": "minimax/MiniMax-M3",
                    "inputTokens": 20, "outputTokens": 10, "reasoningTokens": 0,
                    "cacheReadTokens": 0, "cacheWriteTokens": 0, "costUsd": 0.01,
                }],
            }), encoding="utf-8")
            (snapshot.parent / "review-packet.json").write_text(json.dumps({
                "commit_range": {"base": base, "head": source_commit},
                "integration_commit": source_commit,
                "diff_summary": {"patch_ref": {"sha256": hashlib.sha256(patch).hexdigest()}},
            }), encoding="utf-8")
            adapter = RecoveredMavisReadOnlyAdapter(
                MavisSessionAdapter(str(root / "missing-minimax")), session_id=session_id,
                snapshot_dir=snapshot, source_patch=source_patch, expected_base_commit=base,
            )
            self.assertTrue(adapter.preflight().ok)
            result = adapter.execute(RuntimeRequest(
                role="verifier", workspace=workspace, artifact_dir=root / "recovered",
                prompt=f"Review commit {current}", output_schema_path=VERIFIER_SCHEMA,
                output_schema_id=VERIFIER_REPORT_SCHEMA_ID, title="snapshot remap",
            ))
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.final_output["reviewed_commit"], current)
            self.assertTrue(Path(result.artifact_refs["commit_remap"]).is_file())

    def test_mavis_adapter_maps_session_api_to_same_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = json.dumps(runtime_worker_report(), ensure_ascii=False)
            fake = executable(
                root / "fake-minimax",
                f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args == ['status']:
    print(json.dumps({{'status':'running'}}))
elif args[:2] == ['agent','list']:
    print(json.dumps([{{'name':'coder'}}]))
elif args[:2] == ['session','new']:
    print('Root session created: mvs_test')
    print(json.dumps({{'sessionId':'mvs_test'}}))
elif args[:2] == ['session','info']:
    print(json.dumps({{'session':{{'status':{{'type':'finished'}}}}}}))
elif args[:2] == ['session','messages']:
    assert args[2:4] == ['--limit', '500'], args
    print(json.dumps({{'messages':[{{'role':'assistant','msg_id':'msg_test','msg_type':1,'msg_content':{report_json!r},'usage':{{'total_tokens':321}}}}]}}))
elif args[:2] == ['session','diff']:
    print(json.dumps({{'diffs':[]}}))
elif args[:2] == ['usage','session']:
    print(json.dumps({{
      'summary': {{'inputTokens':200,'outputTokens':121,'reasoningTokens':0,'cacheReadTokens':10,'cacheWriteTokens':0,'totalTokens':321,'costUsd':0.01,'turns':1}},
      'rows': [{{'sessionId':'mvs_test','turnId':'msg_test','model':'minimax/MiniMax-M3','inputTokens':200,'outputTokens':121,'reasoningTokens':0,'cacheReadTokens':10,'cacheWriteTokens':0,'costUsd':0.01}}]
    }}))
else:
    print(json.dumps({{'error':args}}))
    raise SystemExit(2)
""",
            )
            adapter = MavisSessionAdapter(str(fake), agent="coder")
            self.assertTrue(adapter.preflight().ok)
            result = adapter.execute(
                RuntimeRequest(
                    role="worker",
                    workspace=root / "workspace",
                    artifact_dir=root / "artifacts",
                    prompt="test",
                    output_schema_path=SCHEMA,
                    output_schema_id=WORKER_REPORT_SCHEMA_ID,
                    title="mavis adapter test",
                    timeout_seconds=10,
                    poll_interval_seconds=0.01,
                )
            )
            self.assertEqual(result.status, RuntimeStatus.SUCCEEDED, result.error)
            self.assertEqual(result.session_id, "mvs_test")
            self.assertEqual(result.usage["native_total_tokens"], 321)
            self.assertEqual(result.usage["total_tokens"], 331)
            self.assertTrue(result.usage["complete"])
            recovered = adapter.recover_finished_session(
                RuntimeRequest(
                    role="worker",
                    workspace=root / "workspace",
                    artifact_dir=root / "recovered-artifacts",
                    prompt="unused during recovery",
                    output_schema_path=SCHEMA,
                    output_schema_id=WORKER_REPORT_SCHEMA_ID,
                    title="mavis recovery test",
                    timeout_seconds=10,
                ),
                "mvs_test",
            )
            self.assertEqual(recovered.status, RuntimeStatus.SUCCEEDED, recovered.error)
            self.assertEqual(recovered.final_output, result.final_output)
            self.assertTrue(recovered.usage["complete"])
            snapshot_recovered = adapter.recover_delivery_snapshot(
                RuntimeRequest(
                    role="worker",
                    workspace=root / "workspace",
                    artifact_dir=root / "snapshot-recovered-artifacts",
                    prompt="unused during snapshot recovery",
                    output_schema_path=SCHEMA,
                    output_schema_id=WORKER_REPORT_SCHEMA_ID,
                    title="mavis snapshot recovery test",
                    timeout_seconds=10,
                ),
                "mvs_test",
                root / "artifacts",
            )
            self.assertEqual(snapshot_recovered.status, RuntimeStatus.SUCCEEDED, snapshot_recovered.error)
            self.assertEqual(snapshot_recovered.final_output, result.final_output)
            self.assertTrue(snapshot_recovered.usage["complete"])

    def test_claude_adapter_maps_structured_result_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = runtime_worker_report()
            fake = executable(
                root / "fake-claude",
                f"""#!/usr/bin/env python3
import json, pathlib, sys
if '--version' in sys.argv:
    print('claude-code test')
else:
    assert '--print' in sys.argv
    assert '--json-schema' in sys.argv
    schema = json.loads(sys.argv[sys.argv.index('--json-schema') + 1])
    assert '$schema' not in schema and '$id' not in schema and '$defs' not in schema
    assert '$ref' not in json.dumps(schema)
    escaped = False
    try:
        pathlib.Path(__file__).with_name('outside-write.txt').write_text('forbidden')
        escaped = True
    except PermissionError:
        pass
    assert not escaped, 'sandbox allowed write outside workspace/artifacts'
    print(json.dumps({{
      'type':'result','subtype':'success','is_error':False,'session_id':'claude-test-session',
      'total_cost_usd':0.02,
      'usage':{{'input_tokens':100,'output_tokens':20,'cache_read_input_tokens':50,'cache_creation_input_tokens':10}},
      'modelUsage':{{'claude-sonnet-test':{{'inputTokens':100}}}},
      'structured_output':{report!r}
    }}))
""",
            )
            workspace = root / "workspace"
            workspace.mkdir()
            adapter = ClaudeCodeAdapter(str(fake))
            self.assertTrue(adapter.preflight().ok)
            result = adapter.execute(RuntimeRequest(
                role="worker", workspace=workspace, artifact_dir=root / "artifacts", prompt="test",
                output_schema_path=SCHEMA, output_schema_id=WORKER_REPORT_SCHEMA_ID,
                title="claude adapter test", timeout_seconds=10,
            ))
            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.session_id, "claude-test-session")
            self.assertEqual(result.usage["total_tokens"], 180)
            self.assertTrue(result.usage["complete"])
            self.assertEqual(result.model_effective, "claude-sonnet-test")
            self.assertTrue(result.model_effective_verified)


if __name__ == "__main__":
    unittest.main()
