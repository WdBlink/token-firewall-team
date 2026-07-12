# Evaluation methodology

The included dataset is a directional Runtime Pilot, not a release-grade proof of statistical non-inferiority.

## Frozen design

- Two paired bug-fix tasks: one low-risk semantic-boundary task and one high-risk authentication task.
- One frozen base commit, Work Order, public validator, and deferred hidden suite per task.
- Sol-direct control compared with M3, Terra, and Claude Sonnet worker routes.
- Fresh verification and anonymous Sol review for every candidate that reached review.
- Failed calls, malformed output, timeouts, and rework kept in the ledger.
- Token use deduplicated only by identical Session ID.
- Gross accounted tokens retained for audit; expensive Sol tokens are the optimization target.

## Directional results

| Route | Accepted tasks | Control Sol tokens | Route Sol tokens | Sol savings | Frozen verdict |
|---|---:|---:|---:|---:|---|
| M3 loop | 2/2 | 598,925 | 242,649 | 59.49% | `INSUFFICIENT_SAMPLE` |
| Terra loop | 2/2 | 598,925 | 142,312 | 76.24% | `INSUFFICIENT_SAMPLE` |
| Claude Sonnet loop | 0/2 | 598,925 | 0 | Not interpretable | `INSUFFICIENT_SAMPLE` |

The Claude route's apparent 100% Token reduction is not a saving: no candidate reached accepted delivery. The M3 and Terra figures show that the architecture can reduce Sol consumption on these two tasks while retaining accepted outcomes, but `n=2` cannot establish a general quality claim.

## Reproduce the lab

The directories under [`evidence/labs/`](../evidence/labs/) contain the frozen protocol, normalized pair records, content hashes, JSON summaries, Markdown reports, and deterministic SVG charts for each route. Run a new immutable lab snapshot with:

```bash
python3 scripts/token_firewall.py evaluation-lab-run \
  protocol.json pair-*.json \
  --lab-id next-snapshot --out-dir /path/to/new/empty/output
```

The command exits non-zero for `FAIL` and `INSUFFICIENT_SAMPLE`; inspect the machine-readable summary instead of treating that result as a Runtime crash.

## Next evidence threshold

The frozen protocol requires at least 12 task pairs before a release decision and still needs medium-risk, feature, refactor, and integration coverage. A stronger Harness comparison should use paired tasks, repeated fresh Sessions, randomized execution order, hidden tests, and blinded review.
