"""PR-8 §6.6 — HardQcEngine._apply_style_validation_gate verdict 路由。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from novel_system.db.models import SceneCard
from novel_system.db.session import SessionLocal
from novel_system.services.qc_engine import HardQcEngine
from novel_system.services.style_reference.repository import StyleReferenceRepository


def _seed_style_binding(
    *,
    project_id: str,
    seed: str,
    profile_status: str = "active",
    profile_json: dict | None = None,
    forbidden_terms: list[str] | None = None,
) -> str:
    """落 book + run + profile + binding,可选 banned_term。返回 profile_id。"""
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    profile_id = f"sr_profile_{seed}"
    binding_id = f"sr_bind_{seed}"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_profile(
            profile_id=profile_id, book_id=book_id, run_id=run_id, title="t",
            status=profile_status,
            profile_json=profile_json or {"narrative_summary": "n"},
            coverage_json={}, source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=binding_id, profile_id=profile_id,
            scope="project", scope_ref_id=project_id,
            task_type="scene_generation", strategy="A",
            config_json={}, status="active",
        )
        for i, term in enumerate(forbidden_terms or []):
            repo.create_banned_term(
                term_id=f"sr_term_{seed}_{i}",
                profile_id=profile_id, scope="generation",
                term=term, source="manual",
            )
        session.commit()
    return profile_id


def _make_scene(project_id: str | None) -> SceneCard:
    return SceneCard(
        scene_id=f"CH800_SC{project_id or 'X'}",
        chapter_id="CH800",
        project_id=project_id,
        scene_seq=1,
        pov_character_id="A",
        onstage_chars_json=["A"],
        location="x",
        scene_goal="g",
        beats_json=["b"],
        must_include_text="m",
        target_length_band="short",
        scene_type="t",
        is_chapter_last=0,
    )


def test_gate_returns_none_when_no_project_id(session) -> None:
    engine = HardQcEngine(session, llm_client=object())
    verdict = engine._apply_style_validation_gate(_make_scene(None), "一段文本")
    assert verdict is None


def test_gate_returns_none_when_no_active_binding(session) -> None:
    engine = HardQcEngine(session, llm_client=object())
    scene = _make_scene("project_no_binding")
    verdict = engine._apply_style_validation_gate(scene, "一段文本")
    assert verdict is None


def test_gate_returns_pass_when_validation_clean(session) -> None:
    _seed_style_binding(project_id="proj_pass", seed="pass")
    engine = HardQcEngine(session, llm_client=object())
    scene = _make_scene("proj_pass")
    verdict = engine._apply_style_validation_gate(scene, "一段普通文本,完全合规。")
    # 无 plag / forbidden_local → verdict=pass
    assert verdict == "pass"


def test_gate_returns_fail_when_forbidden_term_hit(session) -> None:
    _seed_style_binding(
        project_id="proj_fail",
        seed="fail",
        forbidden_terms=["美轮美奂"],
    )
    engine = HardQcEngine(session, llm_client=object())
    scene = _make_scene("proj_fail")
    verdict = engine._apply_style_validation_gate(scene, "这景色真是美轮美奂极了。")
    # forbidden term 命中 → fail
    assert verdict == "fail"


def test_gate_swallows_exception_and_returns_none(session) -> None:
    _seed_style_binding(project_id="proj_explode", seed="explode")
    engine = HardQcEngine(session, llm_client=object())
    scene = _make_scene("proj_explode")
    with patch(
        "novel_system.services.style_reference.validation.ValidationOrchestrator.validate",
        side_effect=RuntimeError("boom"),
    ):
        verdict = engine._apply_style_validation_gate(scene, "一段文本")
    # 异常吞掉,gate 返回 None(qc 直通,不阻塞)
    assert verdict is None
