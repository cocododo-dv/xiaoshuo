from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path


def _load_summary_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "playwright_audit_summary.py"
    spec = importlib.util.spec_from_file_location("playwright_audit_summary", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load_summary_module()


def _canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _text_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def test_playwright_audit_summary_writes_utf8_markdown(tmp_path) -> None:
    artifact_dir = tmp_path / ".playwright-cli"
    artifact_dir.mkdir()
    (artifact_dir / "page-1.yml").write_text('- heading "Reference Learning"\n', encoding="utf-8")
    (artifact_dir / "console-1.log").write_text("[error] Failed to fetch\n", encoding="utf-8")
    (artifact_dir / "reference-export.md").write_text("# export\n", encoding="utf-8")
    output = tmp_path / "audit.md"
    summary = MODULE.build_summary(artifact_dir, output)
    assert summary["snapshot_count"] == 1
    assert summary["console_issue_count"] == 1
    assert summary["download_count"] == 1
    assert output.read_text(encoding="utf-8").startswith("# Playwright")


def test_playwright_audit_summary_defaults_to_tracked_report() -> None:
    assert MODULE.DEFAULT_OUTPUT == Path("docs/reports/playwright-audit-summary.md")


PHASE_COUNTS = {
    "snowflake_planning": {"step-save": 10, "step-approve": 10},
    "materialization": {"materialize": 1, "outline-approve": 1},
    "scene_execution": {"run-job-create": 15},
    "candidate_selection": {"candidate-select": 3, "selection-resume": 3},
    "archive": {"adopt-current": 15},
    "chapter_aggregation": {"final-aggregate": 5},
}


def _request(requirement_id, index):
    paths = {
        "step-save": f"/api/v2/projects/P1/snowflake-workspace/steps/{index}",
        "step-approve": f"/api/v2/projects/P1/snowflake-workspace/steps/{index}/approve",
        "materialize": "/api/v2/projects/P1/snowflake-workspace/materialize",
        "outline-approve": "/api/v2/projects/P1/snowflake-workspace/outline/approve",
        "run-job-create": f"/api/v1/scenes/S{index}/run/jobs",
        "candidate-select": f"/api/v1/scenes/S{index}/style-candidates/C{index}/select",
        "selection-resume": f"/api/v1/scenes/S{index}/resume-after-selection",
        "adopt-current": f"/api/v1/scenes/S{index}/adopt-current",
        "final-aggregate": f"/api/v1/chapters/C{index}/runtime/aggregate/final",
    }
    methods = {"step-save": "PATCH"}
    return {
        "requirement_id": requirement_id,
        "method": methods.get(requirement_id, "POST"),
        "url": f"http://127.0.0.1:8001{paths[requirement_id]}",
        "status": 200,
        "resource_type": "fetch",
    }


def _phase_receipts():
    phases = []
    for phase, required in PHASE_COUNTS.items():
        requests = []
        requirements = []
        for requirement_id, count in required.items():
            requests.extend(_request(requirement_id, i + 1) for i in range(count))
            requirements.append({"id": requirement_id, "method": requests[-1]["method"], "min": count, "matched": count})
        phases.append({
            "phase": phase,
            "lane": "ui",
            "interaction_count": max(1, sum(required.values())),
            "requirements": requirements,
            "requests": requests,
            "evidence": f"browser receipt for {phase}",
        })
    return phases


def _clean_report():
    planned = []
    scenes = {}
    aggregates = {}
    calls = []
    catalog = {"chapters": []}
    recovery_scenes = {}
    recovery_aggregates = {}
    for chapter_number in range(1, 6):
        chapter_id = f"CH{chapter_number:02d}"
        chapter_scene_ids = []
        chapter_texts = []
        for scene_number in range(1, 4):
            scene_id = f"{chapter_id}_SC{scene_number:02d}"
            text = f"authoritative final text for {scene_id}"
            planned.append({"chapter_id": chapter_id, "scene_id": scene_id})
            chapter_scene_ids.append(scene_id)
            chapter_texts.append(text)
            call = {
                "scene_id": scene_id,
                "llm_call_id": f"call-{scene_id}",
                "provider": "openai",
                "model": "gpt-test",
                "prompt_hash": f"prompt-{scene_id}",
                "prompt_tokens": 700,
                "completion_tokens": 300,
                "total_tokens": 1000,
                "latency_ms": 1200,
                "finish_reason": "stop",
                "error_code": None,
                "created_at": "2026-07-15T00:00:00Z",
            }
            calls.append(call)
            scenes[scene_id] = {
                "chapter_id": chapter_id,
                "final_row_id": f"final-{scene_id}",
                "final_text": text,
                "final_chars": len(text),
                "final_text_sha256": _text_hash(text),
                "authority": {"object_type": "FinalScene", "row_id": f"final-{scene_id}", "status": "archived"},
                "archived": True,
                "scene_status": "archived",
                "tokens": 1000,
                "duration_ms": 2500,
                "attempt_count": 1,
                "attempt_evidence": [{"attempt_no": 1, "status": "archived"}],
                "block_reason": None,
                "source_safety": {"safe": True, "blocked_terms": [], "risks": [], "source_profile_ids": ["profile-1"]},
                "q0_q1_unresolved": 0,
                "model_call": call,
            }
            recovery_scenes[scene_id] = {
                "final_text": text,
                "final_text_sha256": _text_hash(text),
                "final_row_id": f"final-{scene_id}",
            }
        content = "\n".join(chapter_texts)
        aggregates[chapter_id] = {
            "chapter_id": chapter_id,
            "completion_status": "complete",
            "authority_source": "chapter_manuscript",
            "scene_ids": chapter_scene_ids,
            "content": content,
            "content_sha256": _text_hash(content),
        }
        recovery_aggregates[chapter_id] = {
            "content": content,
            "content_sha256": _text_hash(content),
            "scene_ids": chapter_scene_ids,
        }
        catalog["chapters"].append({"chapter_id": chapter_id, "scene_ids": chapter_scene_ids})
    candidate_events = [
        {"scene_id": planned[i]["scene_id"], "selected_row_id": f"candidate-{i}"}
        for i in range(3)
    ]
    selections = copy.deepcopy(candidate_events)
    recovery_raw = {
        "catalog": catalog,
        "scenes": recovery_scenes,
        "selections": selections,
        "aggregates": recovery_aggregates,
    }
    hashes = {
        "catalog_sha256": _canonical_hash(catalog),
        "content_sha256": _canonical_hash(recovery_scenes),
        "selection_sha256": _canonical_hash(selections),
        "aggregate_sha256": _canonical_hash(recovery_aggregates),
        "state_sha256": _canonical_hash(recovery_raw),
    }
    snapshot = {**recovery_raw, "hashes": hashes}
    recovery = {
        "schema": "five-chapter-recovery-v1",
        "cache_clear": {
            "performed": True,
            "local_storage_cleared": True,
            "session_storage_cleared": True,
            "cookies_cleared": True,
            "cache_storage_cleared": True,
        },
        "backend_restart": {
            "performed": True, "health_verified": True,
            "before_pid": "100", "after_pid": "200", "pid_changed": True,
        },
        "before": copy.deepcopy(snapshot),
        "after": copy.deepcopy(snapshot),
    }
    cost = {
        "total_tokens": 15000, "total_cost": 2.5, "call_count": 15,
        "currency": "USD", "is_estimate": True,
        "archived_scene_count": 15, "archived_chapter_count": 5,
    }
    manifest = {
        "schema": "five-chapter-run-manifest-v1",
        "provenance": "real_model",
        "run_id": "run-1", "project_id": "P1", "lane_id": "public-domain-five-chapter",
        "reference_source_basis": "public_domain",
        "expected": {"chapters": 5, "scenes_per_chapter": 3},
        "planned_scene_ids": [item["scene_id"] for item in planned],
        "model_calls": calls,
        "offline_deterministic_required_count": 0,
        "cost_summary": cost,
        "candidate_events_sha256": _canonical_hash(candidate_events),
        "recovery_state_sha256": hashes["state_sha256"],
    }
    return {
        "outcome": {
            "schema": "outcome-gate-v2",
            "expected": {"chapters": 5, "scenes_per_chapter": 3},
            "planned_scenes": planned,
            "scenes": scenes,
            "chapter_aggregates": aggregates,
            "candidate_selection": {"count": 3, "events": candidate_events, "events_sha256": _canonical_hash(candidate_events)},
            "northstar_phases": _phase_receipts(),
            "recovery": recovery,
            "run": {
                "provenance": "real_model", "run_id": "run-1", "project_id": "P1",
                "started_at": "2026-07-15T00:00:00Z", "finished_at": "2026-07-15T01:00:00Z",
                "manifest": manifest, "manifest_hash": _canonical_hash(manifest),
            },
        },
        "chapterScores": {},
    }


def _codes(verdict):
    return {failure["code"] for failure in verdict["failures"]}


def test_outcome_gate_passes_recomputable_v2_evidence():
    verdict = MODULE.evaluate_outcome_gate(_clean_report())
    assert verdict["passed"] is True, verdict["failures"]
    assert verdict["stats"]["archived_scenes"] == 15
    assert verdict["stats"]["aggregated_chapters"] == 5


def test_old_schema_and_empty_report_cannot_pass():
    assert "LEGACY_REPORT_NO_OUTCOME" in _codes(MODULE.evaluate_outcome_gate({}))
    report = _clean_report()
    report["outcome"]["schema"] = "outcome-gate-v1"
    assert "OUTCOME_SCHEMA_UNSUPPORTED" in _codes(MODULE.evaluate_outcome_gate(report))


def test_false_green_one_chapter_with_fifteen_scenes_fails():
    report = _clean_report()
    for item in report["outcome"]["planned_scenes"]:
        item["chapter_id"] = "CH01"
    verdict = MODULE.evaluate_outcome_gate(report)
    assert "CHAPTER_CARDINALITY_INVALID" in _codes(verdict)


def test_missing_tokens_duration_safety_q0_and_attempts_fail_closed():
    report = _clean_report()
    scene = report["outcome"]["scenes"]["CH01_SC01"]
    scene["tokens"] = None
    scene["duration_ms"] = None
    scene["source_safety"] = None
    scene.pop("q0_q1_unresolved")
    scene["attempt_evidence"] = []
    assert "OUTCOME_RECORD_INCOMPLETE" in _codes(MODULE.evaluate_outcome_gate(report))


def test_lane_labels_without_raw_ui_requests_cannot_pass():
    report = _clean_report()
    for phase in report["outcome"]["northstar_phases"]:
        phase["requests"] = []
    assert "NORTHSTAR_REQUEST_EVIDENCE_SHORTFALL" in _codes(MODULE.evaluate_outcome_gate(report))


def test_tampered_final_aggregate_candidate_recovery_and_manifest_hashes_fail():
    mutations = [
        lambda report: report["outcome"]["scenes"]["CH01_SC01"].update(final_text="tampered"),
        lambda report: report["outcome"]["chapter_aggregates"]["CH01"].update(content="tampered"),
        lambda report: report["outcome"]["candidate_selection"]["events"][0].update(selected_row_id="tampered"),
        lambda report: report["outcome"]["recovery"]["after"]["scenes"]["CH01_SC01"].update(final_text="tampered"),
        lambda report: report["outcome"]["run"]["manifest"].update(project_id="tampered"),
    ]
    expected = [
        "SCENE_WITHOUT_ARCHIVED_FINAL", "CHAPTER_AGGREGATE_INVALID",
        "CANDIDATE_SELECTION_EVIDENCE_INVALID", "RECOVERY_HASH_INVALID", "RUN_MANIFEST_HASH_INVALID",
    ]
    for mutate, code in zip(mutations, expected):
        report = _clean_report()
        mutate(report)
        assert code in _codes(MODULE.evaluate_outcome_gate(report))


def test_cli_exit_codes(tmp_path):
    passing = tmp_path / "passing.json"
    passing.write_text(json.dumps(_clean_report()), encoding="utf-8")
    failing = tmp_path / "failing.json"
    failing.write_text("{}", encoding="utf-8")
    verdict = tmp_path / "verdict.md"
    assert MODULE.main(["--outcome-gate", str(passing), "--gate-output", str(verdict)]) == 0
    assert MODULE.main(["--outcome-gate", str(failing), "--gate-output", str(verdict)]) == 1
