# TypeSafe route shadow 001

This experiment compares the current deterministic Token Firewall route with non-authoritative Jev advice. The 20 redacted tasks are synthetic representatives derived from recurring categories in the owner's recent Codex task list; they are not verbatim conversation exports.

Jev sees the redacted request and observed task facts, but not `current_task_shape`, `expert_reference_route`, or `expert_reason`. One API request is made per task. No Worker, Verifier, or implementation task is started.

```bash
TYPESAFE_API_KEY="$(security find-generic-password -a "$USER" -s typesafe.ai -w)" \
python3 skills/token-firewall-team/scripts/token_firewall.py \
  route-shadow-typesafe experiments/typesafe-route-shadow-001/tasks.json \
  --out-dir evidence/route-shadow/typesafe-jev-20-001
```

The expert reference is a policy-derived pre-label, not an independent human blind review. Human adjudication remains required for every current/Jev disagreement before changing production routing.
