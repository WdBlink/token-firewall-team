from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .gates import validate_review_packet, validate_work_order_graph, verify_delivery
from .archive import archive_run_snapshot, verify_run_snapshot
from .benchmark import (
    BenchmarkIdentity,
    BenchmarkRunner,
    compare_benchmarks,
    finalize_hidden_evaluation,
    summarize_rework_campaign,
)
from .budget import gate_sol_budget
from .orchestrator import RuntimePocRunner
from .evaluation import (
    build_evaluation_lab,
    export_inspect_dataset,
    pair_from_benchmark_records,
    write_evaluation_artifacts,
)
from .observability import ExternalRunStateError, discover_ledgers, format_status_card, project_status
from .runtime import (
    CodexCliAdapter,
    ClaudeCodeAdapter,
    MavisSessionAdapter,
    RecoveredMavisReadOnlyAdapter,
    RecoveredMavisSessionAdapter,
    RecoveredPatchAdapter,
    RuntimeAdapter,
)
from .schema import SchemaRegistry, SchemaValidationError
from .state import Conductor, StateTransitionError, atomic_write_json


def _read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token-firewall",
        description="Validate and replay the Token Firewall Agent Team protocol POC.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one protocol JSON object")
    validate.add_argument("file", type=Path)

    dag = subparsers.add_parser("gate-dag", help="validate a JSON array of Work Orders")
    dag.add_argument("file", type=Path)

    packet = subparsers.add_parser("gate-packet", help="validate a Review Packet and its evidence refs")
    packet.add_argument("file", type=Path)
    packet.add_argument("--artifact-root", type=Path, required=True)

    delivery = subparsers.add_parser("gate-delivery", help="verify a Delivery Manifest against Git truth")
    delivery.add_argument("work_order", type=Path)
    delivery.add_argument("manifest", type=Path)
    delivery.add_argument("--repo", type=Path, required=True)
    delivery.add_argument("--artifact-root", type=Path, required=True)
    delivery.add_argument("--no-rerun-tests", action="store_true")

    budget = subparsers.add_parser("gate-budget", help="enforce a frozen risk-tier Sol Token budget")
    budget.add_argument("policy", type=Path)
    budget.add_argument("work_order", type=Path)
    budget.add_argument("stages", type=Path, help="JSON array of metered stage records")
    budget.add_argument("--baseline-sol-tokens", type=int)
    budget.add_argument("--rework-rounds", type=int, default=0)

    replay = subparsers.add_parser("replay", help="recover authoritative state from events.jsonl")
    replay.add_argument("run_dir", type=Path)
    replay.add_argument("--mission-id", required=True)

    archive = subparsers.add_parser("archive-run", help="freeze a completed run into a hashed snapshot archive")
    archive.add_argument("run_dir", type=Path)
    archive.add_argument("archive", type=Path)

    verify_archive = subparsers.add_parser("verify-archive", help="verify a frozen run snapshot and receipt")
    verify_archive.add_argument("archive", type=Path)

    runtime_preflight = subparsers.add_parser("runtime-preflight", help="check a real Runtime Adapter without spending model tokens")
    runtime_preflight.add_argument("--runtime", choices=["codex", "claude", "minimax"], required=True)
    runtime_preflight.add_argument("--executable")
    runtime_preflight.add_argument("--agent", default="coder")

    runtime_run = subparsers.add_parser("runtime-run", help="run the single-Work-Order Runtime POC vertical slice")
    runtime_run.add_argument("mission_contract", type=Path)
    runtime_run.add_argument("work_order", type=Path)
    runtime_run.add_argument("--repo", type=Path, required=True)
    runtime_run.add_argument("--base", required=True)
    runtime_run.add_argument("--run-dir", type=Path, required=True)
    runtime_run.add_argument("--worktree-root", type=Path, required=True)
    runtime_run.add_argument("--worker-runtime", choices=["codex", "claude", "minimax"], default="minimax")
    runtime_run.add_argument("--worker-executable")
    runtime_run.add_argument("--worker-agent", default="coder")
    runtime_run.add_argument("--worker-model")
    runtime_run.add_argument("--recover-worker-runtime-snapshot", type=Path)
    runtime_run.add_argument("--recover-worker-patch", type=Path)
    runtime_run.add_argument("--review-runtime", choices=["none", "codex", "claude", "minimax"], default="none")
    runtime_run.add_argument("--reviewer-executable")
    runtime_run.add_argument("--reviewer-agent", default="verifier")
    runtime_run.add_argument("--reviewer-model")
    runtime_run.add_argument("--timeout", type=int, default=1800)
    runtime_run.add_argument("--poll-interval", type=float, default=2.0)

    benchmark_run = subparsers.add_parser("benchmark-run", help="run one frozen D/A benchmark group")
    benchmark_run.add_argument("identity", type=Path)
    benchmark_run.add_argument("mission_contract", type=Path)
    benchmark_run.add_argument("work_order", type=Path)
    benchmark_run.add_argument("--repo", type=Path, required=True)
    benchmark_run.add_argument("--run-dir", type=Path, required=True)
    benchmark_run.add_argument("--worktree-root", type=Path, required=True)
    benchmark_run.add_argument("--worker-runtime", choices=["codex", "claude", "minimax"], required=True)
    benchmark_run.add_argument("--worker-executable")
    benchmark_run.add_argument("--worker-agent", default="coder")
    benchmark_run.add_argument("--worker-model", required=True)
    benchmark_run.add_argument("--recover-worker-runtime-snapshot", type=Path)
    benchmark_run.add_argument("--recover-worker-patch", type=Path)
    benchmark_run.add_argument(
        "--recover-worker-session",
        help="recover a finished Mavis worker session without sending a new model turn",
    )
    benchmark_run.add_argument(
        "--recover-worker-commit",
        help="commit produced by --recover-worker-session",
    )
    benchmark_run.add_argument(
        "--recover-worker-snapshot",
        type=Path,
        help="immutable runtime-worker artifact directory captured at delivery time",
    )
    benchmark_run.add_argument("--verifier-runtime", choices=["none", "codex", "claude", "minimax"], default="none")
    benchmark_run.add_argument("--verifier-executable")
    benchmark_run.add_argument("--verifier-agent", default="verifier")
    benchmark_run.add_argument("--verifier-model")
    benchmark_run.add_argument(
        "--recover-verifier-session",
        help="recover a finished read-only Mavis verifier without a new model turn",
    )
    benchmark_run.add_argument(
        "--recover-verifier-snapshot", type=Path,
        help="immutable Mavis verifier artifact directory; avoids dependency on the live CLI/daemon",
    )
    benchmark_run.add_argument(
        "--recover-verifier-source-patch", type=Path,
        help="frozen patch reviewed by the recovered verifier; permits an evidence-checked commit-id remap",
    )
    benchmark_run.add_argument("--reviewer-runtime", choices=["codex", "claude", "minimax"], default="codex")
    benchmark_run.add_argument("--reviewer-executable")
    benchmark_run.add_argument("--reviewer-agent", default="verifier")
    benchmark_run.add_argument("--reviewer-model", required=True)
    benchmark_run.add_argument("--hidden-test", type=Path)
    benchmark_run.add_argument("--hidden-test-id", required=True)
    benchmark_run.add_argument("--hidden-suite-sha256", required=True)
    benchmark_run.add_argument("--defer-hidden", action="store_true")
    benchmark_run.add_argument("--timeout", type=int, default=1800)
    benchmark_run.add_argument("--poll-interval", type=float, default=2.0)

    benchmark_compare = subparsers.add_parser("benchmark-compare", help="compare frozen D and A records")
    benchmark_compare.add_argument("control_record", type=Path)
    benchmark_compare.add_argument("experiment_record", type=Path)

    benchmark_rework = subparsers.add_parser(
        "benchmark-summarize-rework",
        help="summarize D control, initial A, and chained B rework records",
    )
    benchmark_rework.add_argument("control_record", type=Path)
    benchmark_rework.add_argument("initial_record", type=Path)
    benchmark_rework.add_argument("rework_records", type=Path, nargs="+")

    benchmark_hidden = subparsers.add_parser(
        "benchmark-finalize-hidden",
        help="run a frozen hidden suite after all model groups have ended",
    )
    benchmark_hidden.add_argument("record", type=Path)
    benchmark_hidden.add_argument("--hidden-test", type=Path, required=True)
    benchmark_hidden.add_argument("--private-root", type=Path)

    observe_status = subparsers.add_parser(
        "observe-status",
        help="show low-noise status projections for external Runtime stages",
    )
    observe_status.add_argument("path", type=Path)
    observe_status.add_argument("--format", choices=["json", "card"], default="card")
    observe_status.add_argument("--stalled-after", type=int, default=180)

    observe_events = subparsers.add_parser(
        "observe-events",
        help="read external Runtime lifecycle events without terminal output",
    )
    observe_events.add_argument("path", type=Path)
    observe_events.add_argument("--after-sequence", type=int, default=0)

    evaluation = subparsers.add_parser(
        "evaluation-summarize",
        help="evaluate paired control/experiment outcomes and render reports",
    )
    evaluation.add_argument("protocol", type=Path)
    evaluation.add_argument("pairs", type=Path)
    evaluation.add_argument("--out-dir", type=Path, required=True)

    evaluation_import = subparsers.add_parser(
        "evaluation-import",
        help="normalize frozen D/A(+B) benchmark records into one traceable pair",
    )
    evaluation_import.add_argument("protocol", type=Path)
    evaluation_import.add_argument("control", type=Path)
    evaluation_import.add_argument("experiment", type=Path)
    evaluation_import.add_argument("--rework", type=Path, nargs="*", default=[])
    evaluation_import.add_argument(
        "--failed-attempt", type=Path, nargs="*", default=[],
        help="failed same-task benchmark records whose unique sessions must remain in cost accounting",
    )
    evaluation_import.add_argument(
        "--failed-control-attempt", type=Path, nargs="*", default=[],
        help="failed same-task D records whose unique sessions must remain in control cost accounting",
    )
    evaluation_import.add_argument("--pair-id", required=True)
    evaluation_import.add_argument("--risk", choices=["low", "medium", "high"], required=True)
    evaluation_import.add_argument("--task-type", required=True)
    evaluation_import.add_argument("--out", type=Path, required=True)

    evaluation_lab = subparsers.add_parser(
        "evaluation-lab-run",
        help="freeze a set of traceable pairs and render an Evaluation Lab report",
    )
    evaluation_lab.add_argument("protocol", type=Path)
    evaluation_lab.add_argument("pairs", type=Path, nargs="+")
    evaluation_lab.add_argument("--lab-id", required=True)
    evaluation_lab.add_argument("--out-dir", type=Path, required=True)

    inspect_export = subparsers.add_parser(
        "evaluation-export-inspect",
        help="export frozen evaluation pairs for optional Inspect AI analysis",
    )
    inspect_export.add_argument("protocol", type=Path)
    inspect_export.add_argument("pairs", type=Path, nargs="+")
    inspect_export.add_argument("--out-dir", type=Path, required=True)
    return parser


