# Evaluation methodology

Token Firewall evaluates quality and expensive-model consumption together. The 12-pair Terra study is the primary release-threshold experiment; the older M3 and Claude studies remain directional two-task pilots.

See [Evaluation framework](evaluation-framework.md) for why the Benchmark Runtime remains authoritative and Inspect AI is used as an optional analysis layer.

## Frozen design

- Twelve paired tasks covering feature, bug-fix, refactor, and integration work across low, medium, and high risk.
- The Sol-direct control and Terra-worker/Sol-reviewer experiment start from the same frozen base Commit, Work Order, public validator, and deferred hidden suite.
- A task succeeds only when the public gate, hidden suite, anonymous review, scope checks, and required evidence all pass, with no high/critical findings.
- Failed calls, timeouts, rework, and recovery attempts remain in cumulative Token accounting.
- Usage is deduplicated only when the Session ID is identical. Terra worker/verifier Tokens remain auditable but are not the optimization target.
- The primary quality test is a paired Bootstrap 95% interval over task success with a frozen −5 percentage-point non-inferiority margin.
- Release `PASS` additionally requires at least 12 pairs, complete usage, zero excess critical regressions, and all required risk/task-type strata.

## Primary result: Terra route, n=12

| Outcome | Sol-direct control | Terra worker + Sol reviewer | Difference |
|---|---:|---:|---:|
| Task success | 83.33% (10/12) | 91.67% (11/12) | +8.33 pp |
| Mean mechanical quality score | 94.58 | 96.67 | +2.09 |
| Cumulative expensive Sol Tokens | 3,599,108 | 1,051,353 | **−70.79%** |
| Critical regressions | 0 | 0 | 0 |

The paired 95% Bootstrap interval for the success-rate difference is **[0, 25] percentage points**. Its lower bound is above the frozen −5-point margin. The sample, coverage, usage, and critical-regression gates also pass, so the frozen verdict is `PASS`.

This supports the bounded statement that **the evaluated collaboration route reduced expensive-model Tokens by 70.79% without an observed delivery-quality loss in this study**. It is not a proof of universal equivalence across repositories, model releases, languages, or task distributions.

Risk strata were:

| Risk | Pairs | Control success | Experiment success |
|---|---:|---:|---:|
| Low | 4 | 100% | 100% |
| Medium | 6 | 66.67% | 83.33% |
| High | 2 | 100% | 100% |

## Dataset-defect disclosure

Task 08 was completed by both arms before exclusion. Its hidden suite required `max_delay=0` to raise even though that behavior was absent from—and inconsistent with—the frozen Acceptance Spec. It was therefore classified as an invalid dataset item, retained in the private run archive, disclosed in [`run-schedule.json`](../experiments/terra-route-n12-001/run-schedule.json), and replaced by a newly frozen Task 13.

The replacement was selected after the defect classification, which creates a post-hoc selection risk. We disclose that limitation rather than treating Task 13 as preregistered. Valid failures were not removed: the Task 11 Terra semantic miss and the corresponding control review failure remain in the 12-pair analysis. A Task 09 verifier-Harness failure and recovered attempt also remain in cost accounting.

## Directional route pilots

| Route | Paired tasks | Accepted tasks | Control Sol Tokens | Route Sol Tokens | Sol savings | Verdict |
|---|---:|---:|---:|---:|---:|---|
| M3 loop | 2 | 2/2 | 598,925 | 242,649 | 59.49% | `INSUFFICIENT_SAMPLE` |
| Claude Sonnet loop | 2 | 0/2 | 598,925 | 0 | Not interpretable | `INSUFFICIENT_SAMPLE` |

Claude's apparent 100% Token reduction is not a saving: no candidate reached accepted delivery. The M3 result is encouraging but cannot inherit the 12-pair Terra conclusion because the worker model and Harness differ.

## Reproduce the lab

The frozen lab under [`evidence/labs/terra-route-n12-001/`](../evidence/labs/terra-route-n12-001/) contains the protocol, normalized pair records, content hashes, JSON summary, Markdown report, and deterministic SVG charts. The fixtures, contracts, hidden suites, and randomized schedule are under [`experiments/terra-route-n12-001/`](../experiments/terra-route-n12-001/).

Run a new immutable snapshot from normalized pair records with:

```bash
TF="python3 skills/token-firewall-team/scripts/token_firewall.py"

$TF evaluation-lab-run protocol.json pair-*.json \
  --lab-id next-snapshot --out-dir /path/to/new/empty/output
```

Export the same authoritative pairs for optional Inspect AI analysis with:

```bash
$TF evaluation-export-inspect protocol.json pair-*.json \
  --out-dir /path/to/inspect-export
```

The lab command exits non-zero for `FAIL` and `INSUFFICIENT_SAMPLE`; inspect the machine-readable summary rather than treating that result as a Runtime crash.

## Remaining evidence needs

- repeat the 12+ task design for M3 through both Claude Code and MiniMax Code;
- add real-repository tasks and a recognized external benchmark such as a SWE-bench subset;
- repeat tasks across fresh Sessions so Task-ID clustered standard errors become more informative;
- report model/version drift instead of pooling results across materially different releases.
