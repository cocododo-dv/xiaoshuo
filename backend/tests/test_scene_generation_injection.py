"""PR-8 §5.1 — scene_generation._inject_style_reference 与 InjectionService 集成。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from novel_system.db.models import SceneCard, SceneRunState
from novel_system.db.session import SessionLocal
from novel_system.services.scene_generation import SceneGenerationService
from novel_system.services.style_reference.repository import StyleReferenceRepository


import pytest as _pytest_ap
from tests.real_llm_fakes import install_online_pipeline as _install_online_pipeline


@_pytest_ap.fixture(autouse=True)
def _auto_online_pipeline(monkeypatch):
    """假生成已退役：给场景管线未显式注入的子服务兜底在线记账替身。"""
    _install_online_pipeline(monkeypatch)


def _seed_style_reference_binding(
    *,
    project_id: str,
    seed: str,
    task_type: str = "scene_generation",
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
            book_id=book_id,
            title="t",
            source_kind="upload",
            cloud_policy="local_only",
            text_checksum=f"chk_{seed}",
            total_chars=10,
            status="ready",
            stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_profile(
            profile_id=profile_id,
            book_id=book_id,
            run_id=run_id,
            title="t",
            status=profile_status,
            profile_json={
                "narrative_summary": "短句白话",
                "style_features": style_features or ["短句", "克制"],
            },
            coverage_json={},
            source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=binding_id,
            profile_id=profile_id,
            scope="project",
            scope_ref_id=project_id,
            task_type=task_type,
            strategy=strategy,
            config_json={},
            status="active",
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


def _persist_scene(session, scene: SceneCard) -> None:
    session.add(scene)
    session.add(SceneRunState(scene_id=scene.scene_id, scene_status="ready"))
    session.flush()


def _bundle() -> dict[str, object]:
    return {
        "bundle_id": "bundle_CH900_SC01_test",
        "bundle_snapshot_hash": "bundle_hash_continuation_test",
        "snapshot": {"scene_id": "CH900_SC01"},
    }


def test_injection_prepends_style_reference_block(session) -> None:
    _seed_style_reference_binding(project_id="proj_inj1", seed="inj1")
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene("proj_inj1")
    base_prompt = {"system_prompt": "BASE_SYSTEM_PROMPT", "user_prompt": "u"}
    out = service._inject_style_reference(
        base_prompt, scene, task_type="scene_generation"
    )
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
    # 异常被吞掉，LLM 流程不阻断；降级原因进入审计但不进入 system/user 文本。
    assert out is not base
    assert out["system_prompt"] == base["system_prompt"]
    assert out["user_prompt"] == base["user_prompt"]
    assert out["_style_reference_runtime_audit"]["outcome"] == "degraded"
    assert out["_style_reference_runtime_audit"]["error_code"] == "RuntimeError"


def test_neutral_draft_does_not_receive_style_reference_injection(session) -> None:
    """中性稿只搭事实骨架；参考风格必须留到 style_draft 阶段。"""
    _seed_style_reference_binding(project_id="proj_neutral_plain", seed="neutral_plain")
    scene = _make_scene("proj_neutral_plain")
    _persist_scene(session, scene)
    bundle = _bundle()

    class FakePromptBuilder:
        def build(self, snapshot, template_name):  # noqa: ANN001
            assert snapshot == bundle["snapshot"]
            assert template_name == "neutral_draft"
            return {
                "template_name": template_name,
                "template_version": "test",
                "system_prompt": "NEUTRAL_BASE_SYSTEM",
                "user_prompt": "NEUTRAL_BASE_USER",
                "structured_schema": {
                    "type": "object",
                    "required": ["scene_text"],
                    "properties": {"scene_text": {"type": "string"}},
                },
                "token_budget": {
                    "target_input_tokens": 1000,
                    "estimated_input_tokens": 0,
                    "remaining_input_tokens": 1000,
                },
            }

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            return SimpleNamespace(
                llm_call_id="llm_call_neutral_plain",
                response=SimpleNamespace(
                    structured_output={
                        "scene_text": "门外的脚步停住了，他把信封放到桌上，等对面的人先开口。"
                    }
                ),
            )

    runner = FakeRunner()
    service = SceneGenerationService(session, llm_runner=runner)
    service._prompt_builder_instance = FakePromptBuilder()

    with patch.object(
        service, "_inject_style_reference", wraps=service._inject_style_reference
    ) as inject_spy:
        result = service.generate_neutral_draft(scene.scene_id, bundle)

    inject_spy.assert_not_called()
    assert runner.calls[0]["prompt"]["system_prompt"] == "NEUTRAL_BASE_SYSTEM"
    assert "短句白话" not in runner.calls[0]["prompt"]["system_prompt"]
    assert result.content == "门外的脚步停住了，他把信封放到桌上，等对面的人先开口。"


def _seed_character_binding(*, seed: str, character_id: str, feature: str) -> None:
    """PR-14 — 落 character scope binding(scope_ref_id=character_id)。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=f"sr_book_{seed}",
            title="t",
            source_kind="upload",
            cloud_policy="local_only",
            text_checksum=f"chk_{seed}",
            total_chars=10,
            status="ready",
            stats_json={},
        )
        repo.create_run(
            run_id=f"sr_run_{seed}",
            book_id=f"sr_book_{seed}",
            status="done",
            phase="done",
        )
        repo.create_profile(
            profile_id=f"sr_profile_{seed}",
            book_id=f"sr_book_{seed}",
            run_id=f"sr_run_{seed}",
            title="t",
            status="active",
            profile_json={"narrative_summary": "n", "style_features": [feature]},
            coverage_json={},
            source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=f"sr_bind_{seed}",
            profile_id=f"sr_profile_{seed}",
            scope="character",
            scope_ref_id=character_id,
            task_type="scene_generation",
            strategy="A",
            config_json={},
            status="active",
        )
        session.commit()


