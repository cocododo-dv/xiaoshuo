"""Tests for the second-wave v2 blueprint gap closures.

Covers:
  §2  VolumeSummary roll-up (summary tower volume layer) + ChapterMemory.memory_kind
  §6.4 probabilistic transition promotion (consecutive transitions → standard)
  §16  per-scene constraint_intensity override (breathing-gap slider)
  §15  hybrid consistency check (keyword authoritative + advisory LLM flag layer)
  §4   reverse causal skeleton LLM refinement (advisory gap detection)
"""
from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    SceneCard,
    SceneMemory,
    StoryProject,
    VolumeSummary,
)
from novel_system.services.llm_accounting import LLMCallContext


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text


class FakeTaskRunner:
    """Duck-typed llm_runner exposing run_task(task_name, prompt_text, system_prompt)."""

    def __init__(self, response_text: str = '{"violations": []}', *, fail: bool = False) -> None:
        self.response_text = response_text
        self.fail = fail
        self.calls: list[dict] = []

    def run_task(
        self,
        *,
        task_name: str,
        prompt_text: str,
        system_prompt: str,
        context: LLMCallContext,
    ):
        self.calls.append(
            {"task_name": task_name, "prompt_text": prompt_text, "context": context}
        )
        if self.fail:
            raise RuntimeError("forced LLM failure")
        return _FakeResponse(self.response_text)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _seed_project(session, project_id="proj_w2"):
    session.add(StoryProject(project_id=project_id, title="二期测试", outline_text="大纲"))
    session.flush()


def _seed_chapter(session, chapter_id, project_id="proj_w2", display_order=1):
    session.add(ChapterGoal(
        chapter_id=chapter_id,
        project_id=project_id,
        display_order=display_order,
        planned_scene_count=1,
        chapter_goal="goal",
    ))
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    session.flush()


def _seed_chapter_memory(session, chapter_id, content, *, kind="mixed"):
    session.add(ChapterMemory(
        row_id=f"cm_{chapter_id}",
        chapter_id=chapter_id,
        aggregate_stage="final",
        content=content,
        memory_kind=kind,
        active_flag=1,
        runtime_eligible=1,
    ))
    session.flush()


def _consistency_context() -> LLMCallContext:
    return LLMCallContext(
        scope_type="scene",
        scope_id="s3",
        project_id="proj_w2",
        scene_id="s3",
        node_id="consistency_extract",
        step="consistency_advisory",
    )


def _causal_context() -> LLMCallContext:
    return LLMCallContext(
        scope_type="project",
        scope_id="proj_w2",
        project_id="proj_w2",
        node_id="causal_skeleton_refine",
        step="reverse_causal_refinement",
    )


