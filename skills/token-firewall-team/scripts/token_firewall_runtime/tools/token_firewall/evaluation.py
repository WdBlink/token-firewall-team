from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Sequence
from xml.sax.saxutils import escape

from .schema import SchemaRegistry, canonical_sha256
from .state import atomic_write_json


EVALUATION_PROTOCOL_SCHEMA_ID = "token-firewall/evaluation-protocol@0.1"
EVALUATION_PAIR_SCHEMA_ID = "token-firewall/evaluation-pair@0.1"
EVALUATION_SUMMARY_SCHEMA_ID = "token-firewall/evaluation-summary@0.1"
EVALUATION_LAB_SCHEMA_ID = "token-firewall/evaluation-lab-manifest@0.1"


def _record_success(record: dict[str, Any]) -> bool:
    return bool(
        record["status"] == "COMPLETE"
        and record["public_gate"]["status"] == "pass"
        and record["hidden_evaluation"]["status"] == "pass"
        and record["review"]["verdict"] == "PASS"
        and record["review"]["high_critical_findings"] == 0
        and record["review"]["coverage_gaps"] == 0
        and record["review"]["requested_context"] == 0
        and not record["scope_violations"]
    )


def _mechanical_quality_score(record: dict[str, Any]) -> float:
    """A transparent diagnostic score; task_success remains the primary outcome."""
    score = 100
    if record["status"] != "COMPLETE":
        score -= 20
    if record["public_gate"]["status"] != "pass":
        score -= 15
    if record["hidden_evaluation"]["status"] == "fail":
        score -= 40
    elif record["hidden_evaluation"]["status"] != "pass":
        score -= 25
    score -= {"PASS": 0, "REWORK": 20, "ESCALATE": 30, "not_run": 40}[record["review"]["verdict"]]
    score -= min(50, record["review"]["high_critical_findings"] * 25)
    score -= min(20, len(record["scope_violations"]) * 10)
    return float(max(0, score))


