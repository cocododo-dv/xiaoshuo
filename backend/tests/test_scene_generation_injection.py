"""PR-8 §5.1 — scene_generation._inject_style_reference 与 InjectionService 集成。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from novel_system.db.models import SceneCard, SceneDraft, SceneRunState
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
            task_type=task_type, strategy=strategy,
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


def test_long_form_continuation_generates_without_refresh_below_threshold(session, monkeypatch) -> None:
    _seed_style_reference_binding(
        project_id="proj_cont_once",
        seed="cont_once",
        task_type="long_form_continuation",
        style_features=["续写腔调"],
    )
    scene = _make_scene("proj_cont_once")
    _persist_scene(session, scene)
    bundle = _bundle()

    class FakePromptBuilder:
        def build(self, snapshot, template_name):  # noqa: ANN001
            assert snapshot == bundle["snapshot"]
            assert template_name == "long_form_continuation"
            return {
                "template_name": template_name,
                "template_version": "test",
                "system_prompt": "BASE_SYSTEM",
                "user_prompt": "BASE_USER",
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
                llm_call_id="llm_call_cont_once",
                response=SimpleNamespace(structured_output={"scene_text": "续写片段一"}),
            )

    runner = FakeRunner()
    service = SceneGenerationService(session, llm_runner=runner)
    service._prompt_builder_instance = FakePromptBuilder()
    monkeypatch.setattr(
        "novel_system.services.scene_generation.get_llm_node_spec",
        lambda node_id: SimpleNamespace(refresh_every_chars=100),
        raising=False,
    )

    with patch.object(service, "_inject_style_reference", wraps=service._inject_style_reference) as inject_spy:
        result = service.generate_long_form_continuation(
            scene.scene_id,
            bundle,
            source_draft_row_id="draft_style_source",
            source_content="原始正文",
            target_continuation_chars=20,
        )

    assert inject_spy.call_count == 1
    assert inject_spy.call_args.kwargs["task_type"] == "long_form_continuation"
    assert runner.calls[0]["node_id"] == "long_form_continuation"
    assert runner.calls[0]["step"] == "long_form_continuation"
    assert runner.calls[0]["prompt"]["system_prompt"].startswith("[STYLE_REFERENCE]\n")
    assert result.content == "续写片段一"

    draft = session.query(SceneDraft).filter_by(stage="long_form_continuation").one()
    assert draft.content == "续写片段一"
    state = session.get(SceneRunState, scene.scene_id)
    assert state is not None
    assert state.current_style_draft_row_id == draft.row_id


def test_long_form_continuation_refreshes_style_reference_after_threshold(session, monkeypatch) -> None:
    _seed_style_reference_binding(
        project_id="proj_cont_refresh_once",
        seed="cont_refresh_once",
        task_type="long_form_continuation",
        style_features=["续写刷新"],
    )
    scene = _make_scene("proj_cont_refresh_once")
    _persist_scene(session, scene)
    bundle = _bundle()

    class FakePromptBuilder:
        def build(self, snapshot, template_name):  # noqa: ANN001
            return {
                "template_name": template_name,
                "template_version": "test",
                "system_prompt": "BASE_SYSTEM",
                "user_prompt": "BASE_USER",
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
            self._segments = ["甲" * 6, "乙" * 6]

        def run(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            index = len(self.calls) - 1
            return SimpleNamespace(
                llm_call_id=f"llm_call_cont_refresh_{index}",
                response=SimpleNamespace(structured_output={"scene_text": self._segments[index]}),
            )

    runner = FakeRunner()
    service = SceneGenerationService(session, llm_runner=runner)
    service._prompt_builder_instance = FakePromptBuilder()
    monkeypatch.setattr(
        "novel_system.services.scene_generation.get_llm_node_spec",
        lambda node_id: SimpleNamespace(refresh_every_chars=10),
        raising=False,
    )

    with patch.object(service, "_inject_style_reference", wraps=service._inject_style_reference) as inject_spy:
        result = service.generate_long_form_continuation(
            scene.scene_id,
            bundle,
            source_draft_row_id="draft_style_source",
            source_content="原始正文",
            target_continuation_chars=12,
        )

    assert inject_spy.call_count == 2
    assert all(call.kwargs["task_type"] == "long_form_continuation" for call in inject_spy.call_args_list)
    assert [call["node_id"] for call in runner.calls] == ["long_form_continuation", "long_form_continuation"]
    assert result.content == ("甲" * 6) + ("乙" * 6)


def test_long_form_continuation_refreshes_multiple_times(session, monkeypatch) -> None:
    _seed_style_reference_binding(
        project_id="proj_cont_refresh_multi",
        seed="cont_refresh_multi",
        task_type="long_form_continuation",
        style_features=["多次刷新"],
    )
    scene = _make_scene("proj_cont_refresh_multi")
    _persist_scene(session, scene)
    bundle = _bundle()

    class FakePromptBuilder:
        def build(self, snapshot, template_name):  # noqa: ANN001
            return {
                "template_name": template_name,
                "template_version": "test",
                "system_prompt": "BASE_SYSTEM",
                "user_prompt": "BASE_USER",
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
            self._segments = ["甲" * 11, "乙" * 10, "丙" * 8]

        def run(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            index = len(self.calls) - 1
            return SimpleNamespace(
                llm_call_id=f"llm_call_cont_refresh_multi_{index}",
                response=SimpleNamespace(structured_output={"scene_text": self._segments[index]}),
            )

    runner = FakeRunner()
    service = SceneGenerationService(session, llm_runner=runner)
    service._prompt_builder_instance = FakePromptBuilder()
    monkeypatch.setattr(
        "novel_system.services.scene_generation.get_llm_node_spec",
        lambda node_id: SimpleNamespace(refresh_every_chars=10),
        raising=False,
    )

    with patch.object(service, "_inject_style_reference", wraps=service._inject_style_reference) as inject_spy:
        result = service.generate_long_form_continuation(
            scene.scene_id,
            bundle,
            source_draft_row_id="draft_style_source",
            source_content="原始正文",
            target_continuation_chars=25,
        )

    assert inject_spy.call_count == 3
    assert len(runner.calls) == 3
    assert result.content == ("甲" * 11) + ("乙" * 10) + ("丙" * 8)


def test_long_form_continuation_degrades_when_no_style_binding(session, monkeypatch) -> None:
    scene = _make_scene("proj_cont_no_binding")
    _persist_scene(session, scene)
    bundle = _bundle()

    class FakePromptBuilder:
        def build(self, snapshot, template_name):  # noqa: ANN001
            return {
                "template_name": template_name,
                "template_version": "test",
                "system_prompt": "BASE_SYSTEM",
                "user_prompt": "BASE_USER",
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
                llm_call_id="llm_call_cont_no_binding",
                response=SimpleNamespace(structured_output={"scene_text": "无绑定也可续写"}),
            )

    runner = FakeRunner()
    service = SceneGenerationService(session, llm_runner=runner)
    service._prompt_builder_instance = FakePromptBuilder()
    monkeypatch.setattr(
        "novel_system.services.scene_generation.get_llm_node_spec",
        lambda node_id: SimpleNamespace(refresh_every_chars=8),
        raising=False,
    )

    with patch.object(service, "_inject_style_reference", wraps=service._inject_style_reference) as inject_spy:
        result = service.generate_long_form_continuation(
            scene.scene_id,
            bundle,
            source_draft_row_id="draft_style_source",
            source_content="原始正文",
            target_continuation_chars=8,
        )

    assert inject_spy.call_count == 1
    assert runner.calls[0]["prompt"]["system_prompt"] == "BASE_SYSTEM"
    assert result.content == "无绑定也可续写"


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


def _seed_scene_binding(*, seed: str, scene_id: str, feature: str) -> None:
    """PR-15 — 落 scene scope binding(scope_ref_id=scene_id)。"""
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
            scope="scene", scope_ref_id=scene_id,
            task_type="scene_generation", strategy="A", config_json={}, status="active",
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
    _seed_character_binding(seed="onstagechar", character_id="CHAR_B", feature="配角腔调")
    service = SceneGenerationService(session, llm_client=object())
    scene = _make_scene("proj_no_project_binding")
    scene.pov_character_id = "POV_NO_BIND"           # pov 无 binding
    scene.onstage_chars_json = ["POV_NO_BIND", "CHAR_B"]
    base = {"system_prompt": "BASE", "user_prompt": "u"}
    out = service._inject_style_reference(base, scene, task_type="scene_generation")
    assert out is not base
    assert "配角腔调" in out["system_prompt"]