# ===========================================================================
# §2  VolumeSummary
# ===========================================================================
class TestVolumeSummary:
    def test_memory_kind_defaults_to_mixed(self, session):
        _seed_project(session)
        _seed_chapter(session, "c1")
        _seed_chapter_memory(session, "c1", "氛围内容")
        row = session.get(ChapterMemory, "cm_c1")
        assert row.memory_kind == "mixed"

    def test_aggregate_volume_summary_rolls_up_chapter_memories(self, session):
        from novel_system.services.aggregator import Aggregator
        _seed_project(session)
        chapter_ids = []
        for i in range(1, 6):
            cid = f"c{i}"
            _seed_chapter(session, cid, display_order=i)
            _seed_chapter_memory(session, cid, f"第{i}章的氛围基调")
            chapter_ids.append(cid)

        result = Aggregator(session).aggregate_volume_summary("proj_w2", 1, chapter_ids)
        assert result["status"] == "created"
        assert result["chapter_count"] == 5

        vs = session.get(VolumeSummary, result["volume_summary_row_id"])
        assert vs is not None
        assert vs.volume_seq == 1
        assert vs.active_flag == 1
        # Atmosphere summary should contain content from all chapters in order
        assert "第1章的氛围基调" in vs.atmosphere_summary
        assert "第5章的氛围基调" in vs.atmosphere_summary

    def test_maybe_aggregate_volume_triggers_at_span_boundary(self, session):
        from novel_system.services.aggregator import Aggregator, VOLUME_CHAPTER_SPAN
        _seed_project(session)
        for i in range(1, VOLUME_CHAPTER_SPAN + 1):
            cid = f"c{i}"
            _seed_chapter(session, cid, display_order=i)
            _seed_chapter_memory(session, cid, f"第{i}章氛围")

        # The 5th chapter completes the first volume span
        result = Aggregator(session).maybe_aggregate_volume(f"c{VOLUME_CHAPTER_SPAN}")
        assert result["status"] == "created"
        assert result["volume_seq"] == 1

    def test_maybe_aggregate_volume_noop_before_boundary(self, session):
        from novel_system.services.aggregator import Aggregator
        _seed_project(session)
        for i in range(1, 4):  # only 3 chapters, span is 5
            cid = f"c{i}"
            _seed_chapter(session, cid, display_order=i)
            _seed_chapter_memory(session, cid, f"第{i}章氛围")

        result = Aggregator(session).maybe_aggregate_volume("c3")
        assert result["status"] == "no_op"
        assert result["reason"] == "not_at_volume_boundary"

    def test_volume_summary_supersedes_prior(self, session):
        from novel_system.services.aggregator import Aggregator
        _seed_project(session)
        chapter_ids = []
        for i in range(1, 6):
            cid = f"c{i}"
            _seed_chapter(session, cid, display_order=i)
            _seed_chapter_memory(session, cid, f"第{i}章氛围")
            chapter_ids.append(cid)

        agg = Aggregator(session)
        first = agg.aggregate_volume_summary("proj_w2", 1, chapter_ids)
        second = agg.aggregate_volume_summary("proj_w2", 1, chapter_ids)

        old = session.get(VolumeSummary, first["volume_summary_row_id"])
        new = session.get(VolumeSummary, second["volume_summary_row_id"])
        assert old.active_flag == 0
        assert old.runtime_eligibility_basis == "superseded"
        assert new.active_flag == 1


# ===========================================================================
# §6.4  probabilistic transition promotion
# ===========================================================================
class TestTransitionPromotion:
    def _transition_scene(self, session, scene_id="sc_t"):
        session.add(SceneCard(
            scene_id=scene_id, chapter_id="ch_t", project_id="proj_w2",
            scene_seq=1, scene_goal="过渡", writer_brief_json={},
        ))
        session.flush()
        return session.get(SceneCard, scene_id)

    def test_promotes_after_three_consecutive_transitions(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session, "ch_t")
        scene = self._transition_scene(session)

        baseline = classify_scene(scene, consecutive_transition_count=0)
        assert baseline.level == "transition"

        promoted = classify_scene(scene, consecutive_transition_count=3)
        assert promoted.level == "standard"
        assert promoted.best_of_n == 3
        assert "promoted_after_3_consecutive_transitions" in promoted.reasons

    def test_no_promotion_below_threshold(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session, "ch_t")
        scene = self._transition_scene(session)
        c = classify_scene(scene, consecutive_transition_count=2)
        assert c.level == "transition"


