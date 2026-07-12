"""Optional Inspect AI analysis task for frozen Token Firewall pair exports.

Token Firewall's Benchmark Runtime remains the source of truth. This module
replays already-frozen pair metadata into Inspect without calling a model.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import json_dataset
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import Metric, Score, Scorer, Target, accuracy, grouped, mean, metric, scorer, stderr
from inspect_ai.solver import Generate, TaskState, solver


@solver
def replay_frozen_pair():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        success = bool(state.metadata["experiment_task_success"])
        state.output = ModelOutput.from_content(
            model="token-firewall/frozen-evidence",
            content="pass" if success else "fail",
        )
        return state

    return solve


@metric
def accuracy_by_risk() -> Metric:
    return grouped(accuracy(), "risk", all_label="risk_all", name_template="risk_{group_name}")


@metric
def accuracy_by_task_type() -> Metric:
    return grouped(accuracy(), "task_type", all_label="type_all", name_template="type_{group_name}")


@scorer(
    metrics={
        "task_success": [
            accuracy(),
            accuracy_by_risk(),
            accuracy_by_task_type(),
            stderr(cluster="task_id"),
        ],
        "quality_difference": [mean(), stderr(cluster="task_id")],
        "sol_savings_percent": [mean(), stderr(cluster="task_id")],
    }
)
def frozen_pair_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        metadata = state.metadata
        if metadata.get("schema") != "token-firewall/inspect-sample@0.1":
            raise ValueError("unsupported Token Firewall Inspect sample schema")
        pair_hash = metadata.get("pair_content_sha256")
        if not isinstance(pair_hash, str) or len(pair_hash) != 64:
            raise ValueError("missing frozen pair hash")
        success = bool(metadata["experiment_task_success"])
        savings = metadata.get("sol_savings_percent")
        if not isinstance(savings, (int, float)):
            raise ValueError("per-pair Sol savings is unavailable")
        return Score(
            value={
                "task_success": int(success),
                "quality_difference": float(metadata["quality_difference"]),
                "sol_savings_percent": float(savings),
            },
            answer="pass" if success else "fail",
            explanation=(
                "Replayed from schema-validated Token Firewall pair evidence; "
                f"pair_sha256={pair_hash}."
            ),
            metadata={
                "truth_source": "token-firewall/evaluation-pair@0.1",
                "pair_content_sha256": pair_hash,
            },
        )

    return score


@task
def token_firewall_pairs(dataset: str) -> Task:
    """Analyze a dataset emitted by `evaluation-export-inspect`."""
    return Task(
        dataset=json_dataset(dataset),
        solver=replay_frozen_pair(),
        scorer=frozen_pair_scorer(),
        model="mockllm/model",
        name="token-firewall-pairs",
        version="0.1",
        metadata={
            "truth_source": "Token Firewall Benchmark Runtime",
            "compatibility_role": "analysis-only",
        },
    )
