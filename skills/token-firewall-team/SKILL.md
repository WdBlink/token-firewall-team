---
name: token-firewall-team
description: Run Codex Agent Teams through the native subagent lifecycle, including an optional MiniMax-M3 economy Worker for bounded work, while preserving contracts, Git truth, deterministic validation, independent verification, and blind final review. Use an external CLI Adapter only when the user explicitly requests execution through an external harness such as Claude Code, MiniMax Code, or OpenCode.
---

# Token Firewall Team

Use Codex-native subagents as the default Agent Team control plane. When the host exposes a configured `minimax_m3` custom agent, treat it as a native economy Worker rather than an external platform. Keep the bundled Runtime for explicitly requested external CLI routes, recovery, and benchmark tooling. Do not make the Runtime a second native scheduler.

## Execution Procedure

```python
def run_token_firewall(request, repository):
    inspect_real_repository(repository)
    mission, work_orders = decompose_with_acceptance_boundaries(request)
    protocol.enforce_protocol(mission, work_orders, stages=[])
    route = select_codex_native_role_and_model_preference(mission, work_orders)
    result = runbook.execute_native_agents(route, mission, work_orders)
    require_git_gate_and_fresh_verifier(result)
    review_packet = build_bounded_blind_review_packet(result)
    if review_packet.requires_sol_decision:
        request_sol_review(review_packet)
    evidence.calibrate_route(route, result.benchmark_records)
    return result
```

## Select the Control Plane

Use Codex's native Agent lifecycle for creation, messaging, status/wait, follow-up, interruption, and result collection. Let the host own Agent lifecycle; let Token Firewall own contracts, isolation, Git truth, validators, evidence, and acceptance authority.

Use the native route by default for ordinary research, implementation, and review inside a capable Codex host. Do not start a nested `codex exec` process for this route.

Route native roles according to the official [Codex subagents guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents): use the configured `minimax_m3` role for low-risk and selected medium-risk bounded work with an explicit oracle; use Terra for read-heavy reconnaissance and bounded routine work when M3 is unavailable or not yet evidence-qualified for the task class; use GPT-5.6 for ambiguous semantic implementation, architecture, security, and high-stakes review. An M3 delivery always requires a fresh non-M3 Verifier. When the current Agent API exposes no selector, leave the model unpinned and let Codex balance intelligence, speed, and price. Record the requested `agent_type`, whether a model was pinned or host-routed, and the effective identity when exposed; never invent per-child usage that the host did not expose.

Model vendor and execution platform are different routing dimensions. A request for MiniMax or M3 uses the native `minimax_m3` role when available. Select an external Runtime only when the user explicitly requests execution through an external harness such as Claude Code CLI, MiniMax Code/Mavis, or OpenCode. Token or cost pressure alone never authorizes an external Adapter, and a native failure never silently falls back to one.

Before the first M3 delivery in a fresh Codex build/session, run an exact-nonce no-tool probe with `fork_turns = "none"`. If the child returns `PAYLOAD_MISSING`, a generic acknowledgement, or anything other than the nonce while direct MiniMax Responses execution is healthy, treat native task delivery—not the provider—as failed. Follow the bounded one-shot bridge in `references/native-minimax-m3.md`; never fall back to an external harness. Clear the bridge after the result and retain the normal Git, validator, non-M3 Verifier, and root-review gates.

### Read-only native tasks

For research, reconnaissance, and analysis with no repository mutation:

1. Record the repository HEAD and clean status before dispatch when a Git repository is in scope.
2. Send a bounded artifact contract directly through the native Agent lifecycle; do not create a worktree only for role ceremony.
3. Use a fresh native Agent for independent evaluation.
4. Recheck HEAD, index, tracked changes, and untracked files. Fail closed if the task changed repository state.

### Mutating native tasks

For code or document changes, preserve the isolated Git delivery gates without introducing another scheduler:

1. The root/Broker records the base commit and creates the isolated worktree before native dispatch when isolation is warranted.
2. Send the bounded Work Order and absolute worktree path directly through Codex's native Agent lifecycle.
3. Use native messaging, follow-up, status/wait, and interruption controls to manage the child.
4. After delivery, reconstruct truth from `base..HEAD`, allowed paths, approved validators, and hashed artifacts; never trust the child report alone.
5. Dispatch a fresh native Verifier with read-only authority. Never reuse the Worker as Verifier or Reviewer.
6. Build the bounded blind Review Packet for final acceptance.

## Locate the Runtime

Set these paths conceptually before invoking commands:

```text
SKILL_ROOT = directory containing this SKILL.md
TF = python3 SKILL_ROOT/scripts/token_firewall.py
```

Run `python3 "$SKILL_ROOT/scripts/token_firewall.py" --help` only when using Runtime validation, recovery, benchmark tooling, or an explicitly requested third-party Adapter. The Runtime has no third-party Python dependency. A missing external Harness never blocks native Codex work.

## Execute the Loop

1. Inspect the real repository, current Git state, requested outcome, and relevant tests. Do not dispatch from memory or from an assumed layout.
2. Classify risk as low, medium, high, or critical. Use `references/protocol.md` for the route and escalation rules.
3. Write an immutable `mission-contract@0.1` and `work-order@0.2`. Every Acceptance Spec must include:
   - at least one positive case;
   - at least one negative case;
   - a semantic boundary with distinct inside/outside examples and an explicit rule;
   - an approved deterministic validator command.
4. Validate contracts before spending model tokens:

   ```bash
   python3 "$SKILL_ROOT/scripts/token_firewall.py" validate mission-contract.json
   python3 "$SKILL_ROOT/scripts/token_firewall.py" validate work-order.json
   python3 "$SKILL_ROOT/scripts/token_firewall.py" gate-dag work-orders.json
   ```