# ===========================================================================
# §16  constraint_intensity breathing-gap slider
# ===========================================================================
class TestConstraintIntensity:
    def _scene(self, session, writer_brief):
        session.add(SceneCard(
            scene_id="sc_ci", chapter_id="ch_ci", project_id="proj_w2",
            scene_seq=1, scene_goal="g", writer_brief_json=writer_brief,
        ))
        session.flush()
        return session.get(SceneCard, "sc_ci")

    def test_free_flow_overrides_critical(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session, "ch_ci")
        # A scene that would otherwise be critical
        scene = self._scene(session, {"function_tag": "turn", "tension_target": 9})
        normal = classify_scene(scene)
        assert normal.level == "critical"

        relaxed = classify_scene(scene, constraint_intensity=0.0)
        assert relaxed.level == "transition"
        assert relaxed.best_of_n == 1
        assert relaxed.skip_critique is True
        assert "constraint_intensity_free_flow" in relaxed.reasons

    def test_full_rigor_overrides_transition(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session, "ch_ci")
        scene = self._scene(session, {})  # would be transition
        normal = classify_scene(scene)
        assert normal.level == "transition"

        rigorous = classify_scene(scene, constraint_intensity=1.0)
        assert rigorous.level == "critical"
        assert rigorous.best_of_n == 5
        assert rigorous.human_gate is True

    def test_mid_intensity_is_standard(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session, "ch_ci")
        scene = self._scene(session, {"function_tag": "turn", "tension_target": 9})
        c = classify_scene(scene, constraint_intensity=0.5)
        assert c.level == "standard"


# ===========================================================================
# §15  hybrid consistency check
# ===========================================================================
class TestHybridConsistency:
    def _setup_state(self, session):
        from novel_system.services.narrative_event_log import NarrativeEventLog
        _seed_project(session)
        _seed_chapter(session, "ch_c")
        for i in range(1, 4):
            session.add(SceneCard(
                scene_id=f"s{i}", chapter_id="ch_c", project_id="proj_w2",
                scene_seq=i, scene_goal=f"g{i}", onstage_chars_json=["林远"],
            ))
        session.flush()
        log = NarrativeEventLog(session)
        log.log_event(
            project_id="proj_w2", chapter_id="ch_c", scene_id="s1",
            event_type="character_state", entity_type="character", entity_id="林远",
            fact_key="missing_limb", fact_value="right_arm",
        )
        session.flush()
        return log

    def test_llm_layer_noop_without_runner(self, session):
        log = self._setup_state(session)
        report = log.check_consistency_llm(
            "林远用左手握住了剑。", "proj_w2", "s3", character_ids=["林远"],
        )
        # Degrades to keyword result; no runner means no advisory flags
        assert all(v.source == "keyword" for v in report.violations)

    def test_llm_flag_is_advisory_not_blocking(self, session):
        log = self._setup_state(session)
        # An *implied* two-handed action ("拉紧了两侧的缰绳") that the deterministic
        # keyword layer cannot catch (no literal 右手/双手 + verb) — genuine LLM
        # territory. The keyword pass is clean here, so the LLM finding is the only
        # one and must surface as an advisory llm_flag, never as a blocker.
        runner = FakeTaskRunner(
            '{"violations": [{"entity": "林远", "fact_key": "missing_limb", '
            '"expected": "right_arm", "actual": "拉紧两侧缰绳暗示双手", '
            '"evidence": "拉紧了两侧的缰绳"}]}'
        )
        report = log.check_consistency_llm(
            "他利落地翻身上马，拉紧了两侧的缰绳。", "proj_w2", "s3",
            character_ids=["林远"], llm_runner=runner,
            llm_context=_consistency_context(),
        )
        assert runner.calls and runner.calls[0]["task_name"] == "consistency_extract"
        keyword_hits = [v for v in report.violations if v.source == "keyword"]
        assert keyword_hits == [], "keyword layer should be clean on the implied case"
        llm_flags = [v for v in report.violations if v.source == "llm_flag"]
        assert len(llm_flags) == 1
        # Advisory flag alone does not flip passed→False (only keyword violations block)
        assert report.passed is True
        assert report.blocking_violations == []

    def test_llm_failure_falls_back_to_keyword(self, session):
        log = self._setup_state(session)
        runner = FakeTaskRunner(fail=True)
        report = log.check_consistency_llm(
            "林远微笑着点头。", "proj_w2", "s3",
            character_ids=["林远"], llm_runner=runner,
            llm_context=_consistency_context(),
        )
        # Should not raise; returns keyword-only result
        assert all(v.source == "keyword" for v in report.violations)

    def test_keyword_violation_still_blocks(self, session):
        log = self._setup_state(session)
        runner = FakeTaskRunner('{"violations": []}')
        # Text uses the missing right arm — keyword layer catches this
        report = log.check_consistency_llm(
            "林远右手握住剑柄。", "proj_w2", "s3",
            character_ids=["林远"], llm_runner=runner,
            llm_context=_consistency_context(),
        )
        keyword_hits = [v for v in report.violations if v.source == "keyword"]
        assert len(keyword_hits) >= 1
        assert report.passed is False


