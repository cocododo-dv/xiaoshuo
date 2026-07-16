from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[2] / "scripts" / "endurance_metrics.py"
    spec = importlib.util.spec_from_file_location("endurance_metrics", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


em = _load()


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _text_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _clean_report(tokens_early=1000, tokens_late=1000):
    chapters = []
    calls = []
    chapter_ids = []
    scene_ids = []
    total_tokens = 0
    total_cost = 0.0
    for index in range(1, 31):
        chapter_id = f"CH{index:02d}"
        scene_id = f"{chapter_id}_SC01"
        chapter_ids.append(chapter_id)
        scene_ids.append(scene_id)
        tokens = tokens_early if index <= 10 else tokens_late if index >= 21 else 1000
        text = f"authoritative final scene {scene_id}"
        content = f"authoritative chapter {chapter_id}\n{text}"
        cost = round(tokens / 100000, 6)
        total_tokens += tokens
        total_cost += cost
        chapters.append({
            "chapter_index": index,
            "chapter_id": chapter_id,
            "model": "gpt-test",
            "archived": True,
            "final_content": content,
            "final_content_sha256": _text_hash(content),
            "scenes": [{
                "scene_id": scene_id,
                "chapter_id": chapter_id,
                "archived": True,
                "final_text": text,
                "final_text_sha256": _text_hash(text),
                "tokens": tokens,
                "duration_ms": 1500,
                "attempt_count": 1,
                "cost": cost,
            }],
            "continuity_errors": 0,
            "q0_q1_unresolved": 0,
            "source_leak": 0,
            "foreshadow_debt": 0,
            "voice_drift": [],
            "cross_chapter_repetition": [],
        })
        calls.append({
            "scene_id": scene_id,
            "llm_call_id": f"call-{scene_id}",
            "provider": "openai",
            "model": "gpt-test",
            "prompt_hash": f"prompt-{scene_id}",
            "total_tokens": tokens,
            "latency_ms": 1000,
            "error_code": None,
            "created_at": "2026-07-15T00:00:00Z",
        })
    cost_summary = {
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "currency": "USD",
        "call_count": 30,
        "is_estimate": True,
        "archived_scene_count": 30,
        "archived_chapter_count": 30,
    }
    manifest = {
        "schema": "endurance-run-manifest-v1",
        "provenance": "real_model",
        "run_id": "endurance-run-1",
        "chapter_ids": chapter_ids,
        "scene_ids": scene_ids,
        "model_calls": calls,
        "offline_deterministic_required_count": 0,
        "cost_summary": cost_summary,
    }
    restarts = []
    for checkpoint in (5, 10, 20, 30):
        state = {
            "catalog": {"through_chapter": checkpoint},
            "finals": scene_ids[:checkpoint],
            "selections": [{"scene_id": item} for item in scene_ids[:checkpoint]],
            "aggregates": chapter_ids[:checkpoint],
        }
        restarts.append({
            "after_chapter": checkpoint,
            "performed": True,
            "health_verified": True,
            "before_pid": str(100 + checkpoint),
            "after_pid": str(200 + checkpoint),
            "before_state": copy.deepcopy(state),
            "after_state": copy.deepcopy(state),
            "before_state_sha256": _hash(state),
            "after_state_sha256": _hash(state),
        })
    samples = {name: [600, 700, 800, 900, 1000] for name in em.LATENCY_SERIES}
    raw_fk = {"tables_checked": ["chapters", "scenes", "final_scenes"], "orphans": []}
    return {
        "schema": "endurance-report-v2",
        "evidence": {
            "provenance": "real_model",
            "run_id": "endurance-run-1",
            "manifest": manifest,
            "manifest_hash": _hash(manifest),
        },
        "chapters": chapters,
        "cost_summary": cost_summary,
        "latency_samples_ms": samples,
        "latency_p95_ms": {name: 1000 for name in em.LATENCY_SERIES},
        "restart_checks": restarts,
        "db_size_samples": [{
            "after_chapter": checkpoint,
            "path": "author.db",
            "bytes": checkpoint * 1000000,
            "file_sha256": f"{checkpoint:064x}",
            "measured_at": "2026-07-15T00:00:00Z",
        } for checkpoint in (5, 10, 15, 20, 25, 30)],
        "foreign_key_audit": {
            "decision": "enable",
            "pragma_foreign_keys": 1,
            "orphan_count": 0,
            "raw_audit": raw_fk,
            "raw_audit_sha256": _hash(raw_fk),
        },
    }


def _codes(verdict):
    return {item.split(":", 1)[0] for item in verdict["failures"]}


def test_clean_30_chapter_report_passes():
    verdict = em.evaluate_endurance(_clean_report())
    assert verdict["passed"] is True, verdict["failures"]
    assert verdict["chapters_archived"] == 30


def test_empty_and_old_schema_reports_cannot_pass():
    assert "ENDURANCE_SCHEMA_UNSUPPORTED" in _codes(em.evaluate_endurance({}))
    report = _clean_report()
    report["schema"] = "endurance-report-v1"
    assert "ENDURANCE_SCHEMA_UNSUPPORTED" in _codes(em.evaluate_endurance(report))


def test_manifest_hash_is_computed_not_self_asserted():
    report = _clean_report()
    report["evidence"]["manifest"]["run_id"] = "forged"
    assert "RUN_MANIFEST_INVALID" in _codes(em.evaluate_endurance(report))


def test_restart_boolean_claims_without_raw_hashes_cannot_pass():
    report = _clean_report()
    report["restart_checks"][0] = {"after_chapter": 5, "verified": True, "state_hash_match": True}
    assert "RESTART_CHECK_INVALID" in _codes(em.evaluate_endurance(report))


def test_tampered_archived_content_and_missing_metrics_fail():
    report = _clean_report()
    report["chapters"][0]["final_content"] = "tampered"
    report["chapters"][1]["scenes"][0]["final_text"] = "tampered"
    report["chapters"][2].pop("foreshadow_debt")
    codes = _codes(em.evaluate_endurance(report))
    assert "CHAPTER_ARCHIVE_INVALID" in codes
    assert "SCENE_ARCHIVE_INCOMPLETE" in codes
    assert "CHAPTER_METRIC_MISSING" in codes


def test_token_regression_fails():
    verdict = em.evaluate_endurance(_clean_report(tokens_early=1000, tokens_late=2000))
    assert "TOKENS_PER_SCENE_REGRESSION" in _codes(verdict)
    assert verdict["tokens_ratio_21_30_vs_1_10"] == pytest.approx(2.0)


def test_quality_failures_are_explicit():
    report = _clean_report()
    report["chapters"][0]["continuity_errors"] = 1
    report["chapters"][1]["q0_q1_unresolved"] = 1
    report["chapters"][2]["source_leak"] = 1
    report["chapters"][3]["voice_drift"] = [{"severity": "high", "resolved": False}]
    report["chapters"][4]["cross_chapter_repetition"] = [{"severity": "high"}]
    codes = _codes(em.evaluate_endurance(report))
    assert {"CONTINUITY_ERRORS_PRESENT", "Q0_Q1_UNRESOLVED", "SOURCE_LEAK",
            "HIGH_VOICE_DRIFT_UNRESOLVED", "HIGH_CROSS_CHAPTER_REPETITION"} <= codes


def test_latency_requires_raw_recomputable_samples():
    report = _clean_report()
    report["latency_samples_ms"]["catalog"] = []
    report["latency_p95_ms"]["scene_state"] = 1
    codes = _codes(em.evaluate_endurance(report))
    assert "LATENCY_SAMPLES_MISSING" in codes
    assert "P95_NOT_RECOMPUTABLE" in codes


def test_db_fk_and_cost_evidence_fail_closed():
    report = _clean_report()
    report["db_size_samples"] = []
    report["foreign_key_audit"]["raw_audit_sha256"] = "self-asserted"
    report["cost_summary"]["total_tokens"] = 1
    codes = _codes(em.evaluate_endurance(report))
    assert "DB_SIZE_SAMPLES_MISSING" in codes
    assert "FK_AUDIT_HASH_INVALID" in codes
    assert "COST_EVIDENCE_INVALID" in codes


def test_bucket_and_model_stratification_remain_diagnostic():
    report = _clean_report()
    assert len(em.bucket_by_five(report["chapters"])) == 6
    assert em.stratify_by_model(report["chapters"])["gpt-test"]["chapter_count"] == 30