def _adapter(kind: str, executable: str | None, agent: str, registry: SchemaRegistry) -> RuntimeAdapter:
    if kind == "codex":
        return CodexCliAdapter(executable or "codex", registry=registry)
    if kind == "minimax":
        return MavisSessionAdapter(executable or "minimax", agent=agent, registry=registry)
    if kind == "claude":
        return ClaudeCodeAdapter(executable or "claude", registry=registry)
    raise ValueError(f"unsupported runtime adapter: {kind}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = SchemaRegistry()
    try:
        if args.command == "validate":
            value = _read_json(args.file)
            registry.validate(value)
            _print({"ok": True, "schema": value["schema"], "file": str(args.file)})
            return 0
        if args.command == "gate-dag":
            orders = _read_json(args.file)
            if not isinstance(orders, list):
                raise ValueError("gate-dag input must be a JSON array")
            for order in orders:
                registry.validate(order)
            result = validate_work_order_graph(orders)
            _print(result.to_dict())
            return 0 if result.ok else 1
        if args.command == "gate-packet":
            result = validate_review_packet(_read_json(args.file), args.artifact_root, registry=registry)
            _print(result.to_dict())
            return 0 if result.ok else 1
        if args.command == "gate-delivery":
            result = verify_delivery(
                args.repo,
                args.artifact_root,
                _read_json(args.work_order),
                _read_json(args.manifest),
                rerun_tests=not args.no_rerun_tests,
                registry=registry,
            )
            _print(result.to_dict())
            return 0 if result.ok else 1
        if args.command == "gate-budget":
            stages = _read_json(args.stages)
            if not isinstance(stages, list):
                raise ValueError("gate-budget stages input must be a JSON array")
            result = gate_sol_budget(
                _read_json(args.policy), _read_json(args.work_order), stages,
                baseline_sol_tokens=args.baseline_sol_tokens,
                rework_rounds=args.rework_rounds,
                registry=registry,
            )
            _print(result.to_dict())
            return 0 if result.ok else 1
        if args.command == "replay":
            state = Conductor(args.mission_id, args.run_dir, registry=registry).state
            _print({"ok": True, "state": state})
            return 0
        if args.command == "archive-run":
            receipt = archive_run_snapshot(args.run_dir, args.archive)
            _print({"ok": True, "receipt": receipt})
            return 0
        if args.command == "verify-archive":
            result = verify_run_snapshot(args.archive)
            _print(result)
            return 0 if result["ok"] else 1
        if args.command == "runtime-preflight":
            adapter = _adapter(args.runtime, args.executable, args.agent, registry)
            result = adapter.preflight()
            _print(result.to_dict())
            return 0 if result.ok else 1
        if args.command == "runtime-run":
            worker = _adapter(args.worker_runtime, args.worker_executable, args.worker_agent, registry)
            generic_recovery = (args.recover_worker_runtime_snapshot, args.recover_worker_patch)
            if any(generic_recovery) and not all(generic_recovery):
                raise ValueError("generic Worker recovery requires both runtime snapshot and patch")
            if all(generic_recovery):
                worker = RecoveredPatchAdapter(
                    args.recover_worker_runtime_snapshot,
                    args.recover_worker_patch,
                    expected_base_commit=args.base,
                    registry=registry,
                )
            reviewer = None
            if args.review_runtime != "none":
                reviewer = _adapter(args.review_runtime, args.reviewer_executable, args.reviewer_agent, registry)
            worker_model = args.worker_model
            if worker_model is None and args.worker_runtime == "minimax":
                worker_model = "minimax/MiniMax-M3"
            runner = RuntimePocRunner(
                repo_root=args.repo,
                run_dir=args.run_dir,
                worktree_root=args.worktree_root,
                worker=worker,
                reviewer=reviewer,
                registry=registry,
            )
            result = runner.run(
                _read_json(args.mission_contract),
                _read_json(args.work_order),
                base_commit=args.base,
                worker_model=worker_model,
                reviewer_model=args.reviewer_model,
                timeout_seconds=args.timeout,
                poll_interval_seconds=args.poll_interval,
            )
            _print(result.to_dict())
            return 0 if result.status in {"REVIEW_READY", "PASSED"} else 1
        if args.command == "benchmark-run":
            identity_value = _read_json(args.identity)
            identity = BenchmarkIdentity(
                run_id=identity_value["run_id"],
                group_id=identity_value["group_id"],
                task_revision=identity_value["task_revision"],
                base_sha=identity_value["base_sha"],
            )
            if identity.group_id in {"A", "C", "E"} and args.verifier_runtime == "none":
                raise ValueError(f"group {identity.group_id} requires a fresh verifier Runtime")
            if identity.group_id == "D" and args.verifier_runtime != "none":
                raise ValueError("group D must not use the A-group verifier stage")
            if not args.defer_hidden and args.hidden_test is None:
                raise ValueError("--hidden-test is required unless --defer-hidden is set")
            worker = _adapter(args.worker_runtime, args.worker_executable, args.worker_agent, registry)
            generic_recovery = (args.recover_worker_runtime_snapshot, args.recover_worker_patch)
            if any(generic_recovery) and not all(generic_recovery):
                raise ValueError("generic Worker recovery requires both runtime snapshot and patch")
            if all(generic_recovery):
                if args.recover_worker_session or args.recover_worker_commit or args.recover_worker_snapshot:
                    raise ValueError("generic Worker recovery cannot be combined with Mavis session recovery")
                worker = RecoveredPatchAdapter(
                    args.recover_worker_runtime_snapshot,
                    args.recover_worker_patch,
                    expected_base_commit=identity.base_sha,
                    registry=registry,
                )
            recovery_values = (args.recover_worker_session, args.recover_worker_commit)
            if any(recovery_values) and not all(recovery_values):
                raise ValueError("worker recovery requires both session and commit")
            if all(recovery_values):
                if args.worker_runtime != "minimax" or not isinstance(worker, MavisSessionAdapter):
                    raise ValueError("worker recovery is supported only for the Mavis adapter")
                worker = RecoveredMavisSessionAdapter(
                    worker,
                    session_id=args.recover_worker_session,
                    recovered_commit=args.recover_worker_commit,
                    expected_base_commit=identity.base_sha,
                    snapshot_dir=args.recover_worker_snapshot,
                )
            elif args.recover_worker_snapshot is not None:
                raise ValueError("worker snapshot recovery requires session and commit")
            reviewer = _adapter(args.reviewer_runtime, args.reviewer_executable, args.reviewer_agent, registry)
            verifier = None
            if args.recover_verifier_snapshot is not None and not args.recover_verifier_session:
                raise ValueError("verifier snapshot recovery requires --recover-verifier-session")
            if args.recover_verifier_source_patch is not None and args.recover_verifier_snapshot is None:
                raise ValueError("verifier commit remap requires --recover-verifier-snapshot")
            if args.verifier_runtime != "none":
                verifier = _adapter(
                    args.verifier_runtime,
                    args.verifier_executable,
                    args.verifier_agent,
                    registry,
                )
                if args.recover_verifier_session:
                    if args.verifier_runtime != "minimax" or not isinstance(verifier, MavisSessionAdapter):
                        raise ValueError("verifier recovery is supported only for the Mavis adapter")
                    verifier = RecoveredMavisReadOnlyAdapter(
                        verifier,
                        session_id=args.recover_verifier_session,
                        snapshot_dir=args.recover_verifier_snapshot,
                        source_patch=args.recover_verifier_source_patch,
                        expected_base_commit=identity.base_sha if args.recover_verifier_source_patch else None,
                    )
            elif args.recover_verifier_session:
                raise ValueError("verifier recovery requires a verifier Runtime")
            record = BenchmarkRunner(
                repo_root=args.repo,
                run_dir=args.run_dir,
                worktree_root=args.worktree_root,
                worker=worker,
                verifier=verifier,
                reviewer=reviewer,
                registry=registry,
            ).run(
                identity,
                _read_json(args.mission_contract),
                _read_json(args.work_order),
                worker_model=args.worker_model,
                verifier_model=args.verifier_model,
                reviewer_model=args.reviewer_model,
                hidden_command=(
                    None
                    if args.defer_hidden
                    else [sys.executable, "-B", str(args.hidden_test.resolve())]
                ),
                hidden_test_id=args.hidden_test_id,
                hidden_suite_sha256=args.hidden_suite_sha256,
                timeout_seconds=args.timeout,
                poll_interval_seconds=args.poll_interval,
            )
            _print(record)
            return 0 if record["status"] in {"MODEL_STAGES_COMPLETE", "COMPLETE"} else 1
        if args.command == "benchmark-compare":
            comparison = compare_benchmarks(
                _read_json(args.control_record),
                _read_json(args.experiment_record),
            )
            _print(comparison)
            return 0 if comparison["comparable"] else 1
        if args.command == "benchmark-summarize-rework":
            summary = summarize_rework_campaign(
                _read_json(args.control_record),
                _read_json(args.initial_record),
                [_read_json(path) for path in args.rework_records],
            )
            _print(summary)
            return 0 if summary["campaign_pass"] else 1
        if args.command == "benchmark-finalize-hidden":
            record = finalize_hidden_evaluation(
                args.record,
                [sys.executable, "-B", str(args.hidden_test.resolve())],
                private_root=args.private_root,
                registry=registry,
            )
            _print(record)
            return 0 if record["status"] == "COMPLETE" else 1
        if args.command == "observe-status":
            ledgers = discover_ledgers(args.path)
            states = [
                project_status(ledger.state, stalled_after_seconds=args.stalled_after)
                for ledger in ledgers
            ]
            if args.format == "json":
                _print({"ok": True, "runs": states})
            else:
                print("\n\n".join(
                    format_status_card(ledger.state, stalled_after_seconds=args.stalled_after)
                    for ledger in ledgers
                ))
            return 0
        if args.command == "observe-events":
            ledgers = discover_ledgers(args.path)
            events = [
                event
                for ledger in ledgers
                for event in ledger.events(after_sequence=args.after_sequence)
            ]
            events.sort(key=lambda item: (item["at"], item["run_id"], item["stage"], item["sequence"]))
            _print({"ok": True, "events": events})
            return 0
        if args.command == "evaluation-summarize":
            pairs = _read_json(args.pairs)
            if not isinstance(pairs, list):
                raise ValueError("evaluation pairs input must be a JSON array")
            summary = write_evaluation_artifacts(
                _read_json(args.protocol),
                pairs,
                args.out_dir,
                registry=registry,
            )
            _print(summary)
            return 0 if summary["verdict"] == "PASS" else 1
        if args.command == "evaluation-import":
            pair = pair_from_benchmark_records(
                _read_json(args.protocol),
                _read_json(args.control),
                [_read_json(args.experiment), *(_read_json(path) for path in args.rework)],
                pair_id=args.pair_id,
                risk=args.risk,
                task_type=args.task_type,
                failed_attempts=[_read_json(path) for path in args.failed_attempt],
                failed_control_attempts=[_read_json(path) for path in args.failed_control_attempt],
                registry=registry,
            )
            atomic_write_json(args.out, pair)
            _print({"ok": True, "pair": pair, "file": str(args.out)})
            return 0
        if args.command == "evaluation-lab-run":
            result = build_evaluation_lab(
                _read_json(args.protocol),
                [_read_json(path) for path in args.pairs],
                args.out_dir,
                lab_id=args.lab_id,
                registry=registry,
            )
            _print(result)
            return 0 if result["summary"]["verdict"] == "PASS" else 1
        if args.command == "evaluation-export-inspect":
            result = export_inspect_dataset(
                _read_json(args.protocol),
                [_read_json(path) for path in args.pairs],
                args.out_dir,
                registry=registry,
            )
            _print({"ok": True, "manifest": result["manifest"], "out_dir": str(args.out_dir)})
            return 0
    except (OSError, ValueError, json.JSONDecodeError, SchemaValidationError, StateTransitionError, ExternalRunStateError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
