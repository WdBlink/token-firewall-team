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

The authority order is: immutable Mission/Work Order → deterministic Broker/Git gates → fresh Verifier → Sol Chief Reviewer. Worker output is always a proposal.

Roles:

- Mission Architect: defines outcomes, invariants, non-goals, approvals, and Sol budget.
- Decomposition Lead: emits narrow DAG Work Orders with positive, negative, and boundary cases.
- Worker: edits only allowed paths and returns `DELIVERED`, `CHANGES_READY`, `BLOCKED`, or `NEEDS_REPLAN`.
- Broker: owns isolated clone creation, scope checks, commits, test reruns, packetization, ledgers, and archives.
- Verifier/Deputy: fresh read-only Session that checks every Spec. It cannot PASS with a failed Spec, high/critical finding, coverage gap, or context request.
- Sol Chief Reviewer: anonymous final decision (`PASS`, `REWORK`, or `ESCALATE`).

Risk routing:

| Risk | Initial implementation | Independent verification | Final decision |
|---|---|---|---|
| low | M3 only for mechanical work; otherwise Terra | same cheap family, fresh Session | Sol bounded review |
| medium | Terra | fresh Terra | Sol review |
| high | M3/Terra only with explicit security boundaries | fresh verifier; deep evidence | Sol deep review |
| critical | Sol or explicitly approved specialist | independent deep verification | Sol deep review/user boundary |

Fail closed on dirty source state, path overlap, unknown model identity, incomplete usage, missing Session ID, malformed delivery, mismatched commit, hidden-test disclosure, unsafe Mavis isolation, or archive/hash mismatch.
