"""Tests for blueprint enforcement features (batch 1 + batch 2).

Covers: conflict-too-clean detection, adversarial dim promotion,
auto-critique new dims, cost_requirement blocking, expression spectrum
frequency tracking, retroactive foreshadow lifecycle, and style-candidates API.
"""
from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    ForeshadowTracker,
    SceneCard,
)


# ---------------------------------------------------------------------------
# §8 / literary_quality: conflict_too_clean detection
# ---------------------------------------------------------------------------


def test_conflict_too_clean_detection_triggers():
    from novel_system.services.literary_quality import analyze_literary_quality

    # Text with conflict + reconciliation in close proximity → should trigger
    text = (
        "她愤怒地质问他为什么隐瞒真相，他一脸惊愕地反对她的指责。"
        "两人激烈争吵了一会儿。"
        "然后他叹气，低下头表示理解。"
        "她点头接受了他的解释，释然地微笑。"
        "他也笑了，两人和好如初。"
    )
    signals, _ = analyze_literary_quality(text)
    assert "conflict_too_clean" in signals
    assert signals["conflict_too_clean"]["risk"] is True
    assert signals["conflict_too_clean"]["score"] < 1.0


def test_conflict_too_clean_detection_clean_text():
    from novel_system.services.literary_quality import analyze_literary_quality

    # Neutral text without conflict/reconciliation patterns → should NOT trigger
    text = (
        "清晨的阳光照进房间，窗外的鸟鸣声渐渐变得嘈杂。"
        "她起身拉开窗帘，看着远处的山脉。"
        "今天的天气很好，适合出门。"
    )
    signals, _ = analyze_literary_quality(text)
    assert "conflict_too_clean" in signals
    assert signals["conflict_too_clean"]["risk"] is False
    assert signals["conflict_too_clean"]["score"] == 1.0


def test_conflict_too_clean_no_reconciliation():
    from novel_system.services.literary_quality import analyze_literary_quality

    # Conflict without reconciliation → should NOT trigger
    text = (
        "他愤怒地拒绝了她的要求，转身离去。"
        "她在背后质问他的动机，但他没有回头。"
        "争吵的余波久久不散。"
    )
    signals, _ = analyze_literary_quality(text)
    assert "conflict_too_clean" in signals
    assert signals["conflict_too_clean"]["risk"] is False


# ---------------------------------------------------------------------------
# §6/§8: adversarial + critique dim promotion
# ---------------------------------------------------------------------------


def test_painless_scene_in_adversarial_dims():
    from novel_system.services.literary_quality import ADVERSARIAL_DIMS

    for dim in ("painless_scene", "no_choice_scene", "choice_pressure", "conflict_too_clean"):
        assert dim in ADVERSARIAL_DIMS, f"{dim} missing from ADVERSARIAL_DIMS"


def test_auto_critique_includes_new_dims():
    from novel_system.services.auto_critique import CRITIQUE_DIMS

    for dim in ("painless_scene", "no_choice_scene", "choice_pressure", "conflict_too_clean"):
        assert dim in CRITIQUE_DIMS, f"{dim} missing from CRITIQUE_DIMS"


def test_dimension_weights_include_conflict_too_clean():
    from novel_system.services.literary_quality import DIMENSION_WEIGHTS

    assert "conflict_too_clean" in DIMENSION_WEIGHTS
    assert DIMENSION_WEIGHTS["conflict_too_clean"] > 0


# ---------------------------------------------------------------------------
# §4: cost_requirement blocking for explicit scenes
# ---------------------------------------------------------------------------