def test_injection_matches_character_binding_via_pov(session) -> None:
    """PR-14 — scene.pov_character_id 命中 character binding 时注入该 profile。"""
    _seed_character_binding(
        seed="povchar", character_id="CHAR_A", feature="角色专属腔调"
    )
    service = SceneGenerationService(session, llm_client=object())
    # scene 的 project 无 binding,但 pov_character_id=CHAR_A 命中 character binding
    scene = _make_scene("proj_no_project_binding")
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    out = service._inject_style_reference(base, scene, task_type="scene_generation")
    assert out is not base
    assert "角色专属腔调" in out["system_prompt"]
    assert out["system_prompt"].endswith("BASE")


def _seed_scene_binding(*, seed: str, scene_id: str, feature: str) -> None:
    """PR-15 — 落 scene scope binding(scope_ref_id=scene_id)。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=f"sr_book_{seed}",
            title="t",
            source_kind="upload",
            cloud_policy="local_only",
            text_checksum=f"chk_{seed}",
            total_chars=10,
            status="ready",
            stats_json={},
        )
        repo.create_run(
            run_id=f"sr_run_{seed}",
            book_id=f"sr_book_{seed}",
            status="done",
            phase="done",
        )
        repo.create_profile(
            profile_id=f"sr_profile_{seed}",
            book_id=f"sr_book_{seed}",
            run_id=f"sr_run_{seed}",
            title="t",
            status="active",
            profile_json={"narrative_summary": "n", "style_features": [feature]},
            coverage_json={},
            source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=f"sr_bind_{seed}",
            profile_id=f"sr_profile_{seed}",
            scope="scene",
            scope_ref_id=scene_id,
            task_type="scene_generation",
            strategy="A",
            config_json={},
            status="active",
        )
        session.commit()


def test_injection_matches_scene_binding_via_scene_id(session) -> None:
    """PR-15 — scene.scene_id 命中 scene binding(优先于 character/project)。"""
    # _make_scene scene_id 固定为 CH900_SC01
    _seed_scene_binding(seed="scenebind", scene_id="CH900_SC01", feature="场景专属腔调")
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene("proj_no_project_binding")
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    out = service._inject_style_reference(base, scene, task_type="scene_generation")
    assert out is not base
    assert "场景专属腔调" in out["system_prompt"]
    assert out["system_prompt"].endswith("BASE")


def test_injection_matches_onstage_nonpov_character(session) -> None:
    """PR-18 — pov 无 binding,但 onstage 配角有 character binding → 命中配角。"""
    _seed_character_binding(
        seed="onstagechar", character_id="CHAR_B", feature="配角腔调"
    )
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene("proj_no_project_binding")
    scene.pov_character_id = "POV_NO_BIND"  # pov 无 binding
    scene.onstage_chars_json = ["POV_NO_BIND", "CHAR_B"]
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    out = service._inject_style_reference(base, scene, task_type="scene_generation")
    assert out is not base
    assert "配角腔调" in out["system_prompt"]
