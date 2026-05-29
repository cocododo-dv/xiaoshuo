"""PR-8 §5.1 — scene_generation._inject_style_reference 与 InjectionService 集成。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from novel_system.db.models import SceneCard
from novel_system.db.session import SessionLocal
from novel_system.services.scene_generation import SceneGenerationService
from novel_system.services.style_reference.repository import StyleReferenceRepository


def _seed_style_reference_binding(
    *,
    project_id: str,
    seed: str,
    style_features: list[str] | None = None,
    strategy: str = "A",
    profile_status: str = "active",
) -> None:
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        book_id = f"sr_book_{seed}"
        run_id = f"sr_run_{seed}"
        profile_id = f"sr_profile_{seed}"
        binding_id = f"sr_bind_{seed}"
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_profile(
            profile_id=profile_id, book_id=book_id, run_id=run_id, title="t",
            status=profile_status,
            profile_json={
                "narrative_summary": "短句白话",
                "style_features": style_features or ["短句", "克制"],
            },
            coverage_json={},
            source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=binding_id, profile_id=profile_id,
            scope="project", scope_ref_id=project_id,
            task_type="scene_generation", strategy=strategy,
            config_json={}, status="active",
        )
        session.commit()


def _make_scene(project_id: str | None) -> SceneCard:
    return SceneCard(
        scene_id="CH900_SC01",
        chapter_id="CH900",
        project_id=project_id,
        scene_seq=1,
        pov_character_id="CHAR_A",
        onstage_chars_json=["CHAR_A"],
        location="Café",
        scene_goal="reveal",
        beats_json=["arrival"],
        must_include_text="x",
        target_length_band="short",
        scene_type="reveal",
        is_chapter_last=0,
    )


def test_injection_prepends_style_reference_block(session) -> None:
    _seed_style_reference_binding(project_id="proj_inj1", seed="inj1")
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene("proj_inj1")
    base_prompt = {"system_prompt": "BASE_SYSTEM_PROMPT", "user_prompt": "u"}
    out = service._inject_style_reference(base_prompt, scene, task_type="scene_generation")
    assert out is not base_prompt
    assert out["system_prompt"].startswith("[STYLE_REFERENCE]\n")
    assert "短句" in out["system_prompt"]
    assert out["system_prompt"].endswith("BASE_SYSTEM_PROMPT")
    # user_prompt 不变
    assert out["user_prompt"] == "u"


def test_injection_noop_when_scene_has_no_project_id(session) -> None:
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene(None)
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    out = service._inject_style_reference(base, scene)
    assert out is base  # 完全未修改(直接返回原对象)


def test_injection_noop_when_no_active_binding(session) -> None:
    # 不 seed binding
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene("proj_no_binding")
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    out = service._inject_style_reference(base, scene)
    # 无 binding 时 fragments 返 empty → prefix="" → 返回原 prompt
    assert out is base


def test_injection_failure_is_swallowed(session) -> None:
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene("proj_explode")
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    with patch(
        "novel_system.services.scene_generation.InjectionService.fragments_for",
        side_effect=RuntimeError("style_reference unreachable"),
    ):
        out = service._inject_style_reference(base, scene)
    # 异常被吞掉,返回原 prompt(LLM 流程不阻断)
    assert out is base


def test_long_form_continuation_node_carries_refresh_every_chars() -> None:
    """PR-8 §5.1 — long_form_continuation 节点应带 refresh_every_chars=8000。"""
    from novel_system.services.llm_node_registry import llm_node_specs

    nodes = {spec.node_id: spec for spec in llm_node_specs()}
    assert "long_form_continuation" in nodes
    assert nodes["long_form_continuation"].refresh_every_chars == 8000


def _seed_character_binding(*, seed: str, character_id: str, feature: str) -> None:
    """PR-14 — 落 character scope binding(scope_ref_id=character_id)。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=f"sr_book_{seed}", title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=f"sr_run_{seed}", book_id=f"sr_book_{seed}", status="done", phase="done")
        repo.create_profile(
            profile_id=f"sr_profile_{seed}", book_id=f"sr_book_{seed}", run_id=f"sr_run_{seed}",
            title="t", status="active",
            profile_json={"narrative_summary": "n", "style_features": [feature]},
            coverage_json={}, source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=f"sr_bind_{seed}", profile_id=f"sr_profile_{seed}",
            scope="character", scope_ref_id=character_id,
            task_type="scene_generation", strategy="A", config_json={}, status="active",
        )
        session.commit()


def test_injection_matches_character_binding_via_pov(session) -> None:
    """PR-14 — scene.pov_character_id 命中 character binding 时注入该 profile。"""
    _seed_character_binding(seed="povchar", character_id="CHAR_A", feature="角色专属腔调")
    service = SceneGenerationService(session, llm_client=object())
    # scene 的 project 无 binding,但 pov_character_id=CHAR_A 命中 character binding
    scene = _make_scene("proj_no_project_binding")
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    out = service._inject_style_reference(base, scene, task_type="scene_generation")
    assert out is not base
    assert "角色专属腔调" in out["system_prompt"]
    assert out["system_prompt"].endswith("BASE")