5. For the native default, resolve the role/model preference in the calling orchestrator (for example OPC's `agent-route`) and dispatch directly. A MiniMax model request resolves to `agent_type = "minimax_m3"` with `fork_turns = "none"`; it does not preflight an external Runtime. If the exact-nonce delivery regression fails, issue the short-lived local bridge defined in `references/native-minimax-m3.md` before spawning. Only when the user explicitly requested an external CLI harness, preflight that one Runtime and never silently switch Harnesses:

   ```bash
   python3 "$SKILL_ROOT/scripts/token_firewall.py" runtime-preflight --runtime claude
   python3 "$SKILL_ROOT/scripts/token_firewall.py" runtime-preflight --runtime minimax --agent coder
   ```

6. For native mutating work, require a clean source commit and let the root/Broker create any required isolated worktree outside the source repository before Agent dispatch. Treat `git diff base..head` as authority. For an explicit external Runtime run, also keep `run-dir`, private hidden tests, and archives outside the repository and let that Runtime create its independent clone. Apply the read-only native procedure when no mutation is authorized.
7. Dispatch only the narrow Work Order. Do not send raw conversation history, the full repository, hidden tests, or unrelated files to a Worker.
8. Use native Agent status/wait tools for the default route. Poll `observe-status` at low frequency only for explicit external Runtime runs. Report state changes, elapsed heartbeat, Agent/Session ID, usage availability, and delivery summary; do not stream full terminals into the main task.
9. Require the deterministic Delivery Gate and a fresh independent verifier before Sol review. If `.git` is protected, accept `CHANGES_READY`; let the Broker validate and commit.
10. Build the blind Review Packet. Sol must see bounded context slices, the patch, acceptance evidence, unresolved risks, and no Worker/model/cost identity.
11. On `REWORK`, compile findings into the next Work Order revision. Do not ask the Worker to reinterpret prose. Preserve every failed attempt and deduplicate cost only by identical Session ID.
12. Run hidden evaluation only after all compared model stages end. Archive final and important failed Runs, verify each archive, then import immutable Benchmark Records into an Evaluation Lab.

### Explicit Claude Adapter watchdog

This applies only when the user explicitly requested Claude Code. Claude runs through `stream-json`, so Runtime activity is based on actual stdout/stderr bytes rather than observer polling. `runtime-run` and `benchmark-run` default to `--startup-timeout 30 --stall-timeout 180`; set larger values for slow startup or validators that legitimately produce no output for several minutes, or `0` to disable one watchdog while retaining the overall `--timeout`.

An inactivity stall, overall timeout, or caller interruption terminates Claude's complete process group. A projected `STALLED` status is diagnostic only; recovery requires a new explicit bounded Runtime attempt, never synthetic heartbeat events or an automatic platform fallback.

## Route Work

Use this evidence-calibrated default:

- Choose the native `minimax_m3` custom agent as an economy Worker for low-risk and selected medium-risk repository reading, bulk drafting, routine implementation, and test repair when the Work Order has tight allowed paths, positive/negative/boundary cases, and a deterministic validator. Give it narrow context instead of an unbounded full-history fork.
- Choose a native Codex `explorer`/Terra-preferred Agent for repository scans, large-file reading, documentation work, structured test inventory, and UX observation.
- Choose a native Codex `worker`/Terra-preferred Agent for bounded routine implementation with an explicit oracle.
- Choose a native GPT-5.6-preferred Agent for ambiguous semantic implementation, integration, architecture, security, concurrency, destructive migration, or high-stakes verification. Use the host's recommended effort level and let it auto-route when profiles are unavailable.
- Use a fresh native Verifier and a bounded root Reviewer. An M3 Worker must be verified by a fresh non-M3 Agent; do not use M3 as its own Verifier or final Reviewer. Keep all mutating-task Git and validator gates.
- If the user explicitly asks to run through Claude Code, MiniMax Code/Mavis, or OpenCode, freeze that external Harness and model for the attempt. Naming MiniMax-M3 alone selects the native role, not an external Adapter.

Do not route based only on file count. Authentication, data loss, external side effects, migrations, concurrency, and ambiguous semantic boundaries raise risk.

## Protect the Token Firewall

- Never make Sol read a full external transcript. Persist it in artifacts and pass only schema-validated delivery data.
- Distinguish a pinned native profile from host auto-routing. Record the preference and selection mode without claiming unavailable per-child Token usage.
- Never count a cheap model's claim as verified evidence. Rerun approved validators and inspect Git truth.
- Treat an M3 delivery as a cost-optimized proposal: constrain its paths and semantics, prohibit opportunistic refactors, and escalate ambiguity rather than letting it improvise. Additional turns, retries, and verifier effort count against realized savings.
- Keep failed calls, retries, timeout Sessions, and rework in evaluation accounting.
- Distinguish gross accounted tokens from vendor-native tokens. Optimize the expensive Sol total; retain both measures for audit.
- Refuse a release claim when usage is incomplete or the frozen Evaluation Protocol lacks enough pairs. Keep conclusions route- and dataset-specific even after a non-inferiority gate passes; never transfer Terra evidence to M3, Claude, or a different task distribution without replication.

## Recover Safely

Use immutable snapshots when a CLI, daemon, or transport disappears. A recovered Worker patch must start from the frozen base. A recovered Verifier may remap a Commit ID only when the source Review Packet, source Patch, and current `base..HEAD` Patch have the same SHA-256.

Read `references/protocol.md` when defining authority or route boundaries. Read `references/native-minimax-m3.md` when configuring or selecting the native M3 route. Read `references/runbook.md` for command recipes and `references/evidence.md` before changing the default router or budget policy.