# ===========================================================================
# §4  reverse causal skeleton LLM refinement
# ===========================================================================
class TestCausalSkeletonRefinement:
    def _skeleton(self):
        from novel_system.services.reverse_causal_skeleton import build_reverse_skeleton
        return build_reverse_skeleton(
            controlling_idea="残缺本身也可以是完整的",
            ending_description="林远接受了断臂，找到内心的完整",
            major_turning_points=[
                {"description": "林远向苏晚求助", "why": "必须放下自尊"},
                {"description": "林远断臂", "why": "外在残缺的起点"},
            ],
        )

    def test_refine_noop_without_runner(self):
        from novel_system.services.reverse_causal_skeleton import refine_skeleton_with_llm
        gaps = refine_skeleton_with_llm(self._skeleton())
        assert gaps == []

    def test_refine_returns_advisory_gaps(self):
        from novel_system.services.reverse_causal_skeleton import (
            refine_skeleton_with_llm,
            format_causal_gaps_for_prompt,
        )
        runner = FakeTaskRunner(
            '{"gaps": [{"after_step": 1, "missing_premise": "林远必须先经历一次失败", '
            '"why": "否则求助显得突兀"}]}'
        )
        gaps = refine_skeleton_with_llm(
            self._skeleton(), llm_runner=runner, llm_context=_causal_context()
        )
        assert len(gaps) == 1
        assert gaps[0].after_step == 1
        assert "失败" in gaps[0].missing_premise
        rendered = format_causal_gaps_for_prompt(gaps)
        assert "因果缺口" in rendered

    def test_refine_does_not_mutate_skeleton(self):
        from novel_system.services.reverse_causal_skeleton import refine_skeleton_with_llm
        skeleton = self._skeleton()
        original_len = len(skeleton.chain)
        runner = FakeTaskRunner(
            '{"gaps": [{"after_step": 0, "missing_premise": "X", "why": "Y"}]}'
        )
        refine_skeleton_with_llm(
            skeleton, llm_runner=runner, llm_context=_causal_context()
        )
        # Advisory only — skeleton spine is never silently rewritten
        assert len(skeleton.chain) == original_len

    def test_refine_llm_failure_returns_empty(self):
        from novel_system.services.reverse_causal_skeleton import refine_skeleton_with_llm
        runner = FakeTaskRunner(fail=True)
        gaps = refine_skeleton_with_llm(
            self._skeleton(), llm_runner=runner, llm_context=_causal_context()
        )
        assert gaps == []


