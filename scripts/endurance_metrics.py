"""Fail-closed evaluator for a real-model, 30-chapter endurance run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from typing import Any

ENDURANCE_SCHEMA = "endurance-report-v2"
MANIFEST_SCHEMA = "endurance-run-manifest-v1"
TOKENS_RATIO_CAP = 1.5
P95_CAP_MS = 2000
READ_ENDPOINTS = ("catalog", "scene_state", "chapter_manuscript")
LATENCY_SERIES = READ_ENDPOINTS + ("scene_generation", "candidate_selection", "archive", "chapter_aggregation")
RESTART_CHECKPOINTS = (5, 10, 20, 30)
DB_SAMPLE_CHECKPOINTS = (5, 10, 15, 20, 25, 30)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _non_negative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _non_negative_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _chapter_index(chapter: Any) -> int:
    value = chapter.get("chapter_index") if isinstance(chapter, dict) else None
    return value if type(value) is int else 0


def _archived_scene_tokens(chapters: list[dict[str, Any]]) -> tuple[int, int]:
    scenes = 0
    tokens = 0
    for chapter in chapters:
        for scene in chapter.get("scenes") or []:
            if scene.get("archived") is True and _positive_int(scene.get("tokens")):
                scenes += 1
                tokens += scene["tokens"]
    return scenes, tokens


def tokens_per_archived_scene(chapters: list[dict[str, Any]]) -> float | None:
    scenes, tokens = _archived_scene_tokens(chapters)
    return tokens / scenes if scenes else None


def _count_high(chapters: list[dict[str, Any]], key: str, *, require_unresolved: bool = False) -> int:
    total = 0
    for chapter in chapters:
        for item in chapter.get(key) or []:
            if not isinstance(item, dict) or str(item.get("severity") or "").lower() != "high":
                continue
            if require_unresolved and item.get("resolved") is True:
                continue
            total += 1
    return total


def bucket_by_five(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(chapters, key=_chapter_index)
    buckets: list[dict[str, Any]] = []
    for start in range(0, len(ordered), 5):
        window = ordered[start : start + 5]
        if not window:
            continue
        scenes, tokens = _archived_scene_tokens(window)
        buckets.append({
            "chapters": [_chapter_index(chapter) for chapter in window],
            "archived_scene_count": scenes,
            "tokens_per_archived_scene": tokens / scenes if scenes else None,
            "continuity_errors": sum(
                chapter.get("continuity_errors", 0)
                for chapter in window
                if _non_negative_int(chapter.get("continuity_errors"))
            ),
            "foreshadow_debt": sum(
                chapter.get("foreshadow_debt", 0)
                for chapter in window
                if _non_negative_int(chapter.get("foreshadow_debt"))
            ),
            "high_voice_drift_unresolved": _count_high(window, "voice_drift", require_unresolved=True),
            "high_cross_chapter_repetition": _count_high(window, "cross_chapter_repetition"),
        })
    return buckets


def stratify_by_model(chapters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for chapter in chapters:
        model = str(chapter.get("model") or "unknown")
        row = output.setdefault(model, {
            "chapter_count": 0,
            "high_voice_drift_unresolved": 0,
            "high_cross_chapter_repetition": 0,
        })
        row["chapter_count"] += 1
        row["high_voice_drift_unresolved"] += _count_high([chapter], "voice_drift", require_unresolved=True)
        row["high_cross_chapter_repetition"] += _count_high([chapter], "cross_chapter_repetition")
    return output


def _percentile95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _failure(failures: list[str], code: str, detail: str | None = None) -> None:
    failures.append(f"{code}: {detail}" if detail else code)


def evaluate_endurance(report: dict[str, Any], *, total_chapters: int = 30) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(report, dict) or report.get("schema") != ENDURANCE_SCHEMA:
        _failure(failures, "ENDURANCE_SCHEMA_UNSUPPORTED", f"only {ENDURANCE_SCHEMA} can pass")
        return {
            "passed": False,
            "failures": failures,
            "total_chapters_expected": total_chapters,
            "chapters_archived": 0,
            "buckets": [],
            "by_model": {},
        }

    chapters = report.get("chapters") if isinstance(report.get("chapters"), list) else []
    indexes = [chapter.get("chapter_index") for chapter in chapters if isinstance(chapter, dict)]
    if indexes != list(range(1, total_chapters + 1)) or len(chapters) != total_chapters:
        _failure(failures, "CHAPTER_INDEX_SET_INVALID", f"expected exactly ordered 1..{total_chapters}")
    chapter_ids: list[str] = []
    scene_ids: list[str] = []
    archived_count = 0
    scene_token_total = 0
    scene_cost_total = 0.0
    for position, chapter in enumerate(chapters, 1):
        if not isinstance(chapter, dict):
            _failure(failures, "CHAPTER_RECORD_INVALID", str(position))
            continue
        chapter_id = str(chapter.get("chapter_id") or "").strip()
        if not chapter_id or chapter_id in chapter_ids:
            _failure(failures, "CHAPTER_ID_INVALID", str(position))
        chapter_ids.append(chapter_id)
        content = chapter.get("final_content")
        if (
            chapter.get("archived") is not True
            or not isinstance(content, str)
            or not content.strip()
            or chapter.get("final_content_sha256") != text_sha256(content or "")
            or not str(chapter.get("model") or "").strip()
        ):
            _failure(failures, "CHAPTER_ARCHIVE_INVALID", chapter_id or str(position))
        else:
            archived_count += 1
        for field in ("continuity_errors", "q0_q1_unresolved", "source_leak", "foreshadow_debt"):
            if not _non_negative_int(chapter.get(field)):
                _failure(failures, "CHAPTER_METRIC_MISSING", f"{chapter_id}.{field}")
        for field in ("voice_drift", "cross_chapter_repetition"):
            if not isinstance(chapter.get(field), list):
                _failure(failures, "CHAPTER_METRIC_MISSING", f"{chapter_id}.{field}")
        scenes = chapter.get("scenes") if isinstance(chapter.get("scenes"), list) else []
        if not scenes:
            _failure(failures, "SCENE_ARCHIVE_INCOMPLETE", f"{chapter_id}: empty")
        for scene in scenes:
            if not isinstance(scene, dict):
                _failure(failures, "SCENE_RECORD_INVALID", chapter_id)
                continue
            scene_id = str(scene.get("scene_id") or "").strip()
            final_text = scene.get("final_text")
            valid = (
                scene_id
                and scene_id not in scene_ids
                and scene.get("chapter_id") == chapter_id
                and scene.get("archived") is True
                and isinstance(final_text, str)
                and bool(final_text.strip())
                and scene.get("final_text_sha256") == text_sha256(final_text or "")
                and _positive_int(scene.get("tokens"))
                and _non_negative_number(scene.get("duration_ms"))
                and scene.get("duration_ms") > 0
                and _positive_int(scene.get("attempt_count"))
                and _non_negative_number(scene.get("cost"))
            )
            if not valid:
                _failure(failures, "SCENE_ARCHIVE_INCOMPLETE", scene_id or chapter_id)
            scene_ids.append(scene_id)
            if _positive_int(scene.get("tokens")):
                scene_token_total += scene["tokens"]
            if _non_negative_number(scene.get("cost")):
                scene_cost_total += float(scene["cost"])

    if len(set(chapter_ids)) != total_chapters:
        _failure(failures, "CHAPTER_ID_SET_INVALID")
    if sum(
        chapter.get("continuity_errors", 0)
        for chapter in chapters
        if isinstance(chapter, dict) and _non_negative_int(chapter.get("continuity_errors"))
    ):
        _failure(failures, "CONTINUITY_ERRORS_PRESENT")
    q0q1 = sum(
        chapter.get("q0_q1_unresolved", 0)
        for chapter in chapters
        if isinstance(chapter, dict) and _non_negative_int(chapter.get("q0_q1_unresolved"))
    )
    leaks = sum(
        chapter.get("source_leak", 0)
        for chapter in chapters
        if isinstance(chapter, dict) and _non_negative_int(chapter.get("source_leak"))
    )
    if q0q1:
        _failure(failures, "Q0_Q1_UNRESOLVED", str(q0q1))
    if leaks:
        _failure(failures, "SOURCE_LEAK", str(leaks))
    drift = _count_high(chapters, "voice_drift", require_unresolved=True)
    repetition = _count_high(chapters, "cross_chapter_repetition")
    if drift:
        _failure(failures, "HIGH_VOICE_DRIFT_UNRESOLVED", str(drift))
    if repetition:
        _failure(failures, "HIGH_CROSS_CHAPTER_REPETITION", str(repetition))

    early = tokens_per_archived_scene([chapter for chapter in chapters if 1 <= _chapter_index(chapter) <= 10])
    late = tokens_per_archived_scene([chapter for chapter in chapters if 21 <= _chapter_index(chapter) <= 30])
    ratio = late / early if early and late else None
    if ratio is None:
        _failure(failures, "TOKENS_PER_SCENE_UNCOMPUTABLE")
    elif ratio > TOKENS_RATIO_CAP:
        _failure(failures, "TOKENS_PER_SCENE_REGRESSION", f"ratio={ratio:.4f}")

    evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
    manifest = evidence.get("manifest") if isinstance(evidence.get("manifest"), dict) else {}
    if evidence.get("provenance") != "real_model" or manifest.get("provenance") != "real_model":
        _failure(failures, "EVIDENCE_PROVENANCE_NOT_REAL_MODEL")
    if (
        manifest.get("schema") != MANIFEST_SCHEMA
        or evidence.get("manifest_hash") != canonical_sha256(manifest)
        or not str(evidence.get("run_id") or "").strip()
        or manifest.get("run_id") != evidence.get("run_id")
        or manifest.get("chapter_ids") != chapter_ids
        or manifest.get("scene_ids") != scene_ids
    ):
        _failure(failures, "RUN_MANIFEST_INVALID")
    calls = manifest.get("model_calls") if isinstance(manifest.get("model_calls"), list) else []
    call_scene_ids = [str(call.get("scene_id") or "") for call in calls if isinstance(call, dict)]
    call_ids = [str(call.get("llm_call_id") or "") for call in calls if isinstance(call, dict)]
    call_tokens = 0
    calls_valid = len(calls) == len(scene_ids) and call_scene_ids == scene_ids and len(set(call_ids)) == len(calls)
    for call in calls:
        if not isinstance(call, dict):
            calls_valid = False
            continue
        if (
            not str(call.get("llm_call_id") or "").strip()
            or not str(call.get("provider") or "").strip()
            or call.get("provider") == "offline_deterministic"
            or not str(call.get("model") or "").strip()
            or not str(call.get("prompt_hash") or "").strip()
            or not _positive_int(call.get("total_tokens"))
            or not _non_negative_number(call.get("latency_ms"))
            or call.get("error_code") not in (None, "")
            or not str(call.get("created_at") or "").strip()
        ):
            calls_valid = False
        if _positive_int(call.get("total_tokens")):
            call_tokens += call["total_tokens"]
    if not calls_valid or manifest.get("offline_deterministic_required_count") != 0:
        _failure(failures, "MODEL_CALL_MANIFEST_INVALID")

    cost = report.get("cost_summary") if isinstance(report.get("cost_summary"), dict) else {}
    cost_valid = (
        _positive_int(cost.get("total_tokens"))
        and _non_negative_number(cost.get("total_cost"))
        and _positive_int(cost.get("call_count"))
        and bool(str(cost.get("currency") or "").strip())
        and type(cost.get("is_estimate")) is bool
        and cost.get("archived_scene_count") == len(scene_ids)
        and cost.get("archived_chapter_count") == total_chapters
        and cost.get("call_count") == len(calls)
        and cost.get("total_tokens") == call_tokens
        and abs(float(cost.get("total_cost", -1)) - scene_cost_total) < 1e-6
        and manifest.get("cost_summary") == cost
    )
    if not cost_valid:
        _failure(failures, "COST_EVIDENCE_INVALID")

    raw_latency = report.get("latency_samples_ms") if isinstance(report.get("latency_samples_ms"), dict) else {}
    claimed_p95 = report.get("latency_p95_ms") if isinstance(report.get("latency_p95_ms"), dict) else {}
    computed_p95: dict[str, float] = {}
    for series in LATENCY_SERIES:
        samples = raw_latency.get(series)
        if not isinstance(samples, list) or len(samples) < 5 or any(
            not _non_negative_number(value) or value <= 0 for value in samples
        ):
            _failure(failures, "LATENCY_SAMPLES_MISSING", series)
            continue
        computed = _percentile95([float(value) for value in samples])
        computed_p95[series] = computed
        claimed = claimed_p95.get(series)
        if not _non_negative_number(claimed) or abs(float(claimed) - computed) > 1e-6:
            _failure(failures, "P95_NOT_RECOMPUTABLE", series)
        if series in READ_ENDPOINTS and computed >= P95_CAP_MS:
            _failure(failures, "P95_TOO_SLOW", f"{series}={computed}ms")

    restarts = report.get("restart_checks") if isinstance(report.get("restart_checks"), list) else []
    restart_points = [row.get("after_chapter") for row in restarts if isinstance(row, dict)]
    required_restarts = [point for point in RESTART_CHECKPOINTS if point <= total_chapters]
    if restart_points != required_restarts:
        _failure(failures, "RESTART_CHECKS_MISSING", str(required_restarts))
    for row in restarts:
        if not isinstance(row, dict):
            _failure(failures, "RESTART_CHECK_INVALID")
            continue
        before_state = row.get("before_state")
        after_state = row.get("after_state")
        states_complete = all(
            isinstance(state, dict) and all(key in state for key in ("catalog", "finals", "selections", "aggregates"))
            for state in (before_state, after_state)
        )
        before_hash = canonical_sha256(before_state) if isinstance(before_state, dict) else None
        after_hash = canonical_sha256(after_state) if isinstance(after_state, dict) else None
        if (
            row.get("performed") is not True
            or row.get("health_verified") is not True
            or not states_complete
            or row.get("before_state_sha256") != before_hash
            or row.get("after_state_sha256") != after_hash
            or before_hash != after_hash
            or not str(row.get("before_pid") or "").strip()
            or not str(row.get("after_pid") or "").strip()
            or str(row.get("before_pid")) == str(row.get("after_pid"))
        ):
            _failure(failures, "RESTART_CHECK_INVALID", str(row.get("after_chapter")))

    db_rows = report.get("db_size_samples") if isinstance(report.get("db_size_samples"), list) else []
    db_points = [row.get("after_chapter") for row in db_rows if isinstance(row, dict)]
    required_db = [point for point in DB_SAMPLE_CHECKPOINTS if point <= total_chapters]
    if db_points != required_db:
        _failure(failures, "DB_SIZE_SAMPLES_MISSING", str(required_db))
    for row in db_rows:
        if not isinstance(row, dict) or not (
            _positive_int(row.get("bytes"))
            and bool(str(row.get("path") or "").strip())
            and _valid_hash(row.get("file_sha256"))
            and bool(str(row.get("measured_at") or "").strip())
        ):
            _failure(failures, "DB_SIZE_SAMPLE_INVALID", str(row.get("after_chapter") if isinstance(row, dict) else "?"))

    fk = report.get("foreign_key_audit") if isinstance(report.get("foreign_key_audit"), dict) else {}
    raw_audit = fk.get("raw_audit")
    if not isinstance(raw_audit, dict) or fk.get("raw_audit_sha256") != canonical_sha256(raw_audit):
        _failure(failures, "FK_AUDIT_HASH_INVALID")
    if fk.get("orphan_count") != 0:
        _failure(failures, "FK_ORPHAN_AUDIT_NOT_CLEAN")
    if fk.get("decision") == "enable":
        if fk.get("pragma_foreign_keys") != 1:
            _failure(failures, "FK_ENABLE_DECISION_NOT_APPLIED")
    elif fk.get("decision") == "defer_with_rationale":
        if not str(fk.get("rationale") or "").strip():
            _failure(failures, "FK_DEFERRAL_RATIONALE_MISSING")
    else:
        _failure(failures, "FK_DECISION_MISSING")

    return {
        "passed": not failures,
        "failures": failures,
        "total_chapters_expected": total_chapters,
        "chapters_archived": archived_count,
        "evidence_provenance": evidence.get("provenance"),
        "run_id": evidence.get("run_id"),
        "tokens_ratio_21_30_vs_1_10": ratio,
        "latency_p95_ms_recomputed": computed_p95,
        "buckets": bucket_by_five(chapters),
        "by_model": stratify_by_model(chapters),
        "restart_checks": restarts,
        "db_size_samples": db_rows,
        "foreign_key_audit": fk,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a v2 real-model endurance evidence report")
    parser.add_argument("report")
    parser.add_argument("--total-chapters", type=int, default=30)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    with open(args.report, encoding="utf-8") as handle:
        report = json.load(handle)
    verdict = evaluate_endurance(report, total_chapters=args.total_chapters)
    text = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(text)
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
