---
name: protocol
description: Define role authority, risk routing, isolation gates, and fail-closed conditions for the Token Firewall loop.
---

# Protocol and role boundary

## Execution Procedure

```python
def enforce_protocol(mission, work_orders, stages):
    validate_immutable_contracts(mission, work_orders)
    enforce_risk_route_and_isolation(work_orders, stages)
    require_broker_git_truth(stages)
    require_fresh_verifier_before_sol(stages)
    fail_closed_on_missing_identity_usage_or_evidence(stages)
```

The authority order is: immutable Mission/Work Order → deterministic Broker/Git gates → fresh Verifier → bounded Chief Reviewer. Worker output is always a proposal.

Roles:

- Mission Architect: defines outcomes, invariants, non-goals, approvals, and Sol budget.
- Decomposition Lead: emits narrow DAG Work Orders with positive, negative, and boundary cases.
- Worker: edits only allowed paths and returns `DELIVERED`, `CHANGES_READY`, `BLOCKED`, or `NEEDS_REPLAN`.
- Broker: owns isolated clone creation, scope checks, commits, test reruns, packetization, ledgers, and archives.
- Verifier/Deputy: fresh read-only Session that checks every Spec. It cannot PASS with a failed Spec, high/critical finding, coverage gap, or context request.
- Sol Chief Reviewer: anonymous final decision (`PASS`, `REWORK`, or `ESCALATE`).

Control-plane ownership is separate from model-provider selection and acceptance authority:

- Codex host: discovers custom agents, creates native subagents, routes messages and follow-ups, exposes status, waits for results, and interrupts or closes children. A custom agent may use a non-OpenAI Responses API provider without becoming an external CLI process.
- Token Firewall Broker: freezes the task, creates mutating-task worktrees, checks scope and Git truth, reruns validators, packetizes evidence, and records failed attempts.
- External Runtime Adapter: owns lifecycle only when the user explicitly requests the corresponding external harness.

A native custom agent may pin MiniMax-M3 through a user-level custom provider; another native profile may express a model preference; and an unpinned call may use Codex host auto-routing. Record which selection mode was used and exclude unavailable per-child usage from model-specific Token-savings claims.

For read-only native tasks, replace worktree isolation with a bounded artifact contract plus pre/post repository-state checks. Any change to HEAD, index, tracked files, or untracked-file set is a hard failure. For mutating tasks, worktree and Git Delivery gates remain mandatory regardless of lifecycle owner.

Risk routing:

| Risk | Initial implementation | Independent verification | Final decision |
|---|---|---|---|
| low | native `minimax_m3` for bounded/evaluable work; otherwise Terra-preferred | fresh non-M3 native verifier | bounded root review |
| medium | native `minimax_m3` only with tight scope and deterministic oracle; otherwise Terra or GPT-5.6 | fresh non-M3 native verifier for M3; otherwise fresh native verifier | bounded root review |
| high | native GPT-5.6 with explicit security boundaries | fresh native deep verifier | high-effort root review |
| critical | native GPT-5.6 or explicitly approved specialist | independent deep verification | root review/user boundary |

M3 is never the sole authority for authentication, authorization, data loss, destructive migration, security, concurrency, external side effects, or ambiguous semantic boundaries. Its output is a proposal until Git truth, deterministic validators, and a fresh non-M3 Verifier agree.

Fail closed on dirty source state, path overlap, missing Session ID, malformed delivery, mismatched commit, hidden-test disclosure, unsafe Mavis isolation, or archive/hash mismatch. An M3 route also fails closed on a missing custom agent, unexpected effective model identity, absent deterministic oracle, or missing independent non-M3 verification. Unknown model identity or incomplete usage fails any model-specific cost claim or benchmark; it remains explicitly recorded but does not invalidate a native delivery whose Git and acceptance evidence pass.
