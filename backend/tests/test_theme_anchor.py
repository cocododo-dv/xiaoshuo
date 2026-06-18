"""Tests for controlling idea & theme validation — blueprint §12."""
from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    SceneCard,
    WorkProfile,
)
from novel_system.services.theme_anchor import (
    EXPRESSION_SPECTRUM,
    ThemeAnchorService,
    _extract_theme_keywords,
)


def _seed_project_with_scenes(session) -> str:
    session.add(WorkProfile(
        profile_id="wp_ci_theme01",
        scope_type="global",
        scope_ref_id="THEME01",
        profile_key="controlling_idea",
        display_name="控制性理念",
        profile_json={"idea": "残缺本身也可以是完整的"},
        status="active",
    ))
    session.add(ChapterGoal(chapter_id="THEME01_CH01", planned_scene_count=3, chapter_goal="test"))
    session.add(ChapterState(chapter_id="THEME01_CH01", current_phase="drafting"))
    session.add(SceneCard(
        scene_id="THEME01_CH01_SC01", chapter_id="THEME01_CH01", scene_seq=1,
        scene_goal="主角面对残缺的身体，选择接受而非逃避",
        exit_change="角色第一次承认自己的不完整",
    ))
    session.add(SceneCard(
        scene_id="THEME01_CH01_SC02", chapter_id="THEME01_CH01", scene_seq=2,
        scene_goal="日常场景：角色在市场买菜",
        exit_change="nothing changes",
    ))
    session.add(SceneCard(
        scene_id="THEME01_CH01_SC03", chapter_id="THEME01_CH01", scene_seq=3,
        scene_goal="角色为保护朋友牺牲安全",
        exit_change="付出代价换来信任",
    ))
    session.commit()
    return "THEME01"


def test_get_set_controlling_idea(session) -> None:
    service = ThemeAnchorService(session)
    assert service.get_controlling_idea("THEME02") is None

    service.set_controlling_idea("THEME02", "一个人发现残缺本身也可以是完整的")
    session.commit()

    assert service.get_controlling_idea("THEME02") == "一个人发现残缺本身也可以是完整的"


def test_scene_relevance_detects_theme_keywords(session) -> None:
    _seed_project_with_scenes(session)
    service = ThemeAnchorService(session)
    scene = session.get(SceneCard, "THEME01_CH01_SC01")

    check = service.check_scene_relevance(scene, "残缺本身也可以是完整的")
    assert check.relevant is True
    assert "残缺" in check.connection or "完整" in check.connection


def test_scene_relevance_detects_cost_as_implicit_theme(session) -> None:
    _seed_project_with_scenes(session)
    service = ThemeAnchorService(session)
    scene = session.get(SceneCard, "THEME01_CH01_SC03")

    check = service.check_scene_relevance(scene, "残缺本身也可以是完整的")
    assert check.relevant is True


def test_scene_relevance_flags_irrelevant(session) -> None:
    _seed_project_with_scenes(session)
    service = ThemeAnchorService(session)
    scene = session.get(SceneCard, "THEME01_CH01_SC02")

    check = service.check_scene_relevance(scene, "残缺本身也可以是完整的")
    assert check.relevant is False
    assert check.suggestion != ""


def test_validate_chapter_theme_pressure(session) -> None:
    _seed_project_with_scenes(session)
    service = ThemeAnchorService(session)

    report = service.validate_chapter_theme_pressure("THEME01", "THEME01_CH01")
    assert report.scene_count == 3
    assert report.checked_count == 3
    assert len(report.irrelevant_scenes) >= 1
    assert "THEME01_CH01_SC02" in report.irrelevant_scenes


def test_format_theme_prompt(session) -> None:
    _seed_project_with_scenes(session)
    service = ThemeAnchorService(session)

    prompt = service.format_theme_prompt("THEME01")
    assert prompt is not None
    assert "残缺" in prompt
    assert "Controlling Idea" in prompt
    assert "Do NOT state the theme directly" in prompt


def test_format_theme_prompt_none_when_no_idea(session) -> None:
    service = ThemeAnchorService(session)
    assert service.format_theme_prompt("THEME_NOEXIST") is None


def test_extract_theme_keywords() -> None:
    keywords = _extract_theme_keywords("残缺本身也可以是完整的")
    assert any("残" in kw or "完" in kw for kw in keywords)
    assert all("的" not in kw and "是" not in kw for kw in keywords)


def test_expression_spectrum_has_five_levels() -> None:
    assert len(EXPRESSION_SPECTRUM) == 5
