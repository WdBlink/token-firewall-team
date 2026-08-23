---
name: evidence
description: Calibrate Token Firewall routes from frozen benchmark records without overstating small-sample pilot results.
---

# Current calibration evidence

## Execution Procedure

```python
def calibrate_route(route, benchmark_records):
    require_content_hashes(benchmark_records)
    include_failures_retries_and_rework(benchmark_records)
    separate_native_from_accounted_tokens(benchmark_records)
    refuse_release_claim_below_frozen_sample_threshold(benchmark_records)
    return directional_route_evidence(route, benchmark_records)
```

The 2026-07-12 Terra study contains 12 paired tasks across low, medium, and high risk and feature, bugfix, refactor, and integration work. It meets the frozen sample/coverage threshold. It remains historical calibration evidence, but Terra is no longer a default production tier under the simplified Luna/M3/Sol operating policy.

- Terra expanded study: 11/12 experiment task success versus 10/12 Sol-direct, mean mechanical quality 96.67 versus 94.58, and 70.79% cumulative Sol savings (1,051,353 versus 3,599,108). The paired 95% Bootstrap interval is [0, 25] percentage points against a −5-point margin. Usage is complete, critical regressions are zero, and the frozen verdict is `PASS`.
- Evidence boundary: this supports no observed delivery-quality loss for this synthetic Python suite and Terra/Sol configuration, not universal model equivalence. One invalid dataset item was transparently excluded after both arms completed and replaced; valid semantic and review failures remain included.

- Historical external M3 route: 2/2 final task success, 59.49% cumulative Sol savings. A low-risk semantic miss required a second Sol review; high-risk work passed once because its Acceptance Spec was substantially more explicit. This is directional evidence for trying the native `minimax_m3` custom agent on bounded tasks, not a release-quality validation of the new native transport.
- Claude Sonnet: 0/2 accepted task outcomes. The adapter and actual model identity were verified, but semantic and structured-output/Runtime failures prevent default routing.

Treat native M3 as the economy implementation candidate for low-risk and selected medium-risk bounded work only when contracts, deterministic validators, and a fresh non-M3 Verifier are present. Use GPT-5.6 Luna as a policy-selected, read-only reconnaissance and first-pass verification tier; this is a role boundary, not a claim that Terra benchmark results transfer to Luna. Require a new Luna Session for independent M3 verification and escalate semantic or high-risk uncertainty to Sol. Measure realized savings after retries and review rather than inferring them from list price. Use Codex-native Agents by default and replicate the native M3 and Luna-verifier routes on real repositories before expanding either risk envelope. Terra remains available for frozen study reproduction or explicit selection, not automatic routing. Do not transfer Terra or historical M3 conclusions to Luna, native host-auto, native M3, Claude, or any other route without an adequately powered paired study.
