"""Tests for v2 blueprint alignment modules.

Covers: scene_criticality, style_drift_detector, candidate_dispersion,
        chapter_transition_buffer, expanded narrative events, hook type
        classification, and information asymmetry extensions.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    FinalScene,
    ForeshadowTracker,
    HumanReviewEvent,
    NarrativeEvent,
    SceneCard,
    SceneExecutionContract,
    SceneRunState,
    SnowflakeScenePlan,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_project(session, project_id="proj_bp"):
    from novel_system.db.models import StoryProject
    session.add(StoryProject(project_id=project_id, title="蓝图测试项目", outline_text="测试大纲"))
    session.flush()


def _seed_chapter(session, chapter_id="ch01", project_id="proj_bp", display_order=1):
    session.add(ChapterGoal(
        chapter_id=chapter_id,
        project_id=project_id,
        display_order=display_order,
        planned_scene_count=2,
        chapter_goal="test chapter goal",
    ))
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    session.flush()


def _seed_scene(session, scene_id="sc01", chapter_id="ch01", project_id="proj_bp", **kwargs):
    defaults = dict(
        scene_id=scene_id,
        chapter_id=chapter_id,
        project_id=project_id,
        scene_seq=1,
        scene_goal="test scene goal",
        pov_character_id="alice",
        onstage_chars_json=["alice", "bob"],
        location="library",
    )
    defaults.update(kwargs)
    session.add(SceneCard(**defaults))
    session.add(SceneRunState(scene_id=scene_id, scene_status="ready"))
    session.flush()
    return session.get(SceneCard, scene_id)


# ===========================================================================
# §1  scene_criticality
# ===========================================================================

class TestSceneCriticality:
    def test_critical_scene_with_turn_tag_and_high_tension(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session)
        scene = _seed_scene(session, writer_brief_json={
            "function_tag": "turn",
            "tension_target": 8,
            "scene_crucible": "角色必须在两个都有巨大代价的选择中做出决定" * 2,
        }, is_chapter_last=1)
        c = classify_scene(scene)
        assert c.level == "critical"
        assert c.best_of_n == 5
        assert c.human_gate is True

    def test_transition_scene_with_no_signals(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session)
        scene = _seed_scene(session, writer_brief_json={})
        c = classify_scene(scene)
        assert c.level == "transition"
        assert c.best_of_n == 1
        assert c.human_gate is False

    def test_standard_scene_with_moderate_signals(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session)
        scene = _seed_scene(session, writer_brief_json={
            "tension_target": 7,
            "scene_form": "proactive",
        })
        c = classify_scene(scene)
        assert c.level == "standard"
        assert c.best_of_n == 3


# ===========================================================================
# §2  style_drift_detector
# ===========================================================================

class TestStyleDriftDetector:
    def test_compute_metrics_basic(self):
        from novel_system.services.style_drift_detector import _compute_metrics
        text = "这是第一句。这是第二句，更长一点。他问道？她回答了。\n新的段落。"
        metrics = _compute_metrics(text)
        assert "avg_sentence_length" in metrics
        assert "dialogue_ratio" in metrics
        assert "question_density_per_1k" in metrics
        assert metrics["avg_sentence_length"] > 0

    def test_detect_drift_with_deviation(self, session):
        from novel_system.services.style_drift_detector import detect_chapter_drift
        _seed_project(session)
        _seed_chapter(session)
        _seed_scene(session)
        session.add(FinalScene(
            row_id="fs_drift_1",
            scene_id="sc01",
            chapter_id="ch01",
            content="这是一段很短的文字。问号？对话不多。" * 10,
            status="approved",
            source_bundle_id="bundle_test",
            source_bundle_hash="hash_test",
        ))
        session.flush()
        baseline = {
            "avg_sentence_length": 50.0,
            "dialogue_ratio": 0.5,
            "sensory_visual_per_1k": 0.1,
            "punctuation_density_per_1k": 1.0,
            "question_density_per_1k": 0.01,
        }
        report = detect_chapter_drift(session, "ch01", baseline)
        assert report.metrics_computed > 0
        assert report.has_drift

    def test_no_drift_when_close_to_baseline(self, session):
        from novel_system.services.style_drift_detector import detect_chapter_drift, _compute_metrics
        _seed_project(session)
        _seed_chapter(session)
        _seed_scene(session)
        content = "他看着窗外。天空很暗。" * 20
        session.add(FinalScene(
            row_id="fs_nodrift",
            scene_id="sc01",
            chapter_id="ch01",
            content=content,
            status="approved",
            source_bundle_id="bundle_test",
            source_bundle_hash="hash_test",
        ))
        session.flush()
        baseline = _compute_metrics(content)
        report = detect_chapter_drift(session, "ch01", baseline)
        assert not report.has_drift


# ===========================================================================
# §3  candidate dispersion
# ===========================================================================

class TestCandidateDispersion:
    def test_identical_texts_zero_dispersion(self):
        from novel_system.services.scene_generation import _candidate_dispersion
        texts = ["相同的文字内容"] * 3
        assert _candidate_dispersion(texts) == 0.0

    def test_different_texts_high_dispersion(self):
        from novel_system.services.scene_generation import _candidate_dispersion
        texts = [
            "在深夜的图书馆里，她翻开了一本旧书。",
            "明亮的阳光照进房间，他站在窗前微笑。",
            "暴雨倾盆，闪电撕裂天空，她冲进人群。",
        ]
        d = _candidate_dispersion(texts)
        assert d > 0.3

    def test_single_text_returns_one(self):
        from novel_system.services.scene_generation import _candidate_dispersion
        assert _candidate_dispersion(["只有一段"]) == 1.0


# ===========================================================================
# §4  hook type classification
# ===========================================================================

class TestHookTypeClassification:
    def test_suspense_keywords(self):
        from novel_system.services.tension_curve import classify_hook_type
        assert classify_hook_type("到底是谁在背后策划这一切？命运未知。") == "suspense"

    def test_reversal_keywords(self):
        from novel_system.services.tension_curve import classify_hook_type
        assert classify_hook_type("出乎意料的反转——原来她才是幕后真凶。") == "reversal"

    def test_emotion_keywords(self):
        from novel_system.services.tension_curve import classify_hook_type
        assert classify_hook_type("她心痛得无法呼吸，泪水模糊了视线。") == "emotion"

    def test_info_gap_keywords(self):
        from novel_system.services.tension_curve import classify_hook_type
        assert classify_hook_type("他还不知道，她一直在隐瞒真相。") == "info_gap"

    def test_adjacent_hook_check(self):
        from novel_system.services.tension_curve import check_adjacent_hook_types
        warnings = check_adjacent_hook_types(["suspense", "suspense", "emotion", "emotion"])
        assert len(warnings) == 2

    def test_no_adjacent_violation(self):
        from novel_system.services.tension_curve import check_adjacent_hook_types
        warnings = check_adjacent_hook_types(["suspense", "emotion", "reversal", "info_gap"])
        assert len(warnings) == 0


# ===========================================================================
# §5  expanded narrative events
# ===========================================================================

class TestExpandedNarrativeEvents:
    def _run_record_events(self, session, *, scene_kwargs=None, foreshadow=None):
        from novel_system.services.orchestrator import Orchestrator
        from novel_system.db.models import SceneExecutionContract
        _seed_project(session)
        _seed_chapter(session)
        s_kw = scene_kwargs or {}
        scene = _seed_scene(session, writer_brief_json={
            "must_reveal": "alice 知道了 bob 的秘密",
            **s_kw.get("writer_brief_json", {}),
        }, **{k: v for k, v in s_kw.items() if k != "writer_brief_json"})
        contract = SceneExecutionContract(
            contract_id="ctr_01",
            scene_id="sc01",
            chapter_id="ch01",
            status="active",
            source_snapshot_hash="test_hash",
            payload_json={"project_id": "proj_bp"},
        )
        session.add(contract)
        if foreshadow:
            session.add(ForeshadowTracker(**foreshadow))
        session.flush()
        orch = Orchestrator(session)
        orch._record_narrative_events(scene, contract, "测试内容" * 10)
        session.flush()

    def test_location_change_events_logged(self, session):
        self._run_record_events(session)
        evts = session.execute(
            select(NarrativeEvent).where(NarrativeEvent.event_type == "location_change")
        ).scalars().all()
        assert len(evts) >= 2  # alice + bob
        assert evts[0].fact_value == "library"

    def test_character_learns_from_must_reveal(self, session):
        self._run_record_events(session)
        evts = session.execute(
            select(NarrativeEvent).where(NarrativeEvent.event_type == "character_learns")
        ).scalars().all()
        assert len(evts) == 1
        assert "bob 的秘密" in evts[0].fact_value

    def test_foreshadow_plant_event(self, session):
        self._run_record_events(session, foreshadow={
            "row_id": "ft_01",
            "foreshadow_id": "fs_001",
            "chapter_id": "ch01",
            "scene_id": "sc01",
            "text": "暗示：门后有响动",
            "tracker_status": "open",
            "active_flag": 1,
        })
        evts = session.execute(
            select(NarrativeEvent).where(NarrativeEvent.event_type == "foreshadow_plant")
        ).scalars().all()
        assert len(evts) == 1
        assert evts[0].entity_id == "fs_001"

    def test_foreshadow_resolve_event(self, session):
        self._run_record_events(session, foreshadow={
            "row_id": "ft_02",
            "foreshadow_id": "fs_002",
            "chapter_id": "ch01",
            "scene_id": "sc01",
            "text": "门后的声音终于揭晓",
            "tracker_status": "resolved",
            "active_flag": 1,
        })
        evts = session.execute(
            select(NarrativeEvent).where(NarrativeEvent.event_type == "foreshadow_resolve")
        ).scalars().all()
        assert len(evts) == 1
        assert evts[0].entity_id == "fs_002"


# ===========================================================================
# §6  scene plan new fields
# ===========================================================================

class TestScenePlanNewFields:
    def test_new_fields_exist_on_model(self, session):
        _seed_project(session)
        session.add(SnowflakeScenePlan(
            scene_plan_id="sp_01",
            project_id="proj_bp",
            scene_id="sc_test",
            chapter_id="ch_test",
            tension_target=7,
            function_tag="turn",
            involved_foreshadowing_json=["fs_001", "fs_002"],
        ))
        session.flush()
        plan = session.get(SnowflakeScenePlan, "sp_01")
        assert plan.tension_target == 7
        assert plan.function_tag == "turn"
        assert plan.involved_foreshadowing_json == ["fs_001", "fs_002"]


# ===========================================================================
# §7  chapter transition buffer
# ===========================================================================

class TestChapterTransitionBuffer:
    def test_first_scene_gets_previous_chapter_tail(self, session):
        from novel_system.services.bundle_builder import BundleBuilder
        _seed_project(session)
        _seed_chapter(session, chapter_id="ch01", display_order=1)
        _seed_chapter(session, chapter_id="ch02", display_order=2)
        _seed_scene(session, scene_id="sc01_last", chapter_id="ch01", scene_seq=1)
        session.add(FinalScene(
            row_id="fs_ch01_last",
            scene_id="sc01_last",
            chapter_id="ch01",
            content="前一章的精彩内容" * 60,
            status="approved",
            source_bundle_id="bundle_test",
            source_bundle_hash="hash_test",
        ))
        scene2 = _seed_scene(session, scene_id="sc02_first", chapter_id="ch02", scene_seq=1)
        session.flush()

        bb = BundleBuilder(session)
        result = bb._chapter_transition_buffer(scene2)
        assert result is not None
        assert "Chapter Transition Buffer" in result
        assert "前一章的精彩内容" in result

    def test_non_first_scene_returns_none(self, session):
        from novel_system.services.bundle_builder import BundleBuilder
        _seed_project(session)
        _seed_chapter(session)
        scene = _seed_scene(session, scene_seq=3)
        bb = BundleBuilder(session)
        result = bb._chapter_transition_buffer(scene)
        assert result is None

    def test_first_chapter_returns_none(self, session):
        from novel_system.services.bundle_builder import BundleBuilder
        _seed_project(session)
        _seed_chapter(session, chapter_id="ch01", display_order=1)
        scene = _seed_scene(session, chapter_id="ch01", scene_seq=1)
        bb = BundleBuilder(session)
        result = bb._chapter_transition_buffer(scene)
        assert result is None


# ===========================================================================
# §8  tension curve hook validation
# ===========================================================================

class TestTensionCurveHookValidation:
    def test_validate_chapter_hooks_flags_missing_type(self, session):
        from novel_system.services.tension_curve import TensionCurveService
        _seed_project(session)
        _seed_chapter(session)
        _seed_scene(session, is_chapter_last=1, hook="")
        svc = TensionCurveService(session)
        violations = svc.validate_chapter_hooks("ch01")
        assert any(v.violation_type == "missing_hook_type" for v in violations)


# ===========================================================================
# §9  reverse causal skeleton
# ===========================================================================

class TestReverseCausalSkeleton:
    def test_build_skeleton_without_turning_points(self):
        from novel_system.services.reverse_causal_skeleton import build_reverse_skeleton
        s = build_reverse_skeleton("残缺也是完整", "主角接受了不完美")
        assert s.controlling_idea == "残缺也是完整"
        assert len(s.chain) == 1

    def test_build_skeleton_with_turning_points(self):
        from novel_system.services.reverse_causal_skeleton import build_reverse_skeleton
        points = [
            {"description": "主角失去右臂", "why": "为终局接受残缺做铺垫",
             "state_before": "完整", "state_after": "残缺"},
            {"description": "主角发现真相", "why": "为做出最终选择提供信息",
             "state_before": "残缺且迷茫", "state_after": "残缺但清醒"},
        ]
        s = build_reverse_skeleton("残缺也是完整", "主角接受了不完美", points)
        assert len(s.chain) == 3  # 2 points + ending

    def test_chain_integrity_validation(self):
        from novel_system.services.reverse_causal_skeleton import ReverseCausalSkeleton, CausalLink
        s = ReverseCausalSkeleton(
            controlling_idea="test",
            ending_state="end",
            chain=[
                CausalLink(0, "step 0", "why", "a", "b"),
                CausalLink(1, "step 1", "why", "MISMATCH", "d"),
            ],
        )
        issues = s.validate_chain_integrity()
        assert len(issues) == 1
        assert "mismatch" in issues[0].lower() or "State" in issues[0]

    def test_format_for_prompt(self):
        from novel_system.services.reverse_causal_skeleton import build_reverse_skeleton, format_skeleton_for_prompt
        s = build_reverse_skeleton("test idea", "test ending")
        text = format_skeleton_for_prompt(s)
        assert "Reverse Causal Skeleton" in text
        assert "test idea" in text


# ===========================================================================
# §10 information asymmetry
# ===========================================================================

class TestInformationAsymmetry:
    def test_asymmetry_digest_with_knowledge_gap(self, session):
        from novel_system.services.narrative_event_log import NarrativeEventLog
        _seed_project(session)
        _seed_chapter(session)
        _seed_scene(session)
        log = NarrativeEventLog(session)
        log.log_event(
            project_id="proj_bp", scene_id="sc01", chapter_id="ch01",
            event_type="character_learns", entity_type="character",
            entity_id="alice", fact_key="knows_secret",
            fact_value="bob is the traitor",
        )
        session.flush()
        digest = log.information_asymmetry_digest("proj_bp", 2, ["alice", "bob"])
        assert "alice" in digest
        assert "bob" in digest

    def test_asymmetry_empty_when_no_events(self, session):
        from novel_system.services.narrative_event_log import NarrativeEventLog
        _seed_project(session)
        _seed_chapter(session)
        _seed_scene(session)
        log = NarrativeEventLog(session)
        digest = log.information_asymmetry_digest("proj_bp", 1, ["alice", "bob"])
        assert digest == ""

    def test_secret_tracking(self, session):
        from novel_system.services.narrative_event_log import NarrativeEventLog
        _seed_project(session)
        _seed_chapter(session)
        _seed_scene(session)
        log = NarrativeEventLog(session)
        log.log_event(
            project_id="proj_bp", scene_id="sc01", chapter_id="ch01",
            event_type="character_state", entity_type="character",
            entity_id="alice", fact_key="secret_held_by",
            fact_value="alice knows the poison is in the wine",
        )
        session.flush()
        digest = log.information_asymmetry_digest("proj_bp", 2, ["alice", "bob"])
        assert "Secrets" in digest or "secret" in digest.lower()


# ===========================================================================
# §11 auto-critique (reflexion pass)
# ===========================================================================

class TestAutoCritique:
    def test_skip_critique_returns_empty(self):
        from novel_system.services.auto_critique import auto_critique
        result = auto_critique("任何文字", skip_critique=True)
        assert result.should_rewrite is False
        assert result.directives == []

    def test_empty_text_returns_empty(self):
        from novel_system.services.auto_critique import auto_critique
        result = auto_critique("")
        assert result.should_rewrite is False

    def test_perception_filter_detected(self):
        from novel_system.services.auto_critique import auto_critique
        text = (
            "她觉得这一切都很奇怪。他看到远处的灯光。她意识到事情不对。"
            "他感到一阵寒意。她知道这是最后的机会。"
        ) * 5
        result = auto_critique(text)
        assert "perception_filter" in result.dimension_scores

    def test_format_critique_brief_list(self):
        from novel_system.services.auto_critique import auto_critique, format_critique_brief
        result = auto_critique("她觉得他看到她意识到他感到。" * 20)
        brief = format_critique_brief(result)
        assert isinstance(brief, list)
        if result.should_rewrite:
            assert any("Auto-Critique" in b for b in brief)


# ===========================================================================
# §12 POV voice coloring
# ===========================================================================

class TestPovVoiceColoring:
    def test_warrior_archetype_detection(self):
        from novel_system.services.pov_voice_coloring import build_pov_coloring
        directive = build_pov_coloring("将军林远", None, {"role": "将军"})
        assert "threat" in " ".join(directive.attention_focus).lower() or len(directive.attention_focus) > 0

    def test_format_includes_pov_constraint(self):
        from novel_system.services.pov_voice_coloring import build_pov_coloring, format_pov_coloring_prompt
        directive = build_pov_coloring("苏晚", None, {})
        prompt = format_pov_coloring_prompt(directive)
        assert "whose POV" in prompt or "苏晚" in prompt
        assert "自由间接引语" in prompt

    def test_empty_bible_still_produces_output(self):
        from novel_system.services.pov_voice_coloring import build_pov_coloring, format_pov_coloring_prompt
        directive = build_pov_coloring("unknown_char", None, {})
        prompt = format_pov_coloring_prompt(directive)
        assert "unknown_char" in prompt
        assert len(prompt) > 50

    def test_bible_fields_used(self):
        from novel_system.services.pov_voice_coloring import build_pov_coloring
        bible = {
            "core_fear": "被遗弃",
            "core_need": "被认可",
            "occupation": "医师",
        }
        directive = build_pov_coloring("healer_char", "voice card text", bible)
        assert "被遗弃" in directive.narration_guidance or "healer" in directive.narration_guidance.lower()


# ===========================================================================
# §13 voice fingerprint
# ===========================================================================

class TestVoiceFingerprint:
    def test_extract_from_populated_bible(self):
        from novel_system.services.voice_fingerprint import extract_fingerprint_from_bible
        bible = {
            "avg_sentence_length": "short (5-10 chars)",
            "catchphrases": ["哼", "你懂什么"],
            "directness": "indirect",
            "formality": "formal",
            "dialect_markers": ["儿化音"],
            "domain_preferences": ["military terminology"],
        }
        fp = extract_fingerprint_from_bible("林远", bible)
        assert fp.character_id == "林远"
        assert fp.syntax.avg_sentence_length == "short (5-10 chars)"
        assert "哼" in fp.vocabulary.catchphrases
        assert fp.pragmatic.directness == "indirect"
        assert fp.vocabulary.formality == "formal"
        assert "儿化音" in fp.special.dialect_markers

    def test_extract_from_empty_bible(self):
        from novel_system.services.voice_fingerprint import extract_fingerprint_from_bible
        fp = extract_fingerprint_from_bible("generic", {})
        assert fp.character_id == "generic"
        assert fp.syntax.avg_sentence_length == "medium (10-20 chars)"
        assert fp.vocabulary.formality == "mixed"
        assert fp.pragmatic.directness == "direct"

    def test_format_prompt_contains_all_layers(self):
        from novel_system.services.voice_fingerprint import extract_fingerprint_from_bible, format_voice_fingerprint_prompt
        fp = extract_fingerprint_from_bible("测试", {"catchphrases": ["嗯哼"]})
        prompt = format_voice_fingerprint_prompt(fp)
        assert "Syntax layer" in prompt
        assert "Vocabulary layer" in prompt
        assert "Pragmatic layer" in prompt
        assert "Hard constraint" in prompt
        assert "嗯哼" in prompt

    def test_format_qc_checklist(self):
        from novel_system.services.voice_fingerprint import extract_fingerprint_from_bible, format_voice_fingerprint_for_qc
        fp = extract_fingerprint_from_bible("测试", {"banned_words": ["绝对不会说的词"]})
        qc = format_voice_fingerprint_for_qc(fp)
        assert "Blind test" in qc
        assert "绝对不会说的词" in qc
        assert "- [ ]" in qc


# ===========================================================================
# §14 foreshadow lifecycle upgrades
# ===========================================================================

class TestForeshadowLifecycleUpgrades:
    def _seed_foreshadow(self, session, *, scene_seq=1, **overrides):
        _seed_project(session)
        _seed_chapter(session)
        for i in range(1, 4):
            _seed_scene(session, scene_id=f"sc0{i}", scene_seq=i)
        defaults = dict(
            row_id="ft_up_01",
            foreshadow_id="fs_up_001",
            chapter_id="ch01",
            scene_id="sc01",
            text="暗示：将军的刀有毒",
            tracker_status="open",
            active_flag=1,
        )
        defaults.update(overrides)
        session.add(ForeshadowTracker(**defaults))
        session.flush()

    def test_preplanned_reinforcement_takes_priority(self, session):
        from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService
        self._seed_foreshadow(session, reinforce_plan_json=[
            {"target_scene_seq": 2, "method": "伤口异常疼痛加剧"},
        ])
        svc = ForeshadowLifecycleService(session)
        report = svc.scene_actions("sc02")
        reinforce_actions = [a for a in report.actions if a.action == "reinforce"]
        assert len(reinforce_actions) >= 1
        assert reinforce_actions[0].method == "伤口异常疼痛加剧"
        assert "Pre-planned" in reinforce_actions[0].reason

    def test_theme_tag_in_formatted_output(self, session):
        from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService
        self._seed_foreshadow(session,
            theme_tag="残缺与完整",
            reinforce_plan_json=[{"target_scene_seq": 2, "method": "疼痛加剧"}],
        )
        svc = ForeshadowLifecycleService(session)
        text = svc.format_foreshadow_directives("sc02")
        assert text is not None
        assert "残缺与完整" in text
        assert "疼痛加剧" in text

    def test_health_report_counts(self, session):
        from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService
        self._seed_foreshadow(session,
            theme_tag="残缺与完整",
            reinforce_plan_json=[{"target_scene_seq": 5, "method": "hint"}],
        )
        svc = ForeshadowLifecycleService(session)
        health = svc.health_report("ch01")
        assert health.total_open == 1
        assert health.with_planned_reinforcement == 1
        assert health.with_theme_tag == 1
        assert health.without_planned_reinforcement == 0

    def test_payoff_method_in_output(self, session):
        from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService
        self._seed_foreshadow(session, payoff_method="苏晚发现残臂黑纹")
        for i in range(4, 20):
            _seed_scene(session, scene_id=f"sc{i:02d}", scene_seq=i)
        session.flush()
        svc = ForeshadowLifecycleService(session)
        report = svc.scene_actions("sc16")
        payoff_actions = [a for a in report.actions if a.action == "payoff"]
        assert len(payoff_actions) >= 1
        assert payoff_actions[0].method == "苏晚发现残臂黑纹"


# ===========================================================================
# §15 theme counterpoint
# ===========================================================================

class TestThemeCounterpoint:
    def test_counterpoint_roundtrip(self, session):
        from novel_system.services.theme_anchor import ThemeAnchorService, CounterpointEntry
        _seed_project(session)
        svc = ThemeAnchorService(session)
        entries = [
            CounterpointEntry("林远", "身体残缺后追求内心完整", "从战士到哲人"),
            CounterpointEntry("苏晚", "外在完美但内心空洞", "从面具到真实"),
        ]
        svc.set_counterpoint_map("proj_bp", entries)
        retrieved = svc.get_counterpoint_map("proj_bp")
        assert len(retrieved) == 2
        assert retrieved[0].character_id == "林远"
        assert retrieved[1].thesis == "外在完美但内心空洞"

    def test_format_theme_prompt_includes_counterpoint(self, session):
        from novel_system.services.theme_anchor import ThemeAnchorService, CounterpointEntry
        _seed_project(session)
        svc = ThemeAnchorService(session)
        svc.set_controlling_idea("proj_bp", "残缺也可以是完整的")
        svc.set_counterpoint_map("proj_bp", [
            CounterpointEntry("林远", "身体残缺追求内心完整", "战士到哲人"),
        ])
        prompt = svc.format_theme_prompt("proj_bp")
        assert "残缺也可以是完整的" in prompt
        assert "Theme Counterpoint" in prompt
        assert "林远" in prompt
        assert "homogenize" in prompt.lower()

    def test_counterpoint_coverage_flags_stale(self, session):
        from novel_system.services.theme_anchor import ThemeAnchorService, CounterpointEntry
        _seed_project(session)
        for i in range(1, 6):
            _seed_chapter(session, chapter_id=f"ch{i:02d}", display_order=i)
        _seed_scene(session, scene_id="sc_ch01", chapter_id="ch01", pov_character_id="林远")
        _seed_scene(session, scene_id="sc_ch05", chapter_id="ch05", scene_seq=2, pov_character_id="苏晚")
        svc = ThemeAnchorService(session)
        svc.set_counterpoint_map("proj_bp", [
            CounterpointEntry("林远", "thesis_a", "arc_a"),
            CounterpointEntry("苏晚", "thesis_b", "arc_b"),
        ])
        result = svc.validate_counterpoint_coverage("proj_bp", "ch05")
        assert "苏晚" in result["covered"]
        assert "林远" in result["stale"] or "林远" in result["missing_from_chapter"]


# ===========================================================================
# §16 semantic self-repetition
# ===========================================================================

class TestSemanticRepetition:
    def test_metaphor_reuse_detected(self):
        from novel_system.services.self_repetition import check_semantic_repetition
        new_text = "她的笑容仿佛春天的阳光。"
        corpus = ["他的笑容仿佛春天的阳光。"]
        hits = check_semantic_repetition(new_text, corpus, ["scene_prev"])
        metaphor_hits = [h for h in hits if h.pattern_type == "metaphor"]
        assert len(metaphor_hits) >= 1

    def test_action_habit_detected(self):
        from novel_system.services.self_repetition import check_semantic_repetition
        new_text = "他轻叹一声，摇了摇头。"
        corpus = [
            "她轻叹着走开了。",
            "他又轻叹了一下。",
        ]
        hits = check_semantic_repetition(new_text, corpus, ["s1", "s2"])
        action_hits = [h for h in hits if h.pattern_type == "action_habit"]
        assert len(action_hits) >= 1
        assert any("轻叹" in h.current_text for h in action_hits)

    def test_emotional_expression_detected(self):
        from novel_system.services.self_repetition import check_semantic_repetition
        new_text = "她心如刀割，泪如雨下。"
        corpus = ["那一刻，他心如刀割。"]
        hits = check_semantic_repetition(new_text, corpus, ["s1"])
        expr_hits = [h for h in hits if h.pattern_type == "emotional_expression"]
        assert len(expr_hits) >= 1
        assert any("心如刀割" in h.current_text for h in expr_hits)

    def test_no_hits_on_different_texts(self):
        from novel_system.services.self_repetition import check_semantic_repetition
        new_text = "月亮挂在天边。"
        corpus = ["阳光照耀大地。"]
        hits = check_semantic_repetition(new_text, corpus, ["s1"])
        assert len(hits) == 0

    def test_format_guidance_output(self):
        from novel_system.services.self_repetition import SemanticRepetitionHit, format_semantic_repetition_guidance
        hits = [
            SemanticRepetitionHit("metaphor", "像春天", "像春天", "s1"),
            SemanticRepetitionHit("action_habit", "轻叹", "轻叹", "s2"),
        ]
        guidance = format_semantic_repetition_guidance(hits)
        assert "Metaphor reuse" in guidance
        assert "Action habit" in guidance
        assert "fresh alternative" in guidance

    def test_empty_hits_returns_empty(self):
        from novel_system.services.self_repetition import format_semantic_repetition_guidance
        assert format_semantic_repetition_guidance([]) == ""


# ===========================================================================
# §17 scene plan causal/cost fields
# ===========================================================================

class TestScenePlanCausalCostFields:
    def test_new_causal_fields_persist(self, session):
        _seed_project(session)
        session.add(SnowflakeScenePlan(
            scene_plan_id="sp_causal_01",
            project_id="proj_bp",
            scene_id="sc_causal",
            chapter_id="ch_causal",
            causal_prerequisite_scene_id="sc_prev",
            cost_requirement="林远必须向苏晚袒露脆弱",
            downstream_obligations_json=["林远必须决定是否向敌人求助"],
        ))
        session.flush()
        plan = session.get(SnowflakeScenePlan, "sp_causal_01")
        assert plan.causal_prerequisite_scene_id == "sc_prev"
        assert plan.cost_requirement == "林远必须向苏晚袒露脆弱"
        assert plan.downstream_obligations_json == ["林远必须决定是否向敌人求助"]

    def test_foreshadow_new_fields_persist(self, session):
        _seed_project(session)
        _seed_chapter(session)
        session.add(ForeshadowTracker(
            row_id="ft_new_fields",
            foreshadow_id="fs_new",
            chapter_id="ch01",
            text="将军的刀上涂有慢性毒药",
            tracker_status="open",
            theme_tag="残缺与完整",
            reinforce_plan_json=[
                {"target_scene_seq": 20, "method": "伤口异常疼痛加剧"},
            ],
            plant_method="林远断臂后伤口持续疼痛",
            payoff_method="苏晚发现残臂出现异常黑纹",
            active_flag=1,
        ))
        session.flush()
        fs = session.get(ForeshadowTracker, "ft_new_fields")
        assert fs.theme_tag == "残缺与完整"
        assert len(fs.reinforce_plan_json) == 1
        assert fs.plant_method == "林远断臂后伤口持续疼痛"
        assert fs.payoff_method == "苏晚发现残臂出现异常黑纹"


# ===========================================================================
# §18 golden chapter criticality
# ===========================================================================

class TestGoldenChapterCriticality:
    def test_golden_chapter_elevates_criticality(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session, display_order=1)
        scene = _seed_scene(session, writer_brief_json={})
        c = classify_scene(scene, chapter_seq=1)
        assert c.level in ("standard", "critical")
        assert c.best_of_n >= 3
        assert "golden_chapter" in c.reasons

    def test_non_golden_chapter_not_elevated(self, session):
        from novel_system.services.scene_criticality import classify_scene
        _seed_project(session)
        _seed_chapter(session, display_order=10)
        scene = _seed_scene(session, writer_brief_json={})
        c = classify_scene(scene, chapter_seq=10)
        assert c.level == "transition"
        assert "golden_chapter" not in c.reasons
