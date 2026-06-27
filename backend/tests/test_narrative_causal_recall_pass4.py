"""pass4 R2/R4：叙事事件源 + 因果链召回缺口（先红后绿）。

- NE-G2: CausalChainValidator 前置检查只查成员、不比 scene_seq → 果在因前/自环不报。
- NE-G1c: 事件重放纯 latest-wins、无 confidence 加权 → 同场景内 advisory(extracted)
  事件因 created_at 更晚反超高置信 spec 事实，LLM 幻觉污染单一真相源。
"""

from __future__ import annotations

from novel_system.db.models import SnowflakeScenePlan
from novel_system.services.causal_chain_validator import CausalChainValidator
from novel_system.services.narrative_event_log import NarrativeEventLog


# ---------------------------------------------------------------------------
# NE-G2: 果在因前（effect 的 cause 在更晚场景）应被报为 forward_reference
# ---------------------------------------------------------------------------
def test_causal_effect_before_cause_is_detected(session):
    # EFFECT@seq1 依赖 CAUSE@seq9 —— cause 物理上发生在 effect 之后（不可能的因果序）
    session.add(SnowflakeScenePlan(
        scene_plan_id="sp_effect", project_id="P_NE", scene_id="EFFECT",
        chapter_id="c1", scene_seq=1, status="active",
        causal_prerequisite_scene_id="CAUSE",
    ))
    session.add(SnowflakeScenePlan(
        scene_plan_id="sp_cause", project_id="P_NE", scene_id="CAUSE",
        chapter_id="c1", scene_seq=9, status="active",
        causal_prerequisite_scene_id=None,
    ))
    session.flush()

    report = CausalChainValidator(session).validate_project("P_NE")
    assert any(v.violation_type == "forward_reference" for v in report.violations), (
        f"果在因前未被检测（只查了成员存在、没比 scene_seq）: "
        f"violations={[v.violation_type for v in report.violations]}, cov={report.chain_coverage}"
    )


def test_causal_self_loop_is_detected(session):
    # 自环：场景以自己为前置（seq 不可能 < 自身）
    session.add(SnowflakeScenePlan(
        scene_plan_id="sp_a", project_id="P_LOOP", scene_id="A",
        chapter_id="c1", scene_seq=1, status="active",
        causal_prerequisite_scene_id="A",
    ))
    session.flush()
    report = CausalChainValidator(session).validate_project("P_LOOP")
    assert any(v.violation_type == "forward_reference" for v in report.violations), (
        f"自环未被检测: {[v.violation_type for v in report.violations]}"
    )


def test_causal_valid_backward_link_not_flagged(session):
    """对照：cause@seq1 → effect@seq2 的正常向后链不得误报。"""
    session.add(SnowflakeScenePlan(
        scene_plan_id="sp_c1", project_id="P_OK", scene_id="C1",
        chapter_id="c1", scene_seq=1, status="active", causal_prerequisite_scene_id=None,
    ))
    session.add(SnowflakeScenePlan(
        scene_plan_id="sp_e2", project_id="P_OK", scene_id="E2",
        chapter_id="c1", scene_seq=2, status="active", causal_prerequisite_scene_id="C1",
    ))
    session.flush()
    report = CausalChainValidator(session).validate_project("P_OK")
    assert not any(v.violation_type == "forward_reference" for v in report.violations)


# ---------------------------------------------------------------------------
# NE-G1c: 同场景内 advisory(extracted) 不得反超高置信 spec 事实
# ---------------------------------------------------------------------------
def test_extracted_event_does_not_override_high_confidence_spec(session):
    log = NarrativeEventLog(session)
    common = dict(
        project_id="PROJ_NE", chapter_id="ch1", scene_id="sc1",
        event_type="location_change", entity_type="character",
        entity_id="hero", fact_key="location",
    )
    log.log_event(**common, fact_value="北境", confidence="high")        # spec（权威）
    log.log_event(**common, fact_value="南境", confidence="extracted")   # advisory（更晚）
    session.flush()
    state = log.project_character_state("hero", "PROJ_NE")
    assert state.get("location") == "北境", (
        "advisory(extracted) 事件反超了高置信 spec 事实（重放无 confidence 加权）"
        " → LLM 幻觉覆盖单一真相源"
    )


def test_later_high_confidence_event_still_wins(session):
    """对照：跨场景的后续高置信事件应正常更新状态（confidence 守卫不能冻结状态演进）。"""
    log = NarrativeEventLog(session)
    base = dict(
        project_id="PROJ_EVO", chapter_id="ch1",
        event_type="character_state", entity_type="character",
        entity_id="hero", fact_key="alive",
    )
    log.log_event(**base, scene_id="sc1", fact_value="alive", confidence="high")
    log.log_event(**base, scene_id="sc2", fact_value="dead", confidence="high")
    session.flush()
    state = log.project_character_state("hero", "PROJ_EVO")
    assert state.get("alive") == "dead", "后续高置信状态变化被错误冻结"
