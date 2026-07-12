# Evaluation framework

Token Firewall uses a layered evaluation architecture. The protocol kernel remains independent of any single evaluation vendor or model Harness.

## Adopted design

| Layer | Implementation | Authority |
|---|---|---|
| Execution truth | Token Firewall Benchmark Runtime | Authoritative |
| Normalization and release statistics | Immutable Evaluation Pairs + Evaluation Lab | Authoritative |
| Exploratory analysis | Inspect AI compatibility export | Derived, analysis-only |
| External benchmark comparison | SWE-bench or repository-specific datasets | Optional additional evidence |
| Semantic judgment | Anonymous bounded Sol review | One quality gate, never the sole scorer |

The first layer freezes the Base Commit, Work Order, Git Patch, public validators, deferred hidden tests, model identity, Session ID, native usage, failures, retries, and rework. The second layer normalizes control and experiment Runs into paired observations, deduplicates Token usage by Session ID, computes cumulative Sol savings, runs paired Bootstrap non-inferiority analysis, checks risk/task-type coverage, and renders deterministic reports.

These two layers are the source of truth because they understand the external Codex, Claude Code, and MiniMax Code delivery protocol. Moving orchestration wholesale into another framework would require re-implementing those safety and provenance boundaries.

## Inspect AI compatibility layer

Inspect AI is integrated as an optional analysis layer, not as the Runtime kernel. `evaluation-export-inspect` converts schema-validated Evaluation Pairs into a hashed JSONL dataset. The adapter under [`integrations/inspect_ai/`](../integrations/inspect_ai/) replays that frozen evidence without another model call and provides:

- a custom multi-value Scorer for task success, quality difference, and per-pair Sol savings;
- success metrics grouped by risk and task type;
- standard errors clustered by Task ID;
- native structured `.eval` logs and Inspect View compatibility;
- offline re-scoring with `inspect score`.

Inspect's [custom scoring](https://inspect.aisi.org.uk/scoring.html), [grouped metrics and clustered standard errors](https://inspect.aisi.org.uk/metrics.html), [structured Eval Logs](https://inspect.aisi.org.uk/eval-logs.html), and [offline scoring workflow](https://inspect.aisi.org.uk/scoring-workflow.html) make it useful for analysis. Token Firewall still computes the authoritative cumulative savings and release verdict because an arithmetic mean of per-task savings is not equivalent to Session-deduplicated cumulative Token accounting.

Inspect also supports scorer access to its own Sandbox. Token Firewall does not currently replay completed coding Runs inside an Inspect Sandbox: external code already ran in an isolated Token Firewall Clone and passed Broker-controlled Git, scope, public-test, hidden-test, and archive gates. A future native Inspect executor may add another sandbox boundary without replacing these gates.

## Why not the alternatives alone?

| Option | Fit | Decision |
|---|---:|---|
| Benchmark Runtime + normalized statistics | 4.7/5 | Adopted as truth source |
| Runtime + Inspect AI export | 4.5/5 | Adopted as analysis enhancement |
| Full migration to Inspect AI | 3.8/5 | Not selected; would duplicate external Coding CLI integration and authority rules |
| SWE-bench only | 3.2/5 | Useful external comparison, but not representative of every Token Firewall task |
| LLM Judge only | 1.5/5 | Rejected; semantic review complements deterministic and hidden evidence |

## Quality and cost decision rule

The primary quality outcome is paired task success: public gate PASS, hidden suite PASS, anonymous review PASS, zero high/critical findings, zero scope violation, and complete required evidence. A transparent mechanical score is diagnostic; it does not override task success.

The protocol declares non-inferiority only when the lower bound of the paired 95% Bootstrap confidence interval is above the frozen quality margin and there are no excess critical regressions. The cost outcome is cumulative expensive Sol Tokens across every unique Session, including failed attempts and rework. A release PASS additionally requires complete usage, all frozen risk and task-type strata, and the minimum number of pairs.

## Implemented result

This is no longer a design-only proposal. The 12-pair Terra study was normalized by the Benchmark Runtime, decided by the Evaluation Lab, and exported through the Inspect compatibility layer:

- authoritative verdict: `PASS`;
- task success: 83.33% control vs 91.67% experiment;
- paired 95% Bootstrap interval: [0, 25] percentage points against a −5-point margin;
- cumulative expensive Sol Tokens: 3,599,108 vs 1,051,353, a 70.79% reduction;
- Inspect export: 12 hashed JSONL samples, custom scoring, grouped metrics, Task-ID clustering, structured logs, and offline re-scoring smoke-tested without another model call.

The frozen [Evaluation Lab](../evidence/labs/terra-route-n12-001/report/evaluation-report.md) remains the result of record. The [Inspect export](../evidence/inspect/terra-route-n12-001/) is derived evidence and carries `compatibility_role: analysis-only` in its manifest.
