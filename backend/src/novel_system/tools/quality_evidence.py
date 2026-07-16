"""Safe operator CLI for the stage-2 hidden quality-evidence lifecycle.

Raw hidden rubrics, prompts, generated prose, and edited prose are read from
files and never printed.  Command output contains only ids, hashes, counters,
policy resolution, and aggregate metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from novel_system.services.errors import DomainError
from novel_system.services.quality_evidence import QualityEvidenceService, load_hidden_benchmark
from novel_system.services.quality_strategy import QualityStrategyResolver, QualityStrategyService


def inspect_hidden_benchmark(
    public_cases_path: str | Path,
    private_rubric_path: str | Path,
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Return hashes/coverage and, optionally, one sanitized generation payload."""

    bundle = load_hidden_benchmark(public_cases_path, private_rubric_path)
    payload: dict[str, Any] = {"benchmark": bundle.public_summary()}
    if case_id is not None:
        payload["generation_payload"] = bundle.payload_for(case_id)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect and inspect hidden quality evidence safely")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="validate split files and show hash-only coverage")
    _add_bundle_args(inspect_parser)
    inspect_parser.add_argument("--case-id")

    register = subparsers.add_parser("register", help="freeze a hidden manifest in the evidence database")
    _add_bundle_args(register)
    register.add_argument("--storage-ref", required=True)

    create_policy = subparsers.add_parser("create-policy", help="create a fail-closed strategy policy")
    create_policy.add_argument("--genre", default="*")
    create_policy.add_argument("--scene-function", default="*")
    create_policy.add_argument("--weights-file")
    create_policy.add_argument("--thresholds-file")
    create_policy.add_argument("--request-best-of-n", action="store_true")
    create_policy.add_argument("--best-of-n-n", type=int, default=1)
    create_policy.add_argument("--policy-version", type=int, default=1)
    create_policy.add_argument("--manifest-id")
    create_policy.add_argument("--experiment-id")
    create_policy.add_argument("--created-by", default="operator")

    bind_policy = subparsers.add_parser("bind-policy", help="bind a policy to completed blind evidence")
    bind_policy.add_argument("--policy-id", required=True)
    bind_policy.add_argument("--manifest-id", required=True)
    bind_policy.add_argument("--experiment-id", required=True)

    start = subparsers.add_parser("start-run", help="start one immutable hidden benchmark run")
    start.add_argument("--manifest-id", required=True)
    start.add_argument("--generator-ref", required=True)
    start.add_argument("--policy-id")
    start.add_argument("--generation-policy-file")
    start.add_argument(
        "--generation-arm",
        choices=("treatment", "control", "unassigned"),
        default="unassigned",
    )

    record = subparsers.add_parser("record-result", help="record a hash-bound generation result")
    _add_bundle_args(record)
    record.add_argument("--run-id", required=True)
    record.add_argument("--case-id", required=True)
    record.add_argument("--actual-prompt-file", required=True)
    record.add_argument("--output-file", required=True)
    record.add_argument("--artifact-ref", required=True)
    record.add_argument("--automated-metrics-file")
    record.add_argument("--cost-tokens", type=int)
    record.add_argument("--cost-micros", type=int)
    record.add_argument("--cost-currency")
    record.add_argument("--cost-basis", choices=("estimated", "actual", "billed"))
    record.add_argument("--latency-ms", type=int)

    complete = subparsers.add_parser("complete-run", help="seal a run after exact case coverage")
    complete.add_argument("--run-id", required=True)

    human = subparsers.add_parser("human-observation", help="record explicit human value evidence")
    human.add_argument("--result-id", required=True)
    human.add_argument("--reviewer-ref", required=True)
    human.add_argument("--source-file")
    human.add_argument("--edited-file")
    human.add_argument("--first-usable", choices=("true", "false"))
    human.add_argument("--follow-read-intent", type=int)

    summarize = subparsers.add_parser("summarize", help="aggregate observed and missing denominators")
    summarize.add_argument("--manifest-id", required=True)
    summarize.add_argument("--genre")
    summarize.add_argument("--scene-function")

    resolve = subparsers.add_parser("resolve", help="show effective strategy and all release blockers")
    resolve.add_argument("--genre", required=True)
    resolve.add_argument("--scene-function", required=True)
    return parser


def _add_bundle_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--public-cases", required=True)
    parser.add_argument("--private-rubric", required=True)


def _read_text(path: str | None, *, label: str) -> str | None:
    if path is None:
        return None
    try:
        return Path(path).expanduser().resolve().read_text(encoding="utf-8")
    except OSError as exc:
        raise DomainError("QUALITY_COLLECTOR_FILE_INVALID", f"{label} file is unavailable", 422) from exc


def _read_json_object(path: str | None, *, label: str) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = _read_text(path, label=label)
    try:
        value = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise DomainError("QUALITY_COLLECTOR_FILE_INVALID", f"{label} must be valid JSON", 422) from exc
    if not isinstance(value, dict):
        raise DomainError("QUALITY_COLLECTOR_FILE_INVALID", f"{label} root must be an object", 422)
    return value


