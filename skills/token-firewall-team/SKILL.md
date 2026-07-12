---
name: token-firewall-team
description: Reduce expensive Sol/GPT-5.6 token use in coding tasks by delegating implementation to MiniMax M3, GPT-5.6 Terra, or Claude Code while keeping Sol as a bounded final reviewer. Use for task decomposition, positive/negative/boundary acceptance contracts, isolated external-worker dispatch, low-noise progress observation, Git-truth delivery gates, blind review, failed-attempt accounting, and quality-versus-token evaluation.
---

# Token Firewall Team

Use the bundled Runtime to run a fail-closed Agent Team loop. Keep Sol on decomposition decisions, escalation, and final acceptance; do not use Sol as the default implementer.

## Execution Procedure

```python
def run_token_firewall(request, repository):
    inspect_real_repository(repository)
    mission, work_orders = decompose_with_acceptance_boundaries(request)
    protocol.enforce_protocol(mission, work_orders, stages=[])
    route = select_preflighted_route(mission, work_orders)
    result = runbook.execute_runtime(route, mission, work_orders)
    require_git_gate_and_fresh_verifier(result)
    review_packet = build_bounded_blind_review_packet(result)
    if review_packet.requires_sol_decision:
        request_sol_review(review_packet)
    evidence.calibrate_route(route, result.benchmark_records)
    return result
```

## Locate the Runtime

Set these paths conceptually before invoking commands:

```text
SKILL_ROOT = directory containing this SKILL.md
TF = python3 SKILL_ROOT/scripts/token_firewall.py
```

Run `python3 "$SKILL_ROOT/scripts/token_firewall.py" --help` to confirm the installation. The Runtime has no third-party Python dependency. Treat Codex CLI, Claude Code, and MiniMax Code as optional capabilities; never fail Skill installation merely because one external Harness is absent.

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

5. Preflight only the Runtime selected for this dispatch. A missing optional Runtime disables that route, not the Skill or other routes. Never silently weaken a failed isolation gate:

   ```bash
   python3 "$SKILL_ROOT/scripts/token_firewall.py" runtime-preflight --runtime codex
   python3 "$SKILL_ROOT/scripts/token_firewall.py" runtime-preflight --runtime claude
   python3 "$SKILL_ROOT/scripts/token_firewall.py" runtime-preflight --runtime minimax --agent coder
   ```

6. Put `run-dir`, `worktree-root`, private hidden tests, and archives outside the source repository. Require a clean source commit. The Runtime creates an independent clone and treats `git diff base..head` as authority.
7. Dispatch only the narrow Work Order. Do not send raw conversation history, the full repository, hidden tests, or unrelated files to a Worker.
8. Poll `observe-status` at low frequency and report only state changes, elapsed heartbeat, Session ID, usage, and delivery summary. Do not stream full terminals into the main task.
9. Require the deterministic Delivery Gate and a fresh independent verifier before Sol review. If `.git` is protected, accept `CHANGES_READY`; let the Broker validate and commit.
10. Build the blind Review Packet. Sol must see bounded context slices, the patch, acceptance evidence, unresolved risks, and no Worker/model/cost identity.
11. On `REWORK`, compile findings into the next Work Order revision. Do not ask the Worker to reinterpret prose. Preserve every failed attempt and deduplicate cost only by identical Session ID.
12. Run hidden evaluation only after all compared model stages end. Archive final and important failed Runs, verify each archive, then import immutable Benchmark Records into an Evaluation Lab.

## Route Work

Use this evidence-calibrated default:

- Choose Terra Worker + fresh Terra Verifier + Sol Reviewer for ordinary coding tasks with semantic boundaries. This is the current default route.
- Choose M3 for small mechanical changes only when the Work Order is exceptionally explicit. Keep two optional M3 transports: MiniMax Code/Mavis and Claude Code. Select one before dispatch and freeze the requested Runtime plus effective model identity in the Stage; never switch Harness silently during a Run. If MiniMax Code is unavailable or unsafe, a later dispatch may explicitly use the Claude Adapter's OS sandbox only when the Stage verifies `model_effective` as MiniMax-M3; never infer this from an alias. Use a fresh M3 Verifier. If Sol finds a semantic defect, compile a revision and use Terra as deputy before a new Sol review.
- Treat Claude Sonnet as experimental until its structured-output and Runtime reliability improve. Use a full model ID and verify `modelUsage`; do not trust a local `sonnet` alias.
- Choose Sol as implementer only for critical work, irreducible cross-cutting ambiguity, or when all approved cheaper routes fail their quality/isolation gates.

Do not route based only on file count. Authentication, data loss, external side effects, migrations, concurrency, and ambiguous semantic boundaries raise risk.

## Protect the Token Firewall

- Never make Sol read a full external transcript. Persist it in artifacts and pass only schema-validated delivery data.
- Never count a cheap model's claim as verified evidence. Rerun approved validators and inspect Git truth.
- Keep failed calls, retries, timeout Sessions, and rework in evaluation accounting.
- Distinguish gross accounted tokens from vendor-native tokens. Optimize the expensive Sol total; retain both measures for audit.
- Refuse a release claim when usage is incomplete or the frozen Evaluation Protocol lacks enough pairs. Keep conclusions route- and dataset-specific even after a non-inferiority gate passes; never transfer Terra evidence to M3, Claude, or a different task distribution without replication.

## Recover Safely

Use immutable snapshots when a CLI, daemon, or transport disappears. A recovered Worker patch must start from the frozen base. A recovered Verifier may remap a Commit ID only when the source Review Packet, source Patch, and current `base..HEAD` Patch have the same SHA-256.

Read `references/protocol.md` when defining authority or route boundaries. Read `references/runbook.md` for command recipes and `references/evidence.md` before changing the default router or budget policy.