def test_cost_requirement_blocking_for_explicit_scenes(session):
    """Scenes with explicit scene_crucible in blueprint but no cost_requirement
    should be blocked. Scenes with cost_requirement (via exit_change fallback)
    should be active.

    Uses the service directly because scene_crucible arrives via SceneBlueprint,
    not writer_brief_json (which has its own field allowlist).
    """
    from novel_system.db.models import SceneBlueprint
    from novel_system.services.scene_execution import SceneExecutionContractService

    session.add(ChapterGoal(chapter_id="BP_CH01", planned_scene_count=2, chapter_goal="test"))

    # Scene WITH blueprint crucible but NO cost → blocked
    session.add(SceneCard(
        scene_id="BP_CH01_SC01",
        chapter_id="BP_CH01",
        scene_seq=1,
        pov_character_id="CHAR_A",
        scene_goal="test goal",
        writer_brief_json={
            "goal": "Character must confront enemy",
            "conflict": "Enemy has the upper hand",
            "setback_or_victory": "Character suffers a setback",
        },
    ))
    session.add(SceneBlueprint(
        row_id="bp_01",
        scene_id="BP_CH01_SC01",
        chapter_id="BP_CH01",
        status="accepted",
        blueprint_json={"scene_crucible": "Explicit crucible from blueprint"},
    ))
    session.commit()

    svc = SceneExecutionContractService(session)
    contract1 = svc.generate("BP_CH01_SC01", actor_ref="test")
    assert contract1.status == "blocked"
    assert "cost_requirement" in (contract1.missing_fields_json or [])

    # Scene WITH blueprint crucible AND exit_change (cost fallback) → active
    session.add(SceneCard(
        scene_id="BP_CH01_SC02",
        chapter_id="BP_CH01",
        scene_seq=2,
        pov_character_id="CHAR_A",
        scene_goal="test goal 2",
        exit_change="Character loses their secret identity",
        writer_brief_json={
            "goal": "Character seeks the truth",
            "conflict": "Truth is guarded",
            "setback_or_victory": "Partial revelation at a price",
        },
    ))
    session.add(SceneBlueprint(
        row_id="bp_02",
        scene_id="BP_CH01_SC02",
        chapter_id="BP_CH01",
        status="accepted",
        blueprint_json={"scene_crucible": "Another crucible"},
    ))
    session.commit()

    contract2 = svc.generate("BP_CH01_SC02", actor_ref="test")
    assert contract2.status == "active"


def test_cost_requirement_advisory_for_legacy_scenes(client):
    """Scenes without explicit scene_crucible (legacy/simple) should keep
    cost_requirement as advisory (non-blocking)."""
    client.post(
        "/api/v1/chapters",
        json={"chapter_id": "BP_LEG01", "planned_scene_count": 1, "chapter_goal": "legacy"},
        headers={"X-Idempotency-Key": "bp-leg-ch"},
    )
    client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "BP_LEG01_SC01",
            "chapter_id": "BP_LEG01",
            "scene_seq": 1,
            "pov_character_id": "CHAR_A",
            "scene_goal": "simple legacy scene",
            "beats_json": ["beat1", "beat2"],
        },
        headers={"X-Idempotency-Key": "bp-leg-sc"},
    )
    resp = client.get("/api/v1/scenes/BP_LEG01_SC01/execution-contract")
    assert resp.status_code == 200
    contract = resp.json()["data"]["contract"]
    # Legacy scene — cost_requirement is advisory, check it's not a blocking field
    blocking_fields = [f for f in contract["missing_fields"] if "(advisory)" not in f]
    assert "cost_requirement" not in blocking_fields
    advisory_fields = [f for f in contract["missing_fields"] if "(advisory)" in f]
    assert any("cost_requirement" in f for f in advisory_fields)


# ---------------------------------------------------------------------------
# §12: expression spectrum frequency tracking
# ---------------------------------------------------------------------------


def test_expression_spectrum_frequency_tracking(session):
    from novel_system.services.theme_anchor import ThemeAnchorService

    project_id = "EXPR_PROJ"
    svc = ThemeAnchorService(session)
    svc.set_controlling_idea(project_id, "残缺也可以是完整的")

    # First usage → allowed
    r1 = svc.record_expression_usage(project_id, "direct_commentary", "S1", "CH1")
    assert r1["allowed"] is True
    assert r1["usage"]["direct_commentary"] == 1

    # Second usage → allowed (cap is 2)
    r2 = svc.record_expression_usage(project_id, "direct_commentary", "S2", "CH2")
    assert r2["allowed"] is True
    assert r2["usage"]["direct_commentary"] == 2

    # Third usage → blocked (exceeds cap of 2)
    r3 = svc.record_expression_usage(project_id, "direct_commentary", "S3", "CH3")
    assert r3["allowed"] is False
    assert r3["warning"] is not None
    assert "上限" in r3["warning"]


