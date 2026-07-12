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

The 2026-07-11 Runtime Pilot contains two paired bugfix tasks (low and high risk), below the frozen 12-pair release threshold.

- Terra: 2/2 task success, 76.24% cumulative Sol savings. The model-stage sensitivity gate passes; the primary operational gate fails because one low Control Reviewer timed out before authoritative usage was emitted.
- M3: 2/2 final task success, 59.49% cumulative Sol savings. A low-risk semantic miss required a second Sol review; high-risk work passed once because its Acceptance Spec was substantially more explicit.
- Claude Sonnet: 0/2 accepted task outcomes. The adapter and actual model identity were verified, but semantic and structured-output/Runtime failures prevent default routing.

Do not convert these values into a universal quality claim. Use Terra as the provisional default, keep Sol as final reviewer, and continue accumulating frozen pairs across medium risk and feature/refactor/integration tasks.
