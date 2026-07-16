"""Stage-2 quality evidence with a hard public/private benchmark boundary.

The hidden rubric file is read only to validate case coverage and derive hashes.
No rubric text or expected answer is retained on the returned bundle or persisted
to the database.  Generation receives only :meth:`HiddenBenchmarkBundle.payload_for`.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    QualityBenchmarkManifest,
    QualityBenchmarkResult,
    QualityBenchmarkRun,
    QualityStrategyPolicy,
    QualityValueObservation,
    utcnow,
)
from novel_system.services.errors import DomainError
from novel_system.services.tension_curve import FUNCTION_TAGS


HIDDEN_BENCHMARK_SCHEMA_VERSION = 1
_ISOLATION_MODES = frozenset({"seed_project", "time_isolated", "external_holdout"})
_PRIVATE_KEY_MARKERS = frozenset(
    {
        "answer",
        "answerkey",
        "expectedanswer",
        "gold",
        "goldanswer",
        "privaterubric",
        "referenceanswer",
        "referencesolution",
        "rubric",
        "scoringguide",
    }
)
_HUMAN_METRIC_MARKERS = (
    "edit_distance",
    "first_usable",
    "follow_read",
    "human_preference",
    "reader_intent",
)
_STORAGE_REF = re.compile(r"^(?:vault|artifact):[A-Za-z0-9._-]{3,160}$")
_AUTOMATED_REVIEWER_PREFIXES = ("model:", "llm:", "ai:", "bot:", "auto:", "synthetic:")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _assert_public_payload(value: Any, *, path: str = "generation_input") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in _PRIVATE_KEY_MARKERS or any(
                marker in normalized for marker in ("expectedanswer", "referenceanswer", "privaterubric")
            ):
                raise DomainError(
                    "HIDDEN_BENCHMARK_PUBLIC_LEAK",
                    f"private evaluation key is forbidden in public generation input: {path}.{key}",
                    status_code=422,
                )
            _assert_public_payload(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public_payload(item, path=f"{path}[{index}]")


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _token_hashes(value: Any) -> set[str]:
    """Return only irreversible fingerprints used by the actual-prompt leak guard."""

    tokens: set[str] = set()
    for raw in _strings(value):
        compact = re.sub(r"\s+", " ", raw).strip().lower()
        if len(compact) >= 8:
            tokens.add(compact)
        tokens.update(re.findall(r"[a-z0-9_]{8,}", compact))
        for cjk_span in re.findall(r"[\u3400-\u9fff]{4,}", compact):
            tokens.add(cjk_span)
            if len(cjk_span) >= 8:
                tokens.update(cjk_span[index : index + 8] for index in range(len(cjk_span) - 7))
    return {_hash_text(token) for token in tokens}


def _secret_fingerprints(value: Any) -> set[str]:
    """Fingerprint secret scalar values, including deliberately short canaries.

    Structural private keys such as ``rubric`` are intentionally excluded: a
    prompt using that ordinary word is not evidence of answer leakage.  Exact
    values and their word/CJK tokens are retained only as irreversible hashes.
    """

    tokens: set[str] = set()
    for raw in _strings_without_keys(value):
        compact = re.sub(r"\s+", " ", raw).strip().lower()
        if len(compact) >= 1:
            tokens.add(compact)
        tokens.update(re.findall(r"[a-z0-9_]{2,}", compact))
        for cjk_span in re.findall(r"[\u3400-\u9fff]{2,}", compact):
            tokens.add(cjk_span)
            for width in range(2, min(8, len(cjk_span)) + 1):
                tokens.update(
                    cjk_span[index : index + width]
                    for index in range(len(cjk_span) - width + 1)
                )
    return {_hash_text(token) for token in tokens}


def _strings_without_keys(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings_without_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings_without_keys(item)


def _contains_nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_contains_nonempty(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nonempty(item) for item in value)
    return False


def _prompt_fingerprints(value: str) -> set[str]:
    fingerprints = _secret_fingerprints(value)
    # One-character hidden answers/canaries are rare but must not bypass the
    # guard.  Private multi-character values do not emit one-character hashes,
    # so adding prompt characters here does not explode false positives.
    compact = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    fingerprints.update(
        _hash_text(char)
        for char in compact
        if re.fullmatch(r"[a-z0-9_\u3400-\u9fff]", char)
    )
    return fingerprints


def _assert_no_human_metric_keys(value: Any, *, path: str = "automated_metrics") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if any(_normalized_key(marker) in normalized for marker in _HUMAN_METRIC_MARKERS):
                raise DomainError(
                    "QUALITY_HUMAN_METRIC_PROVENANCE_REQUIRED",
                    f"automated metrics cannot populate human value field: {path}.{key}",
                    status_code=422,
                )
            _assert_no_human_metric_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_human_metric_keys(item, path=f"{path}[{index}]")


def _read_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DomainError(
            "HIDDEN_BENCHMARK_INVALID",
            f"{label} file is unavailable or invalid JSON",
            status_code=422,
            details={"error_type": type(exc).__name__},
        ) from exc
    if not isinstance(payload, dict):
        raise DomainError("HIDDEN_BENCHMARK_INVALID", f"{label} root must be an object", status_code=422)
    return payload


@dataclass(frozen=True, slots=True)
class HiddenGenerationCase:
    case_id: str
    case_id_hash: str
    genre: str
    scene_function: str
    generation_input: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "genre": self.genre,
            "scene_function": self.scene_function,
            "generation_input": deepcopy(self.generation_input),
        }


@dataclass(frozen=True, slots=True)
class HiddenBenchmarkBundle:
    manifest_id: str
    manifest_version: str
    isolation_mode: str
    manifest_hash: str
    public_cases_hash: str
    rubric_hash: str
    cases: tuple[HiddenGenerationCase, ...]
    # Hashes only; no private token/rubric text survives the loader boundary.
    private_only_token_hashes: frozenset[str]

    def payload_for(self, case_id: str) -> dict[str, Any]:
        for case in self.cases:
            if case.case_id == case_id:
                return case.payload()
        raise DomainError("HIDDEN_BENCHMARK_CASE_NOT_FOUND", f"case {case_id} not found", status_code=404)

    def case_for(self, case_id: str) -> HiddenGenerationCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise DomainError("HIDDEN_BENCHMARK_CASE_NOT_FOUND", f"case {case_id} not found", status_code=404)

    def assert_actual_prompt_clean(self, actual_prompt_text: str) -> None:
        prompt_hashes = _prompt_fingerprints(str(actual_prompt_text or ""))
        if prompt_hashes & set(self.private_only_token_hashes):
            raise DomainError(
                "HIDDEN_BENCHMARK_PROMPT_LEAK",
                "actual generation prompt contains a private-rubric fingerprint",
                status_code=409,
            )

    def public_summary(self) -> dict[str, Any]:
        return {
            "schema_version": HIDDEN_BENCHMARK_SCHEMA_VERSION,
            "manifest_id": self.manifest_id,
            "manifest_version": self.manifest_version,
            "split_kind": "hidden",
            "isolation_mode": self.isolation_mode,
            "manifest_hash": self.manifest_hash,
            "public_cases_hash": self.public_cases_hash,
            "rubric_hash": self.rubric_hash,
            "case_count": len(self.cases),
            "cells": [
                {
                    "case_id_hash": case.case_id_hash,
                    "genre": case.genre,
                    "scene_function": case.scene_function,
                }
                for case in self.cases
            ],
        }


def load_hidden_benchmark(
    public_cases_path: str | Path,
    private_rubric_path: str | Path,
) -> HiddenBenchmarkBundle:
    """Load a split hidden benchmark without retaining private rubric contents."""

    public = _read_json_object(public_cases_path, label="public cases")
    private = _read_json_object(private_rubric_path, label="private rubric")
    if public.get("schema_version") != HIDDEN_BENCHMARK_SCHEMA_VERSION or private.get(
        "schema_version"
    ) != HIDDEN_BENCHMARK_SCHEMA_VERSION:
        raise DomainError("HIDDEN_BENCHMARK_SCHEMA_UNSUPPORTED", "benchmark schema_version must be 1", 422)
    manifest_id = str(public.get("manifest_id") or "").strip()
    if not manifest_id or manifest_id != str(private.get("manifest_id") or "").strip():
        raise DomainError("HIDDEN_BENCHMARK_MANIFEST_MISMATCH", "public/private manifest_id differs", 422)
    manifest_version = str(public.get("manifest_version") or "").strip()
    private_manifest_version = str(private.get("manifest_version") or "").strip()
    if not manifest_version or manifest_version != private_manifest_version:
        raise DomainError(
            "HIDDEN_BENCHMARK_VERSION_MISMATCH",
            "public/private manifest_version must be nonempty and identical",
            422,
        )
    isolation_mode = str(public.get("isolation_mode") or "").strip()
    if public.get("split_kind") != "hidden" or isolation_mode not in _ISOLATION_MODES:
        raise DomainError(
            "HIDDEN_BENCHMARK_ISOLATION_REQUIRED",
            "split_kind=hidden and a supported isolation_mode are required",
            422,
        )
    raw_cases = public.get("cases")
    raw_rubrics = private.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases or not isinstance(raw_rubrics, list):
        raise DomainError("HIDDEN_BENCHMARK_INVALID", "public and private cases must be lists", 422)

    cases: list[HiddenGenerationCase] = []
    public_ids: list[str] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise DomainError("HIDDEN_BENCHMARK_INVALID", f"public case {index} must be an object", 422)
        case_id = str(raw.get("case_id") or "").strip()
        genre = str(raw.get("genre") or "").strip()
        scene_function = str(raw.get("scene_function") or "").strip()
        generation_input = raw.get("generation_input")
        if (
            not case_id
            or case_id in public_ids
            or not genre
            or scene_function not in FUNCTION_TAGS
            or not isinstance(generation_input, dict)
            or not generation_input
        ):
            raise DomainError("HIDDEN_BENCHMARK_INVALID", f"public case {index} is incomplete", 422)
        _assert_public_payload(generation_input, path=f"cases[{index}].generation_input")
        public_ids.append(case_id)
        cases.append(
            HiddenGenerationCase(
                case_id=case_id,
                case_id_hash=_hash_text(f"{manifest_id}:{case_id}"),
                genre=genre,
                scene_function=scene_function,
                generation_input=deepcopy(generation_input),
            )
        )

    private_ids = []
    for index, raw in enumerate(raw_rubrics):
        if not isinstance(raw, dict) or not str(raw.get("case_id") or "").strip():
            raise DomainError("HIDDEN_BENCHMARK_INVALID", f"private case {index} is incomplete", 422)
        private_content = {
            key: value
            for key, value in raw.items()
            if _normalized_key(key) != "caseid"
            and (
                _normalized_key(key) in _PRIVATE_KEY_MARKERS
                or any(marker in _normalized_key(key) for marker in _PRIVATE_KEY_MARKERS)
            )
        }
        if not private_content or not _contains_nonempty(private_content):
            raise DomainError(
                "HIDDEN_BENCHMARK_PRIVATE_RUBRIC_REQUIRED",
                f"private case {index} requires a nonempty rubric, scoring guide, or answer",
                422,
            )
        private_ids.append(str(raw["case_id"]).strip())
    if sorted(public_ids) != sorted(private_ids) or len(private_ids) != len(set(private_ids)):
        raise DomainError("HIDDEN_BENCHMARK_CASE_MISMATCH", "public/private case ids differ", 422)

    public_hash = _hash_json(public)
    rubric_hash = _hash_json(private)
    private_secret_payload = [
        {
            key: value
            for key, value in raw.items()
            if _normalized_key(key) != "caseid"
        }
        for raw in raw_rubrics
    ]
    private_only_hashes = _secret_fingerprints(private_secret_payload) - _secret_fingerprints(public)
    manifest_hash = _hash_json(
        {
            "schema_version": HIDDEN_BENCHMARK_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "manifest_version": manifest_version,
            "public_cases_hash": public_hash,
            "rubric_hash": rubric_hash,
            "case_count": len(cases),
            "isolation_mode": isolation_mode,
        }
    )
    return HiddenBenchmarkBundle(
        manifest_id=manifest_id,
        manifest_version=manifest_version,
        isolation_mode=isolation_mode,
        manifest_hash=manifest_hash,
        public_cases_hash=public_hash,
        rubric_hash=rubric_hash,
        cases=tuple(cases),
        private_only_token_hashes=frozenset(private_only_hashes),
    )


class QualityEvidenceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register_manifest(
        self,
        bundle: HiddenBenchmarkBundle,
        *,
        storage_ref: str,
    ) -> QualityBenchmarkManifest:
        storage_ref = str(storage_ref or "").strip()
        if not _STORAGE_REF.fullmatch(storage_ref):
            raise DomainError(
                "HIDDEN_BENCHMARK_STORAGE_REF_INVALID",
                "storage_ref must be an opaque vault:/artifact: identifier, never a filesystem path",
                status_code=422,
            )
        existing = self.session.get(QualityBenchmarkManifest, bundle.manifest_id)
        if existing is not None:
            if (
                existing.manifest_hash != bundle.manifest_hash
                or existing.rubric_hash != bundle.rubric_hash
                or existing.public_cases_hash != bundle.public_cases_hash
                or existing.manifest_version != bundle.manifest_version
                or existing.case_count != len(bundle.cases)
                or existing.isolation_mode != bundle.isolation_mode
                or existing.storage_ref != storage_ref
                or existing.status != "frozen"
            ):
                raise DomainError(
                    "HIDDEN_BENCHMARK_MANIFEST_CONFLICT",
                    "manifest id is already bound to different frozen content",
                    status_code=409,
                )
            return existing
        row = QualityBenchmarkManifest(
            manifest_id=bundle.manifest_id,
            schema_version=HIDDEN_BENCHMARK_SCHEMA_VERSION,
            manifest_version=bundle.manifest_version,
            split_kind="hidden",
            manifest_hash=bundle.manifest_hash,
            public_cases_hash=bundle.public_cases_hash,
            rubric_hash=bundle.rubric_hash,
            case_count=len(bundle.cases),
            isolation_mode=bundle.isolation_mode,
            storage_ref=storage_ref,
            status="frozen",
        )
        self.session.add(row)
        self.session.flush()
        return row

    def start_run(
        self,
        manifest_id: str,
        *,
        generator_ref: str,
        policy_id: str | None = None,
        generation_policy: dict[str, Any] | None = None,
        generation_arm: str = "unassigned",
        run_id: str | None = None,
    ) -> QualityBenchmarkRun:
        manifest = self.session.get(QualityBenchmarkManifest, manifest_id)
        if manifest is None or manifest.status != "frozen":
            raise DomainError("HIDDEN_BENCHMARK_MANIFEST_NOT_FROZEN", "frozen manifest not found", 409)
        generator_ref = str(generator_ref or "").strip()
        if not generator_ref:
            raise DomainError("QUALITY_BENCHMARK_GENERATOR_REQUIRED", "generator_ref is required", 422)
        if generation_policy is not None and not isinstance(generation_policy, dict):
            raise DomainError("QUALITY_GENERATION_POLICY_INVALID", "generation_policy must be an object", 422)
        normalized_arm = str(generation_arm or "").strip().lower()
        if normalized_arm not in {"treatment", "control", "unassigned"}:
            raise DomainError(
                "QUALITY_GENERATION_ARM_INVALID",
                "generation_arm must be treatment, control, or unassigned",
                422,
            )
        if policy_id is not None:
            policy = self.session.get(QualityStrategyPolicy, policy_id)
            if (
                policy is None
                or policy.status != "active"
                or policy.benchmark_manifest_id != manifest.manifest_id
            ):
                raise DomainError(
                    "QUALITY_BENCHMARK_POLICY_NOT_APPLICABLE",
                    "policy must exist, be active, and be bound to this manifest",
                    409,
                )
        row = QualityBenchmarkRun(
            run_id=run_id or f"qbench_run_{uuid.uuid4().hex[:16]}",
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.manifest_hash,
            rubric_hash=manifest.rubric_hash,
            policy_id=policy_id,
            generator_ref=generator_ref,
            generation_policy_hash=_hash_json(generation_policy or {}),
            generation_arm=normalized_arm,
            status="collecting",
            case_count_expected=manifest.case_count,
            case_count_recorded=0,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def record_generation_result(
        self,
        run_id: str,
        *,
        bundle: HiddenBenchmarkBundle,
        case_id: str,
        generation_payload: dict[str, Any],
        actual_prompt_text: str,
        output_text: str,
        artifact_ref: str,
        automated_metrics: dict[str, Any] | None = None,
        cost_tokens: int | None = None,
        cost_micros: int | None = None,
        cost_currency: str | None = None,
        cost_basis: str | None = None,
        latency_ms: int | None = None,
        result_id: str | None = None,
    ) -> QualityBenchmarkResult:
        run = self.session.get(QualityBenchmarkRun, run_id)
        if run is None:
            raise DomainError("QUALITY_BENCHMARK_RUN_NOT_FOUND", "benchmark run not found", 404)
        if run.status not in {"collecting", "completed"}:
            raise DomainError("QUALITY_BENCHMARK_RUN_CLOSED", "benchmark run is not collecting", 409)
        if (
            run.manifest_id != bundle.manifest_id
            or run.manifest_hash != bundle.manifest_hash
            or run.rubric_hash != bundle.rubric_hash
        ):
            raise DomainError("QUALITY_BENCHMARK_MANIFEST_MISMATCH", "run and hidden bundle differ", 409)
        case = bundle.case_for(case_id)
        expected_payload = case.payload()
        if generation_payload != expected_payload:
            raise DomainError(
                "HIDDEN_BENCHMARK_GENERATION_PAYLOAD_MISMATCH",
                "generation must consume only the sanitized public case payload",
                409,
            )
        _assert_public_payload(generation_payload, path="generation_payload")
        bundle.assert_actual_prompt_clean(actual_prompt_text)
        metrics = dict(automated_metrics or {})
        _assert_no_human_metric_keys(metrics)
        _assert_optional_nonnegative_int(cost_tokens, field="cost_tokens", code="QUALITY_COST_INVALID")
        _assert_optional_nonnegative_int(latency_ms, field="latency_ms", code="QUALITY_LATENCY_INVALID")
        cost_fields_present = (
            cost_micros is not None,
            bool(str(cost_currency or "").strip()),
            bool(str(cost_basis or "").strip()),
        )
        if any(cost_fields_present) and not all(cost_fields_present):
            raise DomainError(
                "QUALITY_MONETARY_COST_INCOMPLETE",
                "cost_micros, cost_currency, and cost_basis must be supplied together or all null",
                422,
            )
        normalized_currency = str(cost_currency or "").strip().upper() or None
        normalized_basis = str(cost_basis or "").strip().lower() or None
        if cost_micros is not None and (
            not isinstance(cost_micros, int)
            or isinstance(cost_micros, bool)
            or cost_micros < 0
            or not re.fullmatch(r"[A-Z]{3}", normalized_currency or "")
            or normalized_basis not in {"estimated", "actual", "billed"}
        ):
            raise DomainError(
                "QUALITY_MONETARY_COST_INVALID",
                "monetary cost requires nonnegative micros, ISO-style currency, and estimated|actual|billed basis",
                422,
            )
        output_text = str(output_text or "")
        artifact_ref = str(artifact_ref or "").strip()
        if not output_text.strip() or not artifact_ref:
            raise DomainError("QUALITY_BENCHMARK_RESULT_INVALID", "output_text and artifact_ref are required", 422)

        existing = self.session.execute(
            select(QualityBenchmarkResult).where(
                QualityBenchmarkResult.run_id == run_id,
                QualityBenchmarkResult.case_id_hash == case.case_id_hash,
            )
        ).scalars().first()
        hashes = {
            "generation_input_hash": _hash_json(expected_payload),
            "generation_prompt_hash": _hash_text(str(actual_prompt_text or "")),
            "output_hash": _hash_text(output_text),
        }
        evidence = {
            **hashes,
            "genre": case.genre,
            "scene_function": case.scene_function,
            "artifact_ref": artifact_ref,
            "prompt_leakage_check": "passed",
            "automated_metrics_json": metrics,
            "cost_tokens": int(cost_tokens) if cost_tokens is not None else None,
            "cost_micros": int(cost_micros) if cost_micros is not None else None,
            "cost_currency": normalized_currency,
            "cost_basis": normalized_basis,
            "latency_ms": int(latency_ms) if latency_ms is not None else None,
        }
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in evidence.items()):
                raise DomainError("QUALITY_BENCHMARK_RESULT_CONFLICT", "case result already differs", 409)
            return existing
        if run.status != "collecting":
            raise DomainError("QUALITY_BENCHMARK_RUN_CLOSED", "completed benchmark runs cannot add cases", 409)
        row = QualityBenchmarkResult(
            result_id=result_id or f"qbench_result_{uuid.uuid4().hex[:16]}",
            run_id=run_id,
            case_id_hash=case.case_id_hash,
            **evidence,
        )
        self.session.add(row)
        run.case_count_recorded += 1
        self.session.flush()
        return row

    def complete_run(self, run_id: str) -> QualityBenchmarkRun:
        run = self.session.get(QualityBenchmarkRun, run_id)
        if run is None:
            raise DomainError("QUALITY_BENCHMARK_RUN_NOT_FOUND", "benchmark run not found", 404)
        actual = len(
            self.session.execute(
                select(QualityBenchmarkResult.result_id).where(QualityBenchmarkResult.run_id == run_id)
            ).all()
        )
        if actual != run.case_count_expected or actual != run.case_count_recorded:
            raise DomainError(
                "QUALITY_BENCHMARK_INCOMPLETE",
                "every frozen hidden case must have exactly one recorded result",
                409,
                details={"expected": run.case_count_expected, "recorded": actual},
            )
        run.status = "completed"
        run.completed_at = utcnow()
        self.session.flush()
        return run

    def record_human_observation(
        self,
        result_id: str,
        *,
        reviewer_ref: str,
        provenance: str,
        source_text: str | None = None,
        edited_text: str | None = None,
        first_usable: bool | None = None,
        follow_read_intent: int | None = None,
        observation_id: str | None = None,
    ) -> QualityValueObservation:
        result = self.session.get(QualityBenchmarkResult, result_id)
        if result is None:
            raise DomainError("QUALITY_BENCHMARK_RESULT_NOT_FOUND", "benchmark result not found", 404)
        reviewer_ref = str(reviewer_ref or "").strip()
        if (
            str(provenance or "").strip().lower() != "human"
            or not reviewer_ref
            or reviewer_ref.lower().startswith(_AUTOMATED_REVIEWER_PREFIXES)
        ):
            raise DomainError(
                "QUALITY_HUMAN_PROVENANCE_REQUIRED",
                "human value observations require explicit human provenance and reviewer_ref",
                422,
            )
        if (source_text is None) != (edited_text is None):
            raise DomainError(
                "QUALITY_EDIT_PAIR_REQUIRED",
                "source_text and edited_text must be supplied together or both omitted",
                422,
            )
        if first_usable is not None and not isinstance(first_usable, bool):
            raise DomainError("QUALITY_FIRST_USABLE_INVALID", "first_usable must be boolean or null", 422)
        if follow_read_intent is not None and (
            not isinstance(follow_read_intent, int)
            or isinstance(follow_read_intent, bool)
            or not 1 <= follow_read_intent <= 5
        ):
            raise DomainError("QUALITY_FOLLOW_READ_INVALID", "follow_read_intent must be 1..5 or null", 422)
        if source_text is None and first_usable is None and follow_read_intent is None:
            raise DomainError("QUALITY_HUMAN_OBSERVATION_EMPTY", "at least one human metric is required", 422)

        source_hash = edited_hash = None
        distance = None
        ratio = None
        if source_text is not None and edited_text is not None:
            source_hash = _hash_text(source_text)
            if source_hash != result.output_hash:
                raise DomainError(
                    "QUALITY_EDIT_SOURCE_MISMATCH",
                    "source_text must be the exact generated result bound by output_hash",
                    409,
                )
            edited_hash = _hash_text(edited_text)
            distance = _levenshtein_distance(source_text, edited_text)
            ratio = round(distance / max(len(source_text), len(edited_text), 1), 6)
        row = QualityValueObservation(
            observation_id=observation_id or f"qvalue_{uuid.uuid4().hex[:16]}",
            result_id=result_id,
            reviewer_ref=reviewer_ref,
            provenance="human",
            source_text_hash=source_hash,
            edited_text_hash=edited_hash,
            human_edit_distance=distance,
            human_edit_distance_ratio=ratio,
            first_usable=first_usable,
            follow_read_intent=int(follow_read_intent) if follow_read_intent is not None else None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def summarize_value_metrics(
        self,
        manifest_id: str,
        *,
        genre: str | None = None,
        scene_function: str | None = None,
        result_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        query = (
            select(QualityBenchmarkResult)
            .join(QualityBenchmarkRun, QualityBenchmarkRun.run_id == QualityBenchmarkResult.run_id)
            .where(
                QualityBenchmarkRun.manifest_id == manifest_id,
                QualityBenchmarkRun.status == "completed",
            )
        )
        if genre is not None:
            query = query.where(QualityBenchmarkResult.genre == genre)
        if scene_function is not None:
            query = query.where(QualityBenchmarkResult.scene_function == scene_function)
        if result_ids is not None:
            normalized_result_ids = sorted({str(value).strip() for value in result_ids if str(value).strip()})
            if not normalized_result_ids:
                return _empty_value_summary(
                    manifest_id,
                    genre=genre,
                    scene_function=scene_function,
                )
            query = query.where(QualityBenchmarkResult.result_id.in_(normalized_result_ids))
        results = list(self.session.execute(query).scalars().all())
        result_ids = [row.result_id for row in results]
        observations = (
            list(
                self.session.execute(
                    select(QualityValueObservation).where(
                        QualityValueObservation.result_id.in_(result_ids),
                        QualityValueObservation.provenance == "human",
                    )
                ).scalars().all()
            )
            if result_ids
            else []
        )
        return {
            "manifest_id": manifest_id,
            "genre": genre,
            "scene_function": scene_function,
            "total_result_n": len(results),
            "human_observation_n": len(observations),
            "human_edit_distance": _metric_summary(
                observations,
                "human_edit_distance_ratio",
                total_results=len(results),
            ),
            "first_usable": _boolean_summary(
                observations,
                "first_usable",
                total_results=len(results),
            ),
            "follow_read_intent": _metric_summary(
                observations,
                "follow_read_intent",
                total_results=len(results),
            ),
            "cost_tokens": _result_metric_summary(results, "cost_tokens"),
            "monetary_cost": _monetary_cost_summary(results),
            "latency_ms": _result_metric_summary(results, "latency_ms"),
        }


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _assert_optional_nonnegative_int(value: Any, *, field: str, code: str) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise DomainError(code, f"{field} must be a nonnegative integer or null", 422)


def _metric_summary(
    rows: list[QualityValueObservation],
    field: str,
    *,
    total_results: int,
) -> dict[str, Any]:
    observed = [row for row in rows if getattr(row, field) is not None]
    distinct_results = {row.result_id for row in observed}
    values_by_result: dict[str, list[float]] = {}
    for row in observed:
        values_by_result.setdefault(row.result_id, []).append(float(getattr(row, field)))
    values = [mean(per_result) for per_result in values_by_result.values()]
    return {
        "observed_observation_n": len(observed),
        "observed_result_n": len(distinct_results),
        "missing_result_n": max(0, total_results - len(distinct_results)),
        "mean": round(mean(values), 6) if values else None,
    }


def _boolean_summary(
    rows: list[QualityValueObservation],
    field: str,
    *,
    total_results: int,
) -> dict[str, Any]:
    observed = [row for row in rows if getattr(row, field) is not None]
    distinct_results = {row.result_id for row in observed}
    positives = sum(1 for row in observed if getattr(row, field) is True)
    values_by_result: dict[str, list[float]] = {}
    for row in observed:
        values_by_result.setdefault(row.result_id, []).append(1.0 if getattr(row, field) is True else 0.0)
    per_result_rates = [mean(values) for values in values_by_result.values()]
    return {
        "observed_observation_n": len(observed),
        "observed_result_n": len(distinct_results),
        "missing_result_n": max(0, total_results - len(distinct_results)),
        "positive_n": positives,
        "rate": round(mean(per_result_rates), 6) if per_result_rates else None,
    }


def _result_metric_summary(rows: list[QualityBenchmarkResult], field: str) -> dict[str, Any]:
    values = [float(getattr(row, field)) for row in rows if getattr(row, field) is not None]
    return {
        "observed_result_n": len(values),
        "missing_result_n": len(rows) - len(values),
        "mean": round(mean(values), 6) if values else None,
        "total": round(sum(values), 6) if values else None,
    }


def _monetary_cost_summary(rows: list[QualityBenchmarkResult]) -> dict[str, Any]:
    observed = [row for row in rows if row.cost_micros is not None]
    buckets: dict[tuple[str, str], list[int]] = {}
    for row in observed:
        buckets.setdefault((str(row.cost_currency), str(row.cost_basis)), []).append(int(row.cost_micros))
    return {
        "observed_result_n": len(observed),
        "missing_result_n": len(rows) - len(observed),
        "by_currency_basis": [
            {
                "currency": currency,
                "basis": basis,
                "observed_result_n": len(values),
                "total_micros": sum(values),
                "mean_micros": round(mean(values), 6),
            }
            for (currency, basis), values in sorted(buckets.items())
        ],
    }


def _empty_value_summary(
    manifest_id: str,
    *,
    genre: str | None,
    scene_function: str | None,
) -> dict[str, Any]:
    metric = {
        "observed_observation_n": 0,
        "observed_result_n": 0,
        "missing_result_n": 0,
        "mean": None,
    }
    return {
        "manifest_id": manifest_id,
        "genre": genre,
        "scene_function": scene_function,
        "total_result_n": 0,
        "human_observation_n": 0,
        "human_edit_distance": dict(metric),
        "first_usable": {
            "observed_observation_n": 0,
            "observed_result_n": 0,
            "missing_result_n": 0,
            "positive_n": 0,
            "rate": None,
        },
        "follow_read_intent": dict(metric),
        "cost_tokens": {"observed_result_n": 0, "missing_result_n": 0, "mean": None, "total": None},
        "monetary_cost": {"observed_result_n": 0, "missing_result_n": 0, "by_currency_basis": []},
        "latency_ms": {"observed_result_n": 0, "missing_result_n": 0, "mean": None, "total": None},
    }
