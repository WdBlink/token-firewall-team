---
name: runbook
description: Execute, observe, recover, archive, and evaluate Token Firewall Runtime runs through stable CLI recipes.
---

# Runtime runbook

## Execution Procedure

```python
def execute_route(route, mission, work_orders):
    dispatch_native_agent_directly(route, mission, work_orders)
    observe_state_changes_without_streaming_transcripts()
    gate_delivery_and_packet()
    archive_and_verify_terminal_run()
```

Invoke commands through `python3 <skill>/scripts/token_firewall.py` only for contract validation, recovery, benchmarks, archives, or an explicitly requested third-party Adapter.

## Native Codex route

Use Codex's built-in Agent lifecycle directly. Do not run the Python Runtime as a native mailbox or launch a nested `codex exec` process.

Codex discovers personal custom agents from `~/.codex/agents/*.toml` and project agents from `.codex/agents/*.toml`. A MiniMax-M3 economy Worker should be a personal `minimax_m3` custom agent whose file pins `model = "MiniMax-M3"` and a user-level custom Responses API provider. The custom-agent file must include `name`, `description`, and `developer_instructions`. Provider credentials stay outside the repository. See [`references/native-minimax-m3.md`](native-minimax-m3.md) for the installed-skill setup and policy.

For read-only work, record the repository state, send a bounded artifact contract to a native Agent, use a fresh native evaluator, and prove the repository is unchanged afterward.

For mutating work:

1. record the base commit and clean source state;
2. create an isolated worktree when scopes overlap or the risk warrants it;
3. resolve a Codex-native role/model preference in the calling orchestrator; select `agent_type = "minimax_m3"` for an eligible economy Work Order and avoid a full-history fork;
4. dispatch the bounded Work Order with the absolute worktree path;
5. manage follow-ups, waits, and interruption through native controls;
6. reconstruct delivery from Git truth and rerun approved validators;
7. dispatch a fresh read-only native Verifier;
8. build the blind Review Packet.

The implementation Agent must never evaluate its own delivery. A `minimax_m3` Worker requires a fresh non-M3 Verifier and bounded root review.

## Standalone Runtime compatibility

### Native-first migration note

`runtime-run` no longer has an implicit MiniMax worker. Callers must pass `--worker-runtime codex`, `claude`, or `minimax`; omitting it is a command-line error. This standalone compatibility path is distinct from the native Codex `minimax_m3` custom agent. A third-party Runtime must reflect an explicit external-harness choice and can never be inferred from Economy mode, the MiniMax model name, or token pressure.

Claude Runtime output is now a stream artifact named `claude-events.jsonl` instead of the former `claude-result.json`. Consumers should resolve it through `RuntimeResult.artifact_refs["result"]` and parse JSON Lines, selecting the terminal `type=result` event rather than assuming one JSON envelope. Archived runs that contain the old file remain historical artifacts and are not rewritten.

```bash
TF="python3 /absolute/path/to/token-firewall-team/scripts/token_firewall.py"
$TF runtime-run mission.json work-order.json \
  --repo /path/to/clean/repo --base <full-commit> \
  --run-dir /outside/run --worktree-root /outside/worktrees \
  --worker-runtime codex --worker-model gpt-5.6-terra
```

This external Codex CLI recipe exists for standalone compatibility and frozen experiments. It is not the Codex-host Economy path. Add `--review-runtime codex --reviewer-model gpt-5.6-sol` only when the experiment requires it.

## Optional Runtime matrix

The Skill core has no vendor-Harness installation dependency. A Codex custom agent backed by the MiniMax Responses API is part of the native route and does not use these adapters. Preflight an external route only after the user explicitly requests that external harness:

- MiniMax Code/Mavis present and safe: use `--worker-runtime minimax` for an explicitly requested external MiniMax transport.
- Claude Code present and mapped to M3: use `--worker-runtime claude` only when Claude Code itself was explicitly requested, then require an effective verified MiniMax-M3 identity in `stage-result.json`.
- MiniMax Code absent: the native `minimax_m3` custom agent remains operational when its API provider is configured; report only the explicitly requested MiniMax Code harness as unavailable.
- Claude Code absent: native Codex work remains operational; report that the requested Claude route is unavailable.

Choose the explicitly requested transport before dispatch. Do not fall back inside an active Run; preserve the failed attempt and require a new explicit third-party choice so Harness identity, usage, and failure accounting remain auditable.

## Frozen Benchmark

```bash
$TF benchmark-run identity.json mission.json work-order.json \
  --repo /path/to/clean/repo --run-dir /outside/run \
  --worktree-root /outside/worktrees \
  --worker-runtime codex --worker-model gpt-5.6-terra \
  --verifier-runtime codex --verifier-model gpt-5.6-terra \
  --reviewer-runtime codex --reviewer-model gpt-5.6-sol \
  --hidden-test-id suite@1 --hidden-suite-sha256 <sha256> --defer-hidden
```

Use the full Claude model ID for group E. Mavis production preflight intentionally rejects `bypassPermissions`; the unsafe override is allowed only for disposable experiments and must remain visible in isolation evidence.

For a frozen benchmark that explicitly targets Claude Code transport, a machine-local Claude Code alias may still map to M3 through `--worker-runtime claude --worker-model <alias>`. This is not the operational economy route. Accept the benchmark route only when the Stage artifact has `model_effective_verified=true` and an effective MiniMax-M3 model. A frozen Worker can be replayed without another model turn:

```bash
$TF runtime-run mission.json work-order.json --repo /clean/repo --base <commit> \
  --run-dir /new/run --worktree-root /new/worktrees \
  --worker-runtime claude --worker-model <verified-m3-alias> \
  --recover-worker-runtime-snapshot /old/runtime-worker \
  --recover-worker-patch /old/patch.diff
```

## Observe, finalize, archive

```bash
$TF observe-status /outside/run --format card
$TF observe-events /outside/run --after-sequence 0
$TF benchmark-finalize-hidden /outside/run/benchmark-record.json \
  --hidden-test /private/hidden.py --private-root /private/results
$TF archive-run /outside/run /outside/archives/run.zip
$TF verify-archive /outside/archives/run.zip
```

## Evaluation

```bash
$TF evaluation-import protocol.json control.json experiment.json \
  --rework rework.json \
  --failed-attempt failed-a.json \
  --failed-control-attempt failed-d.json \
  --pair-id task-001 --risk high --task-type bugfix --out pair.json
$TF evaluation-lab-run protocol.json pair-*.json \
  --lab-id snapshot-001 --out-dir /new/empty/lab
$TF evaluation-export-inspect protocol.json pair-*.json \
  --out-dir /new/empty/inspect-export
```

An `evaluation-lab-run` exit code of 1 is expected for `FAIL` or `INSUFFICIENT_SAMPLE`; inspect the machine-readable summary rather than treating it as a harness crash.

`evaluation-export-inspect` creates a hashed JSONL compatibility dataset. Its output is analysis-only; the Evaluation Lab summary remains authoritative. See `integrations/inspect_ai/` for the optional custom Scorer and offline re-scoring workflow.
