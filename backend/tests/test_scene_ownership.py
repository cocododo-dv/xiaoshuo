from __future__ import annotations

import pytest

from novel_system.db.models import ChapterGoal, SceneCard, StoryProject
from novel_system.services.errors import DomainError
from novel_system.services.scene_ownership import require_scene_project_id


def _project(session, project_id: str) -> None:
    session.add(StoryProject(
        project_id=project_id,
        title=project_id,
        outline_text="",
        planning_mode="snowflake",
    ))
    session.flush()


def test_scene_ownership_uses_chapter_relation_not_structured_id_prefix(session) -> None:
    _project(session, "project_with_underscores")
    chapter = ChapterGoal(
        chapter_id="project_with_underscores_CH_deadbeef",
        project_id="project_with_underscores",
        chapter_goal="Authoritative parent",
    )
    session.add(chapter)
    session.flush()
    scene = SceneCard(
        scene_id="scene_without_cached_project",
        chapter_id=chapter.chapter_id,
        project_id=None,
        scene_seq=1,
        scene_goal="Resolve through chapter",
    )
    session.add(scene)
    session.flush()

    assert require_scene_project_id(session, scene) == "project_with_underscores"


def test_scene_ownership_rejects_conflicting_relations(session) -> None:
    _project(session, "project_a")
    _project(session, "project_b")
    chapter = ChapterGoal(
        chapter_id="chapter_conflict",
        project_id="project_a",
        chapter_goal="Conflict",
    )
    session.add(chapter)
    session.flush()
    scene = SceneCard(
        scene_id="scene_conflict",
        chapter_id=chapter.chapter_id,
        project_id="project_b",
        scene_seq=1,
        scene_goal="Conflict",
    )
    session.add(scene)
    session.flush()

    with pytest.raises(DomainError) as error:
        require_scene_project_id(session, scene)
    assert error.value.code == "PROJECT_OWNERSHIP_CONFLICT"


def test_scene_ownership_fails_closed_for_projectless_legacy_scene(session) -> None:
    chapter = ChapterGoal(chapter_id="legacy_chapter", chapter_goal="Legacy")
    session.add(chapter)
    session.flush()
    scene = SceneCard(
        scene_id="legacy_scene",
        chapter_id=chapter.chapter_id,
        scene_seq=1,
        scene_goal="Legacy",
    )
    session.add(scene)
    session.flush()

    with pytest.raises(DomainError) as error:
        require_scene_project_id(session, scene)
    assert error.value.code == "PROJECT_OWNERSHIP_UNRESOLVED"
