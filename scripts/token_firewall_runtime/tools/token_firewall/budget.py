from __future__ import annotations

from typing import Any, Sequence

from .gates import GateResult
from .schema import SchemaRegistry


BUDGET_POLICY_SCHEMA_ID = "token-firewall/risk-token-budget-policy@0.1"


def risk_budget(policy: dict[str, Any], work_order: dict[str, Any], *, registry: SchemaRegistry | None = None) -> dict[str, Any]:
    registry = registry or SchemaRegistry()
    registry.validate(policy, BUDGET_POLICY_SCHEMA_ID)
    registry.validate(work_order)
    return dict(policy["tiers"][work_order["risk"]["level"]])


def gate_sol_budget(
    policy: dict[str, Any],
    work_order: dict[str, Any],
    stages: Sequence[dict[str, Any]],
    *,
    baseline_sol_tokens: int | None = None,
    rework_rounds: int = 0,
    registry: SchemaRegistry | None = None,
) -> GateResult:
    """Fail closed on incomplete, duplicated, or over-budget Sol accounting."""
    result = GateResult()
    tier = risk_budget(policy, work_order, registry=registry)
    if work_order["risk"]["required_review"] != tier["required_review"]:
        result.add(
            "BUDGET_REVIEW_ROUTE_MISMATCH",
            "Work Order review route differs from the frozen risk tier",
            expected=tier["required_review"],
            actual=work_order["risk"]["required_review"],
        )
    seen: dict[str, dict[str, Any]] = {}
    sol_stages: list[dict[str, Any]] = []
    for stage in stages:
        if not stage.get("counts_as_sol"):
            continue
        session_id = stage.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            result.add("BUDGET_SESSION_MISSING", "Sol stage has no auditable session_id")
            continue
        previous = seen.get(session_id)
        if previous is not None:
            if previous.get("usage") != stage.get("usage") or previous.get("model_requested") != stage.get("model_requested"):
                result.add("BUDGET_SESSION_CONFLICT", "Repeated Sol session has conflicting accounting", session_id=session_id)
            continue
        seen[session_id] = stage
        sol_stages.append(stage)
    for stage in sol_stages:
        usage = stage.get("usage")
        if not isinstance(usage, dict) or not usage.get("complete") or not isinstance(usage.get("total_tokens"), int):
            result.add("BUDGET_USAGE_INCOMPLETE", "Sol usage is incomplete", session_id=stage.get("session_id"))
    planning = sum(
        stage["usage"]["total_tokens"] for stage in sol_stages
        if isinstance(stage.get("usage"), dict) and isinstance(stage["usage"].get("total_tokens"), int)
        and stage.get("role") in {"mission-architect", "decomposition-lead"}
    )
    review = sum(
        stage["usage"]["total_tokens"] for stage in sol_stages
        if isinstance(stage.get("usage"), dict) and isinstance(stage["usage"].get("total_tokens"), int)
        and stage.get("role") in {"reviewer", "chief-reviewer"}
    )
    total = sum(
        stage["usage"]["total_tokens"] for stage in sol_stages
        if isinstance(stage.get("usage"), dict) and isinstance(stage["usage"].get("total_tokens"), int)
    )
    for name, actual, maximum in (
        ("planning", planning, tier["planning_sol_max"]),
        ("review", review, tier["review_sol_max"]),
        ("total", total, tier["total_sol_max"]),
    ):
        if actual > maximum:
            result.add("BUDGET_SOL_LIMIT_EXCEEDED", f"{name} Sol Token budget exceeded", bucket=name, actual=actual, maximum=maximum)
    if rework_rounds > tier["max_rework_rounds"]:
        result.add("BUDGET_REWORK_EXCEEDED", "rework round budget exceeded", actual=rework_rounds, maximum=tier["max_rework_rounds"])
    savings = None
    if baseline_sol_tokens is not None:
        if baseline_sol_tokens <= 0:
            result.add("BUDGET_BASELINE_INVALID", "baseline_sol_tokens must be positive")
        else:
            savings = round((baseline_sol_tokens - total) / baseline_sol_tokens * 100, 2)
            if savings < tier["minimum_sol_savings_percent"]:
                result.add(
                    "BUDGET_SAVINGS_MISSED", "risk-tier Sol savings target was missed",
                    actual=savings, minimum=tier["minimum_sol_savings_percent"],
                )
    result.evidence.update({"risk": work_order["risk"]["level"], "tier": tier, "planning_sol_tokens": planning, "review_sol_tokens": review, "total_sol_tokens": total, "sol_savings_percent": savings, "deduplicated_sol_sessions": len(sol_stages)})
    return result
