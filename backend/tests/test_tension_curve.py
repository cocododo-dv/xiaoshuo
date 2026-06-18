"""Tests for tension curve and scene function tags — blueprint §10."""
from __future__ import annotations

from novel_system.db.models import ChapterGoal, ChapterState, SceneCard
from novel_system.services.tension_curve import (
    FUNCTION_TAGS,
    TensionCurveService,
    get_scene_function_tag,
    get_scene_tension,
    tension_level_label,
    tension_writing_guidance,
)


def _seed_chapter(session, *, scene_briefs: list[dict]) -> str:
    chapter_id = "TC100"
    session.add(ChapterGoal(chapter_id=chapter_id, planned_scene_count=len(scene_briefs), chapter_goal="test"))
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    for idx, brief in enumerate(scene_briefs, 1):
        session.add(SceneCard(
            scene_id=f"{chapter_id}_SC{idx:02d}",
            chapter_id=chapter_id,
            scene_seq=idx,
            scene_goal=f"Scene {idx}",
            writer_brief_json=brief,
        ))
    session.commit()
    return chapter_id


def test_tension_level_labels() -> None:
    assert tension_level_label(1) == "low"
    assert tension_level_label(3) == "low"
    assert tension_level_label(4) == "medium"
    assert tension_level_label(6) == "medium"
    assert tension_level_label(7) == "high"
    assert tension_level_label(9) == "high"
    assert tension_level_label(10) == "extreme"


def test_tension_writing_guidance_returns_string() -> None:
    for level in range(1, 11):
        guidance = tension_writing_guidance(level)
        assert isinstance(guidance, str)
        assert len(guidance) > 5


def test_get_scene_tension_and_tag() -> None:
    scene = SceneCard(
        scene_id="test", chapter_id="ch", scene_seq=1, scene_goal="test",
        writer_brief_json={"tension_target": 7, "function_tag": "reveal"},
    )
    assert get_scene_tension(scene) == 7
    assert get_scene_function_tag(scene) == "reveal"


def test_get_scene_tension_clamps_range() -> None:
    scene = SceneCard(
        scene_id="test", chapter_id="ch", scene_seq=1, scene_goal="test",
        writer_brief_json={"tension_target": 15},
    )
    assert get_scene_tension(scene) == 10


def test_get_scene_tension_none_when_missing() -> None:
    scene = SceneCard(
        scene_id="test", chapter_id="ch", scene_seq=1, scene_goal="test",
        writer_brief_json={},
    )
    assert get_scene_tension(scene) is None
    assert get_scene_function_tag(scene) is None


def test_adjacent_tag_repeat_detected(session) -> None:
    chapter_id = _seed_chapter(session, scene_briefs=[
        {"function_tag": "advance"},
        {"function_tag": "advance"},
        {"function_tag": "advance"},
        {"function_tag": "reveal"},
    ])
    service = TensionCurveService(session)
    report = service.validate_chapter(chapter_id)

    assert report.scene_count == 4
    assert report.tagged_count == 4
    adjacent = [v for v in report.violations if v.violation_type == "adjacent_tag_repeat"]
    assert len(adjacent) == 2
    assert all("advance" in v.message for v in adjacent)


def test_no_violation_when_tags_vary(session) -> None:
    chapter_id = _seed_chapter(session, scene_briefs=[
        {"function_tag": "advance"},
        {"function_tag": "reveal"},
        {"function_tag": "advance"},
        {"function_tag": "deepen"},
    ])
    service = TensionCurveService(session)
    report = service.validate_chapter(chapter_id)
    assert report.violations == []


def test_tension_monotony_detected(session) -> None:
    chapter_id = _seed_chapter(session, scene_briefs=[
        {"tension_target": 5},
        {"tension_target": 4},
        {"tension_target": 5},
        {"tension_target": 6},
        {"tension_target": 5},
    ])
    service = TensionCurveService(session)
    report = service.validate_chapter(chapter_id)

    monotony = [v for v in report.violations if v.violation_type == "tension_monotony"]
    assert len(monotony) >= 1
    assert "medium" in monotony[0].message


def test_format_tension_prompt_returns_guidance() -> None:
    scene = SceneCard(
        scene_id="test", chapter_id="ch", scene_seq=1, scene_goal="test",
        writer_brief_json={"tension_target": 8, "function_tag": "turn"},
    )
    service = TensionCurveService.__new__(TensionCurveService)
    prompt = service.format_tension_prompt(scene)
    assert prompt is not None
    assert "8/10" in prompt
    assert "high" in prompt
    assert "turn" in prompt


def test_format_tension_prompt_none_when_no_data() -> None:
    scene = SceneCard(
        scene_id="test", chapter_id="ch", scene_seq=1, scene_goal="test",
        writer_brief_json={},
    )
    service = TensionCurveService.__new__(TensionCurveService)
    assert service.format_tension_prompt(scene) is None


def test_function_tags_vocabulary() -> None:
    assert len(FUNCTION_TAGS) == 6
    assert "advance" in FUNCTION_TAGS
    assert "turn" in FUNCTION_TAGS
    assert "breathe" in FUNCTION_TAGS
