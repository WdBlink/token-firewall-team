---
name: runbook
description: Execute, observe, recover, archive, and evaluate Token Firewall Runtime runs through stable CLI recipes.
---

# Runtime runbook

## Execution Procedure

```python
def execute_runtime(route, mission, work_orders):
    preflight(route)
    run_in_external_clone(mission, work_orders)
    observe_state_changes_without_streaming_transcripts()
    gate_delivery_and_packet()
    archive_and_verify_terminal_run()
```

Invoke commands through `python3 <skill>/scripts/token_firewall.py`.

## Single Work Order

```bash
TF="python3 /absolute/path/to/token-firewall-team/scripts/token_firewall.py"
$TF runtime-run mission.json work-order.json \
  --repo /path/to/clean/repo --base <full-commit> \
  --run-dir /outside/run --worktree-root /outside/worktrees \
  --worker-runtime codex --worker-model gpt-5.6-terra
```

Add `--review-runtime codex --reviewer-model gpt-5.6-sol` only when the final Sol decision is required.

## Optional Runtime matrix

The Skill core has no vendor-Harness installation dependency. Preflight only the route selected for the next dispatch:

- MiniMax Code present and safe: use `--worker-runtime minimax` for the native M3 transport.
- Claude Code present and mapped to M3: use `--worker-runtime claude`, then require an effective verified MiniMax-M3 identity in `stage-result.json`.
- MiniMax Code absent: keep the Skill, Codex routes, and Claude route operational.
- Claude Code absent: keep the Skill, Codex routes, and MiniMax route operational.

Choose the transport before dispatch. Do not fall back inside an active Run; preserve the failed attempt and start a new explicit dispatch so Harness identity, usage, and failure accounting remain auditable.

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

If this machine maps a Claude Code alias to M3, an isolated M3 Worker can use `--worker-runtime claude --worker-model <alias>`. Accept the route only when the Stage artifact has `model_effective_verified=true` and an effective MiniMax-M3 model. A frozen Worker can be replayed without another model turn:

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
```

An `evaluation-lab-run` exit code of 1 is expected for `FAIL` or `INSUFFICIENT_SAMPLE`; inspect the machine-readable summary rather than treating it as a harness crash.
