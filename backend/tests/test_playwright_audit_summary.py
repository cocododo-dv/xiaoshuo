from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_summary_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "playwright_audit_summary.py"
    spec = importlib.util.spec_from_file_location("playwright_audit_summary", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_playwright_audit_summary_writes_utf8_markdown(tmp_path) -> None:
    module = _load_summary_module()
    artifact_dir = tmp_path / ".playwright-cli"
    artifact_dir.mkdir()
    removed_demo_label = "Demo " + "Studio"
    (artifact_dir / "page-2026-04-20T08-07-21-714Z.yml").write_text(
        "- generic [ref=e1]:\n"
        "  - heading \"参考书学习\" [level=2]\n"
        "  - button \"刷新\"\n"
        "  - generic [ref=e2]: Reference Learning\n"
        f"  - generic [ref=e3]: {removed_demo_label}\n",
        encoding="utf-8",
    )
    (artifact_dir / "page-2026-04-20T08-07-47-205Z.yml").write_text(
        "- generic [ref=e1]:\n"
        "  - heading \"互操作中心\" [level=2]\n"
        "  - generic [ref=e2]: 结果信封\n",
        encoding="utf-8",
    )
    (artifact_dir / "console-2026-04-20T07-00-01-564Z.log").write_text(
        "[warning] Password field is not contained in a form\n"
        "[error] Failed to fetch http://127.0.0.1:8000/api/v2/style-reference/books\n",
        encoding="utf-8",
    )
    (artifact_dir / "reference-export.md").write_text(
        "# Reference Export\n\n- 安全状态：通过\n\n抽象叙事技法样例\n",
        encoding="utf-8",
    )
    (artifact_dir / "audit-summary.md").write_text(
        "# Playwright 走查产物摘要\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "audit-summary.md"
    summary = module.build_summary(artifact_dir, output_path)

    assert output_path.read_bytes().startswith("# Playwright 走查产物摘要".encode("utf-8"))
    text = output_path.read_text(encoding="utf-8")
    assert summary["snapshot_count"] == 2
    assert summary["download_count"] == 1
    assert summary["console_issue_count"] == 2
    assert "page-2026-04-20T08-07-21-714Z.yml" in text
    assert "参考书学习" in text
    assert removed_demo_label not in text
    assert "reference-export.md" in text
    assert "安全状态：通过" in text
    assert "Failed to fetch" in text


def test_playwright_audit_summary_defaults_to_tracked_report_and_ignores_raw_artifacts() -> None:
    module = _load_summary_module()
    repo_root = Path(__file__).resolve().parents[2]

    assert module.DEFAULT_OUTPUT == Path("docs/reports/playwright-audit-summary.md")
    assert ".playwright-cli/" in (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# Wave 0 结果门禁（outcome gate）——设计 v1.1 §8 Wave 0
# 完成门：旧的"无稿但通过"样本必须被新门禁判为失败。
# ---------------------------------------------------------------------------

NORTHSTAR_PHASES = (
    "snowflake_planning",
    "materialization",
    "scene_execution",
    "candidate_selection",
    "archive",
    "chapter_aggregation",
)


def _scene_record(
    chapter_id: str,
    *,
    archived: bool = True,
    final_chars: int = 1200,
    final_row_id: str | None = "fs_row",
    scene_status: str = "archived",
    tokens: int | None = 5200,
    block_reason: str | None = None,
) -> dict:
    return {
        "chapter_id": chapter_id,
        "final_row_id": final_row_id,
        "final_chars": final_chars,
        "archived": archived,
        "scene_status": scene_status,
        "tokens": tokens,
        "duration_ms": 45000,
        "attempts": 1,
        "block_reason": block_reason,
        "source_safety": {"safe": True, "blocked_terms": []},
    }


def _outcome_section(
    *,
    chapters: int = 5,
    scenes_per_chapter: int = 3,
    overrides: dict | None = None,
    drop_scenes: set | None = None,
    phase_lanes: dict | None = None,
) -> dict:
    planned = []
    scenes = {}
    for c in range(1, chapters + 1):
        chapter_id = f"CH{c:02d}"
        for s in range(1, scenes_per_chapter + 1):
            scene_id = f"{chapter_id}_SC{s:02d}"
            planned.append({"chapter_id": chapter_id, "scene_id": scene_id})
            if drop_scenes and scene_id in drop_scenes:
                continue
            scenes[scene_id] = _scene_record(chapter_id)
    for scene_id, record in (overrides or {}).items():
        scenes[scene_id] = record
    lanes = phase_lanes or {}
    phases = [
        {"phase": phase, "lane": lanes.get(phase, "ui"), "evidence": f"{phase} via {lanes.get(phase, 'ui')}"}
        for phase in NORTHSTAR_PHASES
        if lanes.get(phase, "ui") != "__absent__"
    ]
    return {
        "schema": "outcome-gate-v1",
        "expected": {"chapters": chapters, "scenes_per_chapter": scenes_per_chapter},
        "planned_scenes": planned,
        "scenes": scenes,
        "northstar_phases": phases,
    }


def _healthy_chapter_scores(chapters: int = 5) -> dict:
    return {
        f"CH{c:02d}": {"characters": 3600, "originality": 8, "sourceLeakRisk": 10}
        for c in range(1, chapters + 1)
    }


def _failure_codes(verdict: dict) -> set:
    return {item["code"] for item in verdict["failures"]}


def test_outcome_gate_fails_legacy_no_draft_but_green_report() -> None:
    """完成门样本：按仓库真实旧三章 QA 报告形状构造——步骤全 ok、
    三场 human_review_required、finalRowId 全空、空章节仍拿 originality 9。
    旧判定视其为通过；新门禁必须判失败。"""
    module = _load_summary_module()
    legacy_report = {
        "meta": {"storySeed": "玻璃雨停在零点"},
        "steps": [
            {"name": "preflight current DB, tools, provider routes and reference file", "ok": True, "ms": 4000},
            {"name": "scene workbench run three scene jobs and archive final scenes", "ok": True, "ms": 900000},
            {"name": "chapter manuscripts aggregate final text", "ok": True, "ms": 8000},
        ],
        "sceneRunBlockers": [
            {"sceneId": f"CDBQA_0{i}_SC01", "sceneStatus": "human_review_required", "finalRowId": None}
            for i in (1, 2, 3)
        ],
        "chapterScores": {
            f"CDBQA_0{i}": {
                "finalRowId": None,
                "status": "human_review_required",
                "characters": 0,
                "originality": 9,
                "sourceLeakRisk": 10,
            }
            for i in (1, 2, 3)
        },
    }

    verdict = module.evaluate_outcome_gate(legacy_report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    assert "LEGACY_REPORT_NO_OUTCOME" in _failure_codes(verdict)


def test_outcome_gate_fails_scenes_without_archived_final() -> None:
    module = _load_summary_module()
    blocked = {
        scene_id: _scene_record(
            scene_id.rsplit("_", 1)[0],
            archived=False,
            final_chars=0,
            final_row_id=None,
            scene_status="human_review_required",
            block_reason="soft_qc: human_review_required",
        )
        for scene_id in ("CH04_SC02", "CH05_SC01", "CH05_SC03")
    }
    report = {"outcome": _outcome_section(overrides=blocked), "chapterScores": {}}

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    assert "SCENE_WITHOUT_ARCHIVED_FINAL" in _failure_codes(verdict)
    failure = next(item for item in verdict["failures"] if item["code"] == "SCENE_WITHOUT_ARCHIVED_FINAL")
    assert set(failure["scenes"]) == {"CH04_SC02", "CH05_SC01", "CH05_SC03"}


def test_outcome_gate_fails_on_coverage_shortfall() -> None:
    module = _load_summary_module()
    report = {"outcome": _outcome_section(chapters=3, scenes_per_chapter=1)}

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    assert "SCENE_COVERAGE_SHORTFALL" in _failure_codes(verdict)
    assert verdict["stats"]["planned_scenes"] == 3
    assert verdict["stats"]["expected_scenes"] == 15


def test_outcome_gate_fails_empty_final_content_even_if_marked_archived() -> None:
    module = _load_summary_module()
    overrides = {
        "CH02_SC02": _scene_record("CH02", archived=True, final_chars=0, final_row_id="fs_empty"),
    }
    report = {"outcome": _outcome_section(overrides=overrides)}

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    failure = next(item for item in verdict["failures"] if item["code"] == "SCENE_WITHOUT_ARCHIVED_FINAL")
    assert failure["scenes"] == ["CH02_SC02"]


def test_outcome_gate_flags_fake_scores_for_empty_chapters() -> None:
    module = _load_summary_module()
    overrides = {
        f"CH05_SC{s:02d}": _scene_record(
            "CH05", archived=False, final_chars=0, final_row_id=None, scene_status="human_review_required"
        )
        for s in (1, 2, 3)
    }
    scores = _healthy_chapter_scores()
    scores["CH05"] = {"characters": 0, "originality": 9, "sourceLeakRisk": 10}
    report = {"outcome": _outcome_section(overrides=overrides), "chapterScores": scores}

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    assert "EMPTY_CHAPTER_FAKE_SCORE" in _failure_codes(verdict)
    failure = next(item for item in verdict["failures"] if item["code"] == "EMPTY_CHAPTER_FAKE_SCORE")
    assert "CH05" in failure["detail"]


def test_outcome_gate_accepts_guarded_no_draft_marker_for_empty_chapters() -> None:
    """无稿守卫形态（no_draft: true、无数值评分）不算伪评分——
    仍会因场景无归档正文而失败，但不得再报 EMPTY_CHAPTER_FAKE_SCORE。"""
    module = _load_summary_module()
    overrides = {
        f"CH05_SC{s:02d}": _scene_record(
            "CH05", archived=False, final_chars=0, final_row_id=None, scene_status="human_review_required"
        )
        for s in (1, 2, 3)
    }
    scores = _healthy_chapter_scores()
    scores["CH05"] = {"no_draft": True, "status_by_scene": {"CH05_SC01": "human_review_required"}}
    report = {"outcome": _outcome_section(overrides=overrides), "chapterScores": scores}

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    assert "EMPTY_CHAPTER_FAKE_SCORE" not in _failure_codes(verdict)


def test_outcome_gate_requires_ui_lane_for_northstar_phases() -> None:
    module = _load_summary_module()
    report = {
        "outcome": _outcome_section(
            phase_lanes={
                "snowflake_planning": "api",
                "materialization": "api",
                "candidate_selection": "__absent__",
            }
        ),
        "chapterScores": _healthy_chapter_scores(),
    }

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    failure = next(item for item in verdict["failures"] if item["code"] == "NORTHSTAR_PHASE_NOT_UI")
    assert "candidate_selection" in failure["detail"]
    assert "snowflake_planning" in failure["detail"]


def test_outcome_gate_fails_incomplete_scene_record() -> None:
    module = _load_summary_module()
    broken = _scene_record("CH01")
    del broken["tokens"]
    report = {"outcome": _outcome_section(overrides={"CH01_SC01": broken})}

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is False
    failure = next(item for item in verdict["failures"] if item["code"] == "OUTCOME_RECORD_INCOMPLETE")
    assert "CH01_SC01" in failure["detail"]
    assert "tokens" in failure["detail"]


def test_outcome_gate_passes_complete_five_chapter_run() -> None:
    """可证伪性：完整五章十五场、全部归档非空、六阶段全 UI 时门禁必须通过，
    防止造出一个永远失败的假门。"""
    module = _load_summary_module()
    report = {"outcome": _outcome_section(), "chapterScores": _healthy_chapter_scores()}

    verdict = module.evaluate_outcome_gate(report, expected_chapters=5, scenes_per_chapter=3)

    assert verdict["passed"] is True
    assert verdict["failures"] == []
    assert verdict["stats"]["archived_scenes"] == 15


def test_outcome_gate_cli_exit_codes_and_verdict_file(tmp_path) -> None:
    module = _load_summary_module()
    import json

    failing = {"steps": [{"name": "x", "ok": True, "ms": 1}]}
    failing_path = tmp_path / "legacy.json"
    failing_path.write_text(json.dumps(failing), encoding="utf-8")
    passing = {"outcome": _outcome_section(), "chapterScores": _healthy_chapter_scores()}
    passing_path = tmp_path / "healthy.json"
    passing_path.write_text(json.dumps(passing), encoding="utf-8")
    verdict_md = tmp_path / "outcome-gate-verdict.md"

    rc_fail = module.main(
        [
            "--outcome-gate", str(failing_path),
            "--expected-chapters", "5",
            "--scenes-per-chapter", "3",
            "--gate-output", str(verdict_md),
        ]
    )
    assert rc_fail == 1
    text = verdict_md.read_text(encoding="utf-8")
    assert "失败" in text
    assert "LEGACY_REPORT_NO_OUTCOME" in text

    rc_pass = module.main(
        [
            "--outcome-gate", str(passing_path),
            "--expected-chapters", "5",
            "--scenes-per-chapter", "3",
            "--gate-output", str(verdict_md),
        ]
    )
    assert rc_pass == 0
    assert "通过" in verdict_md.read_text(encoding="utf-8")
