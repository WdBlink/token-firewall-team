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

The 2026-07-12 Terra study contains 12 paired tasks across low, medium, and high risk and feature, bugfix, refactor, and integration work. It meets the frozen sample/coverage threshold.

- Terra expanded study: 11/12 experiment task success versus 10/12 Sol-direct, mean mechanical quality 96.67 versus 94.58, and 70.79% cumulative Sol savings (1,051,353 versus 3,599,108). The paired 95% Bootstrap interval is [0, 25] percentage points against a −5-point margin. Usage is complete, critical regressions are zero, and the frozen verdict is `PASS`.
- Evidence boundary: this supports no observed delivery-quality loss for this synthetic Python suite and Terra/Sol configuration, not universal model equivalence. One invalid dataset item was transparently excluded after both arms completed and replaced; valid semantic and review failures remain included.

- M3: 2/2 final task success, 59.49% cumulative Sol savings. A low-risk semantic miss required a second Sol review; high-risk work passed once because its Acceptance Spec was substantially more explicit.
- Claude Sonnet: 0/2 accepted task outcomes. The adapter and actual model identity were verified, but semantic and structured-output/Runtime failures prevent default routing.

Use Terra as the currently evidence-backed default Worker route, keep Sol as final reviewer, and continue route-specific replication on real repositories. Do not transfer the Terra conclusion to M3 or Claude without their own adequately powered paired studies.