def test_expression_budget_check(session):
    from novel_system.services.theme_anchor import ThemeAnchorService

    project_id = "EXPR_PROJ2"
    svc = ThemeAnchorService(session)
    svc.set_controlling_idea(project_id, "test theme")

    # No usage yet → no warnings
    warnings = svc.check_expression_budget(project_id)
    assert len(warnings) == 0

    # Use direct_commentary once → near_cap warning (cap=2, count=1)
    svc.record_expression_usage(project_id, "direct_commentary", "S1", "CH1")
    warnings = svc.check_expression_budget(project_id)
    assert len(warnings) == 1
    assert warnings[0]["status"] == "near_cap"

    # Use again → exhausted
    svc.record_expression_usage(project_id, "direct_commentary", "S2", "CH2")
    warnings = svc.check_expression_budget(project_id)
    assert len(warnings) == 1
    assert warnings[0]["status"] == "exhausted"


# ---------------------------------------------------------------------------
# §5: retroactive foreshadow lifecycle
# ---------------------------------------------------------------------------


def _seed_chapter_for_foreshadow(session, chapter_id: str = "FS_RETRO", n_scenes: int = 10) -> str:
    session.add(ChapterGoal(chapter_id=chapter_id, planned_scene_count=n_scenes, chapter_goal="test"))
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    for seq in range(1, n_scenes + 1):
        session.add(SceneCard(
            scene_id=f"{chapter_id}_SC{seq:02d}",
            chapter_id=chapter_id,
            scene_seq=seq,
            scene_goal=f"Scene {seq}",
        ))
    session.commit()
    return chapter_id


def test_foreshadow_retroactive_lifecycle(session):
    from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService

    chapter_id = _seed_chapter_for_foreshadow(session)
    svc = ForeshadowLifecycleService(session)

    # Create a retroactive foreshadow
    tracker = svc.create_retroactive_foreshadow(
        chapter_id,
        text="将军的刀上涂有慢性毒药",
        payoff_scene_id=f"{chapter_id}_SC08",
        target_plant_range=(2, 4),
        plant_method="伤口持续疼痛，角色归因于伤口本身",
        payoff_method="苏晚发现残臂出现异常黑纹",
        theme_tag="残缺与完整",
    )
    assert tracker.tracker_status == "retroactive_pending"
    assert tracker.foreshadow_id.startswith("fs_retro_")
    assert tracker.row_id is not None

    # Should appear in pending retroactive list
    pending = svc.pending_retroactive_foreshadows(chapter_id)
    assert len(pending) == 1
    assert pending[0].foreshadow_id == tracker.foreshadow_id

    # Mark as planted
    svc.mark_retroactive_planted(tracker.foreshadow_id, f"{chapter_id}_SC03")
    session.expire_all()

    # Should no longer be pending; status should be "open"
    pending_after = svc.pending_retroactive_foreshadows(chapter_id)
    assert len(pending_after) == 0

    updated = session.get(ForeshadowTracker, tracker.row_id)
    assert updated.tracker_status == "open"
    assert updated.scene_id == f"{chapter_id}_SC03"


# ---------------------------------------------------------------------------
# §6/§14: style-candidates API
# ---------------------------------------------------------------------------


def test_style_candidates_api_returns_empty_list(client, session):
    """GET /scenes/{id}/style-candidates returns 200 with empty candidates for a fresh scene."""
    from tests.test_orchestrator_flow import seed_story

    seed_story(client, session=session)

    resp = client.get("/api/v1/scenes/CH001_SC01/style-candidates")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "candidates" in data
    assert isinstance(data["candidates"], list)
    assert data["total"] == 0  # No drafts generated yet