# ===========================================================================
# §0  orchestration-signals aggregation endpoint
# ===========================================================================
class TestOrchestrationSignalsEndpoint:
    def _seed_scene_with_state(self, session):
        from novel_system.db.models import SceneRunState
        _seed_project(session)
        _seed_chapter(session, "ch_os")
        session.add(SceneCard(
            scene_id="sc_os", chapter_id="ch_os", project_id="proj_w2",
            scene_seq=1, scene_goal="g", onstage_chars_json=["林远"],
        ))
        session.add(SceneRunState(
            scene_id="sc_os", scene_status="ready",
            candidate_dispersion_score=0.08,
            criticality_level="critical",
            criticality_reasons_json=["function_tag=turn"],
        ))
        session.commit()

    def test_signals_endpoint_returns_aggregated_panel(self, client, session):
        self._seed_scene_with_state(session)
        resp = client.get("/api/v1/scenes/sc_os/orchestration-signals")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["available"] is True
        assert data["dispersion"]["score"] == 0.08
        assert data["dispersion"]["signal"] == "low"  # below 0.15 threshold
        assert data["criticality"]["level"] == "critical"
        # health/budget/drift keys present even when empty
        assert "foreshadow_health" in data
        assert "theme_budget" in data
        assert "style_drift" in data

    def test_signals_endpoint_missing_scene(self, client):
        resp = client.get("/api/v1/scenes/nonexistent/orchestration-signals")
        assert resp.status_code == 200
        assert resp.json()["data"]["available"] is False


# ===========================================================================
# §7  anti-mean sampling — end-to-end flow lock (regression guard)
# ===========================================================================
class TestAntiMeanSamplingFlow:
    def test_task_config_carries_sampling_penalties(self):
        from novel_system.services.llm_client import parse_model_routing_config
        import yaml
        import pathlib
        # Load the real models.yaml so a dropped field is caught here, not silently in prod.
        root = pathlib.Path(__file__).resolve().parents[2]
        raw = yaml.safe_load((root / "config" / "models.yaml").read_text(encoding="utf-8"))
        cfg = parse_model_routing_config(raw)
        stylize = cfg.task_routing.get("stylize")
        assert stylize is not None
        assert stylize.frequency_penalty == 0.3
        assert stylize.presence_penalty == 0.15

    def test_penalties_flow_through_request_to_payload(self):
        from novel_system.services.llm_client import TaskModelConfig
        from novel_system.services.llm_task_runner import LLMNodeRunner
        from novel_system.services.llm_providers.openai import OpenAICompatibleAdapter
        from novel_system.services.llm_providers.base import ProviderRuntimeConfig

        tc = TaskModelConfig(
            provider="openai_compatible", model="m", temperature=0.8,
            max_output_tokens=100, response_format="text",
            frequency_penalty=0.3, presence_penalty=0.15, api_mode="chat",
        )
        req = LLMNodeRunner._build_request(
            {"system_prompt": "sys", "token_budget": {}},
            user_prompt="u", node_id="style_draft", task_config=tc,
        )
        assert req.frequency_penalty == 0.3
        assert req.presence_penalty == 0.15

        cfg = ProviderRuntimeConfig(
            provider_id="p", provider_type="openai_compatible",
            base_url="http://x/v1", api_mode="chat",
        )
        http = OpenAICompatibleAdapter().build_request(req, cfg)
        assert http.payload["frequency_penalty"] == 0.3
        assert http.payload["presence_penalty"] == 0.15

    def test_absent_penalties_stay_out_of_payload(self):
        # Tasks without penalties must not inject the keys (provider default preserved).
        from novel_system.services.llm_client import TaskModelConfig
        from novel_system.services.llm_task_runner import LLMNodeRunner
        from novel_system.services.llm_providers.openai import OpenAICompatibleAdapter
        from novel_system.services.llm_providers.base import ProviderRuntimeConfig

        tc = TaskModelConfig(
            provider="openai_compatible", model="m", temperature=0.5,
            max_output_tokens=100, response_format="text", api_mode="chat",
        )
        req = LLMNodeRunner._build_request(
            {"system_prompt": "sys", "token_budget": {}},
            user_prompt="u", node_id="neutral_draft", task_config=tc,
        )
        assert req.frequency_penalty is None
        cfg = ProviderRuntimeConfig(
            provider_id="p", provider_type="openai_compatible",
            base_url="http://x/v1", api_mode="chat",
        )
        http = OpenAICompatibleAdapter().build_request(req, cfg)
        assert "frequency_penalty" not in http.payload
        assert "presence_penalty" not in http.payload