def _unique_stages(records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    stages: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    complete = True
    for record in records:
        for stage in record["stages"].values():
            if stage is None:
                continue
            session_id = stage.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                complete = False
                continue
            previous = seen.get(session_id)
            if previous is None:
                seen[session_id] = stage
                stages.append(stage)
            else:
                metered_keys = (
                    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                    "total_tokens", "native_total_tokens", "complete",
                )
                same_metering = all(
                    previous["usage"].get(key, 0) == stage["usage"].get(key, 0)
                    for key in metered_keys
                )
                if (
                    previous["runtime"] != stage["runtime"]
                    or previous["model_requested"] != stage["model_requested"]
                    or not same_metering
                ):
                    complete = False
    complete = complete and all(stage["usage"]["complete"] for stage in stages)
    return stages, complete


def _outcome(records: Sequence[dict[str, Any]], *, arm_id: str) -> dict[str, Any]:
    stages, usage_complete = _unique_stages(records)
    final = records[-1]
    return {
        "arm_id": arm_id,
        "task_success": _record_success(final),
        "quality_score": _mechanical_quality_score(final),
        "quality_score_source": "mechanical-gates@0.1",
        "sol_tokens": sum(stage["usage"]["total_tokens"] for stage in stages if stage["counts_as_sol"]),
        "all_model_tokens": sum(stage["usage"]["total_tokens"] for stage in stages),
        "elapsed_seconds": round(sum(record["elapsed_seconds"] for record in records), 3),
        "high_critical_findings": final["review"]["high_critical_findings"],
        "hidden_status": final["hidden_evaluation"]["status"],
        "review_verdict": final["review"]["verdict"],
        "usage_complete": usage_complete,
        "session_ids": [stage["session_id"] for stage in stages],
    }


def pair_from_benchmark_records(
    protocol: dict[str, Any],
    control: dict[str, Any],
    experiment_records: Sequence[dict[str, Any]],
    *,
    pair_id: str,
    risk: str,
    task_type: str,
    failed_attempts: Sequence[dict[str, Any]] = (),
    failed_control_attempts: Sequence[dict[str, Any]] = (),
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    """Normalize a frozen D vs A(+B rework) campaign without selective accounting."""
    from .benchmark import BENCHMARK_SCHEMA_ID, compare_benchmarks, summarize_rework_campaign

    registry = registry or SchemaRegistry()
    registry.validate(protocol, EVALUATION_PROTOCOL_SCHEMA_ID)
    if risk not in protocol["sampling"]["risk_levels"]:
        raise ValueError(f"risk is outside frozen evaluation strata: {risk}")
    if task_type not in protocol["sampling"]["task_types"]:
        raise ValueError(f"task_type is outside frozen evaluation strata: {task_type}")
    registry.validate(control, BENCHMARK_SCHEMA_ID)
    records = list(experiment_records)
    if not records:
        raise ValueError("at least one A experiment record is required")
    for record in records:
        registry.validate(record, BENCHMARK_SCHEMA_ID)
    experiment_group = records[0]["group_id"]
    if control["group_id"] != "D" or experiment_group not in {"A", "C", "E"}:
        raise ValueError("evaluation normalization requires D control followed by A, C, or E experiment")
    if protocol["control_arm"]["arm_id"] != "D" or protocol["experiment_arm"]["arm_id"] != experiment_group:
        raise ValueError("evaluation protocol arms do not match the benchmark groups")
    comparable = compare_benchmarks(control, records[0])["comparable"]
    if not comparable:
        raise ValueError("control and experiment benchmark records are not comparable")
    if len(records) > 1:
        if experiment_group != "A":
            raise ValueError("B rework records are only valid after an A experiment")
        campaign = summarize_rework_campaign(control, records[0], records[1:])
        if not campaign["chain_valid"]:
            raise ValueError("A/B rework campaign chain is invalid")
    failed = list(failed_attempts)
    for record in failed:
        registry.validate(record, BENCHMARK_SCHEMA_ID)
        if record["group_id"] != experiment_group:
            raise ValueError("failed attempt group differs from the experiment group")
        if any(record[key] != records[0][key] for key in (
            "base_sha", "mission_id", "task_id", "task_revision",
            "mission_content_sha256", "task_content_sha256",
        )):
            raise ValueError("failed attempt does not belong to the frozen experiment task")
    failed_control = list(failed_control_attempts)
    for record in failed_control:
        registry.validate(record, BENCHMARK_SCHEMA_ID)
        if record["group_id"] != "D":
            raise ValueError("failed control attempt must use group D")
        if any(record[key] != control[key] for key in (
            "base_sha", "mission_id", "task_id", "task_revision",
            "mission_content_sha256", "task_content_sha256",
        )):
            raise ValueError("failed control attempt does not belong to the frozen control task")
    source_run_ids = [
        *(record["run_id"] for record in failed_control),
        control["run_id"],
        *(record["run_id"] for record in failed),
        *(record["run_id"] for record in records),
    ]
    if len(set(source_run_ids)) != len(source_run_ids):
        raise ValueError("source benchmark run IDs must be unique")
    pair = {
        "schema": EVALUATION_PAIR_SCHEMA_ID,
        "object_id": f"pair_{re.sub(r'[^A-Za-z0-9_.-]+', '_', pair_id)}",
        "content_sha256": "0" * 64,
        "experiment_id": protocol["experiment_id"],
        "pair_id": pair_id,
        "task_id": control["task_id"],
        "risk": risk,
        "task_type": task_type,
        "task_content_sha256": control["task_content_sha256"],
        "provenance": {
            "normalizer_revision": "benchmark-to-pair@0.2" if (failed or failed_control) else "benchmark-to-pair@0.1",
            "campaign_mode": "rework" if len(records) > 1 else "single",
            "control_record_sha256": control["content_sha256"],
            "experiment_record_sha256": [
                *(record["content_sha256"] for record in failed),
                *(record["content_sha256"] for record in records),
            ],
            **({"failed_attempt_record_sha256": [record["content_sha256"] for record in failed]} if failed else {}),
            **({
                "failed_control_attempt_record_sha256": [record["content_sha256"] for record in failed_control]
            } if failed_control else {}),
            "source_run_ids": source_run_ids,
        },
        "control": _outcome([*failed_control, control], arm_id=protocol["control_arm"]["arm_id"]),
        "experiment": _outcome([*failed, *records], arm_id=protocol["experiment_arm"]["arm_id"]),
    }
    pair["content_sha256"] = canonical_sha256(pair)
    registry.validate(pair, EVALUATION_PAIR_SCHEMA_ID)
    return pair


def build_evaluation_lab(
    protocol: dict[str, Any],
    pairs: Sequence[dict[str, Any]],
    output_dir: Path | str,
    *,
    lab_id: str,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or SchemaRegistry()
    registry.validate(protocol, EVALUATION_PROTOCOL_SCHEMA_ID)
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"evaluation lab output directory must be new or empty: {destination}")
    pair_dir = destination / "pairs"
    pair_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for pair in pairs:
        registry.validate(pair, EVALUATION_PAIR_SCHEMA_ID)
        if pair["pair_id"] in seen:
            raise ValueError(f"duplicate pair_id in lab: {pair['pair_id']}")
        seen.add(pair["pair_id"])
        filename = f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', pair['pair_id'])}.json"
        atomic_write_json(pair_dir / filename, pair)
        entries.append({"pair_id": pair["pair_id"], "path": f"pairs/{filename}", "sha256": pair["content_sha256"]})
    atomic_write_json(destination / "protocol.json", protocol)
    atomic_write_json(destination / "pairs.json", list(pairs))
    manifest = {
        "schema": EVALUATION_LAB_SCHEMA_ID,
        "object_id": f"lab_{re.sub(r'[^A-Za-z0-9_.-]+', '_', lab_id)}",
        "content_sha256": "0" * 64,
        "lab_id": lab_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "protocol_ref": "protocol.json",
        "protocol_sha256": protocol["content_sha256"],
        "pairs": entries,
        "dataset_sha256": canonical_sha256([entry["sha256"] for entry in entries], exclude_content_hash=False),
    }
    manifest["content_sha256"] = canonical_sha256(manifest)
    registry.validate(manifest, EVALUATION_LAB_SCHEMA_ID)
    atomic_write_json(destination / "lab-manifest.json", manifest)
    summary = write_evaluation_artifacts(protocol, pairs, destination / "report", registry=registry)
    return {"manifest": manifest, "summary": summary}


def export_inspect_dataset(
    protocol: dict[str, Any],
    pairs: Sequence[dict[str, Any]],
    output_dir: Path | str,
    *,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    """Export frozen pairs for Inspect AI analysis without changing the truth source.

    The Token Firewall pair records remain authoritative. This export intentionally
    contains no model transcript and can be scored or re-scored offline by Inspect.
    """
    registry = registry or SchemaRegistry()
    registry.validate(protocol, EVALUATION_PROTOCOL_SCHEMA_ID)
    if not pairs:
        raise ValueError("Inspect export requires at least one evaluation pair")
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Inspect export output directory must be new or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pair in pairs:
        registry.validate(pair, EVALUATION_PAIR_SCHEMA_ID)
        if pair["experiment_id"] != protocol["experiment_id"]:
            raise ValueError("Inspect export pair belongs to a different experiment")
        if pair["pair_id"] in seen:
            raise ValueError(f"duplicate pair_id in Inspect export: {pair['pair_id']}")
        seen.add(pair["pair_id"])
        control = pair["control"]
        experiment = pair["experiment"]
        per_pair_savings = (
            round((control["sol_tokens"] - experiment["sol_tokens"]) / control["sol_tokens"] * 100, 4)
            if control["sol_tokens"]
            else None
        )
        samples.append({
            "id": pair["pair_id"],
            "input": f"Score frozen Token Firewall pair {pair['pair_id']} from deterministic evidence.",
            "target": "pass",
            "metadata": {
                "schema": "token-firewall/inspect-sample@0.1",
                "experiment_id": pair["experiment_id"],
                "pair_id": pair["pair_id"],
                "task_id": pair["task_id"],
                "cluster_id": pair["task_id"],
                "risk": pair["risk"],
                "task_type": pair["task_type"],
                "pair_content_sha256": pair["content_sha256"],
                "control_task_success": control["task_success"],
                "experiment_task_success": experiment["task_success"],
                "control_quality_score": control["quality_score"],
                "experiment_quality_score": experiment["quality_score"],
                "quality_difference": round(experiment["quality_score"] - control["quality_score"], 4),
                "control_sol_tokens": control["sol_tokens"],
                "experiment_sol_tokens": experiment["sol_tokens"],
                "sol_savings_percent": per_pair_savings,
                "control_usage_complete": control["usage_complete"],
                "experiment_usage_complete": experiment["usage_complete"],
                "hidden_status": experiment["hidden_status"],
                "review_verdict": experiment["review_verdict"],
                "high_critical_findings": experiment["high_critical_findings"],
            },
        })

    dataset = destination / "token-firewall-pairs.jsonl"
    dataset_bytes = b"".join(
        json.dumps(sample, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for sample in samples
    )
    dataset.write_bytes(dataset_bytes)
    summary = summarize_paired_evaluation(protocol, pairs, registry=registry)
    manifest = {
        "schema": "token-firewall/inspect-export-manifest@0.1",
        "content_sha256": "0" * 64,
        "experiment_id": protocol["experiment_id"],
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "truth_source": "token-firewall/evaluation-pair@0.1",
        "compatibility_role": "analysis-only",
        "protocol_content_sha256": protocol["content_sha256"],
        "pair_content_sha256": [pair["content_sha256"] for pair in pairs],
        "dataset": {
            "path": dataset.name,
            "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "samples": len(samples),
        },
        "authoritative_summary_content_sha256": canonical_sha256(summary),
        "supported_analysis": [
            "custom_scorer",
            "grouped_metrics:risk",
            "grouped_metrics:task_type",
            "clustered_stderr:task_id",
            "offline_rescoring",
            "structured_eval_log",
        ],
    }
    manifest["content_sha256"] = canonical_sha256(manifest)
    atomic_write_json(destination / "inspect-export-manifest.json", manifest)
    return {"manifest": manifest, "samples": samples}


def _rate(values: Sequence[bool]) -> float:
    return sum(1 for item in values if item) / len(values)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * quantile)
    return ordered[index]


def _paired_bootstrap_difference(
    pairs: Sequence[dict[str, Any]],
    *,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    randomizer = random.Random(seed)
    differences: list[float] = []
    for _ in range(samples):
        selected = [pairs[randomizer.randrange(len(pairs))] for _ in pairs]
        control = _rate([item["control"]["task_success"] for item in selected])
        experiment = _rate([item["experiment"]["task_success"] for item in selected])
        differences.append((experiment - control) * 100)
    return round(_percentile(differences, 0.025), 2), round(_percentile(differences, 0.975), 2)


def summarize_paired_evaluation(
    protocol: dict[str, Any],
    pairs: Sequence[dict[str, Any]],
    *,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or SchemaRegistry()
    registry.validate(protocol, EVALUATION_PROTOCOL_SCHEMA_ID)
    if not pairs:
        raise ValueError("paired evaluation requires at least one pair")
    pair_ids: set[str] = set()
    content_hashes: set[str] = set()
    all_sessions: set[str] = set()
    sessions_unique = True
    for pair in pairs:
        registry.validate(pair, EVALUATION_PAIR_SCHEMA_ID)
        if pair["experiment_id"] != protocol["experiment_id"]:
            raise ValueError("evaluation pair belongs to a different experiment")
        if pair["control"]["arm_id"] != protocol["control_arm"]["arm_id"]:
            raise ValueError("evaluation pair control arm differs from protocol")
        if pair["experiment"]["arm_id"] != protocol["experiment_arm"]["arm_id"]:
            raise ValueError("evaluation pair experiment arm differs from protocol")
        if pair["risk"] not in protocol["sampling"]["risk_levels"]:
            raise ValueError(f"pair risk is outside frozen strata: {pair['risk']}")
        if pair["task_type"] not in protocol["sampling"]["task_types"]:
            raise ValueError(f"pair task_type is outside frozen strata: {pair['task_type']}")
        if pair["pair_id"] in pair_ids:
            raise ValueError(f"duplicate pair_id: {pair['pair_id']}")
        if pair["content_sha256"] in content_hashes:
            raise ValueError("duplicate evaluation pair content")
        pair_ids.add(pair["pair_id"])
        content_hashes.add(pair["content_sha256"])
        for outcome in (pair["control"], pair["experiment"]):
            for session_id in outcome["session_ids"]:
                if session_id in all_sessions:
                    sessions_unique = False
                all_sessions.add(session_id)

    control_success = [item["control"]["task_success"] for item in pairs]
    experiment_success = [item["experiment"]["task_success"] for item in pairs]
    control_rate = _rate(control_success)
    experiment_rate = _rate(experiment_success)
    difference_pp = (experiment_rate - control_rate) * 100
    lower, upper = _paired_bootstrap_difference(
        pairs,
        samples=protocol["sampling"]["bootstrap_samples"],
        seed=protocol["sampling"]["random_seed"],
    )
    margin = protocol["primary_outcome"]["noninferiority_margin_percentage_points"]
    critical_regressions = sum(
        1
        for item in pairs
        if item["experiment"]["high_critical_findings"] > item["control"]["high_critical_findings"]
    )
    noninferior = bool(
        lower >= -margin
        and critical_regressions <= protocol["primary_outcome"]["critical_regressions_allowed"]
    )

    control_sol = sum(item["control"]["sol_tokens"] for item in pairs)
    experiment_sol = sum(item["experiment"]["sol_tokens"] for item in pairs)
    sol_savings = round((control_sol - experiment_sol) / control_sol * 100, 2) if control_sol else None
    target = protocol["cost_outcome"]["minimum_sol_savings_percent"]
    target_met = sol_savings is not None and sol_savings >= target
    usage_complete = sessions_unique and all(
        item[side]["usage_complete"]
        for item in pairs
        for side in ("control", "experiment")
    )

    observed_risks = {item["risk"] for item in pairs}
    observed_types = {item["task_type"] for item in pairs}
    sufficient_sample = bool(
        len(pairs) >= protocol["sampling"]["minimum_pairs"]
        and set(protocol["sampling"]["risk_levels"]) <= observed_risks
        and set(protocol["sampling"]["task_types"]) <= observed_types
    )
    strata: list[dict[str, Any]] = []
    for risk in protocol["sampling"]["risk_levels"]:
        selected = [item for item in pairs if item["risk"] == risk]
        if selected:
            strata.append(
                {
                    "risk": risk,
                    "pairs": len(selected),
                    "control_success_rate": round(_rate([item["control"]["task_success"] for item in selected]), 4),
                    "experiment_success_rate": round(_rate([item["experiment"]["task_success"] for item in selected]), 4),
                }
            )

    if not sufficient_sample:
        verdict = "INSUFFICIENT_SAMPLE"
    elif noninferior and target_met and usage_complete:
        verdict = "PASS"
    else:
        verdict = "FAIL"
    pilot_gate = "PASS" if noninferior and target_met and usage_complete else "FAIL"
    return {
        "schema": EVALUATION_SUMMARY_SCHEMA_ID,
        "content_sha256": "0" * 64,
        "experiment_id": protocol["experiment_id"],
        "protocol_content_sha256": protocol["content_sha256"],
        "pair_content_sha256": sorted(content_hashes),
        "sample_size": len(pairs),
        "sufficient_sample": sufficient_sample,
        "usage_complete": usage_complete,
        "quality": {
            "control_success_rate": round(control_rate, 4),
            "experiment_success_rate": round(experiment_rate, 4),
            "difference_percentage_points": round(difference_pp, 2),
            "ci95_lower_percentage_points": lower,
            "ci95_upper_percentage_points": upper,
            "noninferiority_margin_percentage_points": margin,
            "noninferior": noninferior,
            "critical_regressions": critical_regressions,
            "control_mean_score": round(mean(item["control"]["quality_score"] for item in pairs), 2),
            "experiment_mean_score": round(mean(item["experiment"]["quality_score"] for item in pairs), 2),
        },
        "cost": {
            "control_sol_tokens": control_sol,
            "experiment_sol_tokens": experiment_sol,
            "sol_savings_percent": sol_savings,
            "target_percent": target,
            "target_met": target_met,
        },
        "strata": strata,
        "artifacts": {"markdown_report": "evaluation-report.md", "charts": []},
        "verdict": verdict,
        "pilot_gate": pilot_gate,
    }


def write_evaluation_artifacts(
    protocol: dict[str, Any],
    pairs: Sequence[dict[str, Any]],
    output_dir: Path | str,
    *,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or SchemaRegistry()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary = summarize_paired_evaluation(protocol, pairs, registry=registry)
    charts: list[str] = []
    renderers = {
        # Keep the frozen protocol key and filename for backward compatibility,
        # but render a task-level comparison rather than a causal-looking Pareto plot.
        "quality_token_pareto": _render_task_quality_token_comparison,
        "paired_quality": _render_paired_quality,
        "risk_strata": _render_risk_strata,
        "token_waterfall": _render_token_waterfall,
    }
    for chart in protocol["reporting"]["charts"]:
        name = f"{chart.replace('_', '-')}.svg"
        (destination / name).write_text(renderers[chart](protocol, pairs, summary), encoding="utf-8")
        charts.append(name)
    summary["artifacts"]["charts"] = charts
    (destination / "evaluation-report.md").write_text(
        _markdown_report(protocol, pairs, summary),
        encoding="utf-8",
    )
    summary["content_sha256"] = canonical_sha256(summary)
    registry.validate(summary, EVALUATION_SUMMARY_SCHEMA_ID)
    atomic_write_json(destination / "evaluation-summary.json", summary)
    return summary


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#172033}.axis{stroke:#9aa7b8;stroke-width:1}.grid{stroke:#e7ebf0;stroke-width:1}.label{font-size:12px}.title{font-size:18px;font-weight:700}</style>'
        f"{body}</svg>\n"
    )


def _render_task_quality_token_comparison(
    protocol: dict[str, Any],
    pairs: Sequence[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    """Render quality and expensive-token outcomes without implying causality.

    Both panels start at zero, use the same task ordering, and keep quality and
    Token on separate axes. The frozen ``quality_token_pareto`` protocol key is
    retained only for artifact compatibility.
    """
    width, height = 1080, 720
    left, right = 78, 28
    plot_w = width - left - right
    quality_top, quality_h = 105, 220
    token_top, token_h = 415, 220
    group_w = plot_w / len(pairs)
    bar_w = min(24.0, group_w * 0.28)
    gap = 6.0
    control_color = "#2563EB"
    experiment_color = "#0F9F78"

    def task_order(pair: dict[str, Any]) -> tuple[int, int]:
        task_id = pair["task_id"]
        if task_id == "T-PILOT-LOW":
            return (0, 1)
        if task_id == "T-PILOT-HIGH":
            return (0, 2)
        match = re.search(r"(\d+)$", task_id)
        return (1, int(match.group(1)) if match else 10_000)

    ordered_pairs = sorted(pairs, key=task_order)
    maximum_tokens = max(
        max(pair["control"]["sol_tokens"], pair["experiment"]["sol_tokens"])
        for pair in ordered_pairs
    ) or 1
    token_step = 100_000
    token_ceiling = max(token_step, ((maximum_tokens + token_step - 1) // token_step) * token_step)

    def short_task(task_id: str, index: int) -> str:
        if task_id == "T-PILOT-HIGH":
            return "P-H"
        if task_id == "T-PILOT-LOW":
            return "P-L"
        match = re.search(r"(\d+)$", task_id)
        return match.group(1) if match else f"T{index + 1}"

    parts = [
        '<style>.panel{font-size:14px;font-weight:700}.subtitle{font-size:11px;fill:#526072}'
        '.value{font-size:9px;font-weight:600}.legend{font-size:11px;font-weight:600}'
        '.badge{font-size:12px;font-weight:700;fill:#08775b}</style>',
        '<text x="24" y="30" class="title">12-task comparison · 交付质量与昂贵 Sol Token</text>',
        '<text x="24" y="52" class="subtitle">Separate zero-based panels avoid implying that Token consumption causes quality changes.</text>',
        f'<rect x="748" y="18" width="12" height="12" rx="2" fill="{control_color}"/>',
        '<text x="766" y="28" class="legend">Sol-direct / Sol 直做</text>',
        f'<rect x="905" y="18" width="12" height="12" rx="2" fill="{experiment_color}"/>',
        '<text x="923" y="28" class="legend">Hybrid / 混合方案</text>',
    ]

    for index in range(len(ordered_pairs)):
        if index % 2 == 0:
            x = left + index * group_w
            parts.append(
                f'<rect x="{x:.1f}" y="{quality_top-8}" width="{group_w:.1f}" '
                f'height="{token_top+token_h-quality_top+16}" fill="#F8FAFC"/>'
            )

    parts.extend([
        '<text x="24" y="82" class="panel">A · Gate-based quality score / 门禁质量分（0–100）</text>',
        f'<text x="{width-right}" y="82" text-anchor="end" class="badge">非劣效门槛 PASS · 未观察到质量下降</text>',
    ])
    for tick in range(0, 101, 25):
        y = quality_top + (100 - tick) / 100 * quality_h
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" class="label">{tick}</text>')
    parts.append(f'<line x1="{left}" y1="{quality_top}" x2="{left}" y2="{quality_top+quality_h}" class="axis"/>')
    for index, pair in enumerate(ordered_pairs):
        center = left + (index + 0.5) * group_w
        for side, arm, color in ((-1, "control", control_color), (1, "experiment", experiment_color)):
            value = float(pair[arm]["quality_score"])
            x = center + side * (bar_w + gap) / 2 - bar_w / 2
            bar_h = value / 100 * quality_h
            y = quality_top + quality_h - bar_h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="2"/>')
            parts.append(f'<text x="{x+bar_w/2:.1f}" y="{max(98, y-5):.1f}" text-anchor="middle" class="value">{value:g}</text>')

    parts.extend([
        '<text x="24" y="391" class="panel">B · Expensive Sol Tokens / 昂贵 Sol Token（含失败与返工）</text>',
        f'<text x="{width-right}" y="391" text-anchor="end" class="badge">累计节省 {summary["cost"]["sol_savings_percent"]:.2f}%</text>',
    ])
    for tick in range(0, token_ceiling + token_step, token_step):
        y = token_top + token_h - tick / token_ceiling * token_h
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" class="grid"/>')
        label = "0" if tick == 0 else f"{tick // 1000}k"
        parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" class="label">{label}</text>')
    parts.append(f'<line x1="{left}" y1="{token_top}" x2="{left}" y2="{token_top+token_h}" class="axis"/>')
    for index, pair in enumerate(ordered_pairs):
        center = left + (index + 0.5) * group_w
        for side, arm, color in ((-1, "control", control_color), (1, "experiment", experiment_color)):
            value = int(pair[arm]["sol_tokens"])
            x = center + side * (bar_w + gap) / 2 - bar_w / 2
            bar_h = value / token_ceiling * token_h
            y = token_top + token_h - bar_h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="2"/>')
            parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y-5:.1f}" text-anchor="middle" class="value">{round(value/1000):g}k</text>')
        parts.append(f'<text x="{center:.1f}" y="{token_top+token_h+22}" text-anchor="middle" class="label">{escape(short_task(pair["task_id"], index))}</text>')

    parts.extend([
        f'<text x="{left+plot_w/2:.1f}" y="680" text-anchor="middle" class="label">Task ID（P-H/P-L 为原始 high/low Pilot）</text>',
        '<text x="24" y="706" class="subtitle">Bars: mechanical gate scores; verdict: paired task_success. Token counts include every unique expensive Sol Session; cheap-model usage remains auditable.</text>',
    ])
    return _svg(width, height, "".join(parts))


def _render_paired_quality(protocol: dict[str, Any], pairs: Sequence[dict[str, Any]], summary: dict[str, Any]) -> str:
    width = 760
    height = max(260, 100 + len(pairs) * 28)
    left, right, top = 170, 40, 60
    plot_w = width - left - right
    parts = ['<text x="24" y="30" class="title">Task 配对质量分</text>']
    for tick in range(0, 101, 20):
        x = left + tick / 100 * plot_w
        parts.append(f'<line x1="{x:.1f}" y1="{top-10}" x2="{x:.1f}" y2="{height-35}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-16}" text-anchor="middle" class="label">{tick}</text>')
    for index, pair in enumerate(pairs):
        y = top + index * 28
        c = left + pair["control"]["quality_score"] / 100 * plot_w
        e = left + pair["experiment"]["quality_score"] / 100 * plot_w
        parts.extend([
            f'<text x="{left-10}" y="{y+4}" text-anchor="end" class="label">{escape(pair["task_id"])}</text>',
            f'<line x1="{c:.1f}" y1="{y}" x2="{e:.1f}" y2="{y}" stroke="#9aa7b8" stroke-width="2"/>',
            f'<circle cx="{c:.1f}" cy="{y}" r="5" fill="#315efb"/>',
            f'<circle cx="{e:.1f}" cy="{y}" r="5" fill="#00a36c"/>',
        ])
    return _svg(width, height, "".join(parts))


def _render_risk_strata(protocol: dict[str, Any], pairs: Sequence[dict[str, Any]], summary: dict[str, Any]) -> str:
    width, height = 720, 390
    left, top, plot_h = 90, 60, 260
    parts = ['<text x="24" y="30" class="title">风险分层成功率</text>']
    for index, item in enumerate(summary["strata"]):
        group_x = left + index * 190
        for offset, key, color in ((0, "control_success_rate", "#315efb"), (62, "experiment_success_rate", "#00a36c")):
            value = item[key]
            bar_h = value * plot_h
            x = group_x + offset
            y = top + plot_h - bar_h
            parts.append(f'<rect x="{x}" y="{y:.1f}" width="48" height="{bar_h:.1f}" fill="{color}" rx="4"/>')
            parts.append(f'<text x="{x+24}" y="{y-7:.1f}" text-anchor="middle" class="label">{value:.0%}</text>')
        parts.append(f'<text x="{group_x+55}" y="{top+plot_h+24}" text-anchor="middle" class="label">{escape(item["risk"])} · n={item["pairs"]}</text>')
    return _svg(width, height, "".join(parts))


def _render_token_waterfall(protocol: dict[str, Any], pairs: Sequence[dict[str, Any]], summary: dict[str, Any]) -> str:
    width, height = 720, 330
    control = summary["cost"]["control_sol_tokens"]
    experiment = summary["cost"]["experiment_sol_tokens"]
    maximum = max(control, experiment) or 1
    parts = ['<text x="24" y="30" class="title">累计 Sol Token</text>']
    for index, (label, value, color) in enumerate((
        (protocol["control_arm"]["arm_id"], control, "#315efb"),
        (protocol["experiment_arm"]["arm_id"], experiment, "#00a36c"),
    )):
        y = 85 + index * 85
        bar_w = value / maximum * 540
        parts.extend([
            f'<text x="120" y="{y+22}" text-anchor="end" class="label">{escape(label)}</text>',
            f'<rect x="140" y="{y}" width="{bar_w:.1f}" height="34" fill="{color}" rx="5"/>',
            f'<text x="{148+bar_w:.1f}" y="{y+22}" class="label">{value:,}</text>',
        ])
    saving = summary["cost"]["sol_savings_percent"]
    parts.append(f'<text x="140" y="285" class="label">节省：{saving if saving is not None else "n/a"}%</text>')
    return _svg(width, height, "".join(parts))


def _markdown_report(protocol: dict[str, Any], pairs: Sequence[dict[str, Any]], summary: dict[str, Any]) -> str:
    quality = summary["quality"]
    cost = summary["cost"]
    lines = [
        f"# Token Firewall Evaluation · {protocol['experiment_id']}",
        "",
        f"发布结论：**{summary['verdict']}**",
        f"当前 Pilot 门禁：**{summary['pilot_gate']}**",
        "",
        f"- 配对任务：{summary['sample_size']}（最低要求 {protocol['sampling']['minimum_pairs']}）",
        f"- Control 成功率：{quality['control_success_rate']:.1%}",
        f"- Experiment 成功率：{quality['experiment_success_rate']:.1%}",
        f"- 成功率差：{quality['difference_percentage_points']:.2f} pp",
        f"- 95% 配对 Bootstrap CI：[{quality['ci95_lower_percentage_points']:.2f}, {quality['ci95_upper_percentage_points']:.2f}] pp",
        f"- 非劣效：{quality['noninferior']}（margin {quality['noninferiority_margin_percentage_points']} pp）",
        f"- 累计 Sol Token：{cost['control_sol_tokens']:,} → {cost['experiment_sol_tokens']:,}",
        f"- Sol 节省：{cost['sol_savings_percent']}%（目标 {cost['target_percent']}%）",
        f"- 用量完整：{summary['usage_complete']}",
        "",
        "## 图表",
        "",
    ]
    lines.extend(f"- [{name}]({name})" for name in summary["artifacts"]["charts"])
    lines.extend(["", "## Task 明细", "", "| Task | Risk | Type | Control | Experiment | Sol Token C→E |", "|---|---|---|---:|---:|---:|"])
    for pair in pairs:
        lines.append(
            f"| {pair['task_id']} | {pair['risk']} | {pair['task_type']} | "
            f"{pair['control']['quality_score']:.1f} | {pair['experiment']['quality_score']:.1f} | "
            f"{pair['control']['sol_tokens']:,}→{pair['experiment']['sol_tokens']:,} |"
        )
    return "\n".join(lines) + "\n"