def _execute_db_command(args: argparse.Namespace, session) -> tuple[dict[str, Any], bool]:
    evidence = QualityEvidenceService(session)
    strategy = QualityStrategyService(session)
    command = args.command
    if command == "register":
        bundle = load_hidden_benchmark(args.public_cases, args.private_rubric)
        row = evidence.register_manifest(bundle, storage_ref=args.storage_ref)
        return {
            "manifest_id": row.manifest_id,
            "manifest_hash": row.manifest_hash,
            "rubric_hash": row.rubric_hash,
            "case_count": row.case_count,
            "status": row.status,
        }, True
    if command == "create-policy":
        row = strategy.create_policy(
            genre=args.genre,
            scene_function=args.scene_function,
            weights=_read_json_object(args.weights_file, label="weights"),
            thresholds=_read_json_object(args.thresholds_file, label="thresholds"),
            best_of_n_requested=args.request_best_of_n,
            best_of_n_n=args.best_of_n_n,
            evidence_experiment_id=args.experiment_id,
            benchmark_manifest_id=args.manifest_id,
            policy_version=args.policy_version,
            created_by=args.created_by,
        )
        return {
            "policy_id": row.policy_id,
            "scope": [row.genre, row.scene_function],
            "policy_version": row.policy_version,
            "best_of_n_requested": row.best_of_n_requested,
            "best_of_n_n": row.best_of_n_n,
            "status": row.status,
        }, True
    if command == "bind-policy":
        row = strategy.bind_evidence(
            args.policy_id,
            evidence_experiment_id=args.experiment_id,
            benchmark_manifest_id=args.manifest_id,
        )
        return {
            "policy_id": row.policy_id,
            "experiment_id": row.evidence_experiment_id,
            "manifest_id": row.benchmark_manifest_id,
            "status": row.status,
        }, True
    if command == "start-run":
        row = evidence.start_run(
            args.manifest_id,
            generator_ref=args.generator_ref,
            policy_id=args.policy_id,
            generation_policy=_read_json_object(args.generation_policy_file, label="generation policy"),
            generation_arm=args.generation_arm,
        )
        return {
            "run_id": row.run_id,
            "manifest_id": row.manifest_id,
            "manifest_hash": row.manifest_hash,
            "rubric_hash": row.rubric_hash,
            "generation_policy_hash": row.generation_policy_hash,
            "generation_arm": row.generation_arm,
            "case_count_expected": row.case_count_expected,
            "status": row.status,
        }, True
    if command == "record-result":
        bundle = load_hidden_benchmark(args.public_cases, args.private_rubric)
        row = evidence.record_generation_result(
            args.run_id,
            bundle=bundle,
            case_id=args.case_id,
            generation_payload=bundle.payload_for(args.case_id),
            actual_prompt_text=_read_text(args.actual_prompt_file, label="actual prompt") or "",
            output_text=_read_text(args.output_file, label="output") or "",
            artifact_ref=args.artifact_ref,
            automated_metrics=_read_json_object(args.automated_metrics_file, label="automated metrics"),
            cost_tokens=args.cost_tokens,
            cost_micros=args.cost_micros,
            cost_currency=args.cost_currency,
            cost_basis=args.cost_basis,
            latency_ms=args.latency_ms,
        )
        return {
            "result_id": row.result_id,
            "run_id": row.run_id,
            "case_id_hash": row.case_id_hash,
            "generation_input_hash": row.generation_input_hash,
            "generation_prompt_hash": row.generation_prompt_hash,
            "output_hash": row.output_hash,
            "prompt_leakage_check": row.prompt_leakage_check,
            "cost_observed": row.cost_tokens is not None,
            "monetary_cost_observed": row.cost_micros is not None,
            "latency_observed": row.latency_ms is not None,
        }, True
    if command == "complete-run":
        row = evidence.complete_run(args.run_id)
        return {
            "run_id": row.run_id,
            "status": row.status,
            "case_count_expected": row.case_count_expected,
            "case_count_recorded": row.case_count_recorded,
            "completed_at": row.completed_at,
        }, True
    if command == "human-observation":
        first_usable = None if args.first_usable is None else args.first_usable == "true"
        row = evidence.record_human_observation(
            args.result_id,
            reviewer_ref=args.reviewer_ref,
            provenance="human",
            source_text=_read_text(args.source_file, label="source"),
            edited_text=_read_text(args.edited_file, label="edited"),
            first_usable=first_usable,
            follow_read_intent=args.follow_read_intent,
        )
        return {
            "observation_id": row.observation_id,
            "result_id": row.result_id,
            "reviewer_ref": row.reviewer_ref,
            "provenance": row.provenance,
            "source_text_hash": row.source_text_hash,
            "edited_text_hash": row.edited_text_hash,
            "human_edit_distance": row.human_edit_distance,
            "human_edit_distance_ratio": row.human_edit_distance_ratio,
            "first_usable": row.first_usable,
            "follow_read_intent": row.follow_read_intent,
        }, True
    if command == "summarize":
        return evidence.summarize_value_metrics(
            args.manifest_id,
            genre=args.genre,
            scene_function=args.scene_function,
        ), False
    if command == "resolve":
        return QualityStrategyResolver(session).resolve(
            args.genre,
            args.scene_function,
        ).public_summary(), False
    raise DomainError("QUALITY_COLLECTOR_COMMAND_INVALID", "unsupported collector command", 422)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            report = inspect_hidden_benchmark(
                args.public_cases,
                args.private_rubric,
                case_id=args.case_id,
            )
        else:
            from novel_system.db.session import SessionLocal

            session = SessionLocal()
            try:
                report, mutates = _execute_db_command(args, session)
                if mutates:
                    session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except DomainError as exc:
        print(
            json.dumps({"error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
