"""审计 P-1 回归：目录冷启动章必须具备完整运行时状态行。

历史缺陷：catalog.create_chapter 只建 ChapterGoal 不建 ChapterState，
场景 run 通过全部 QC 后在归档段（archiver）/ 章聚合段（aggregator）对
``session.get(ChapterState, …)`` 的结果裸解引用 → AttributeError → 500
且整跑回滚（LLM 成稿丢失）。
"""

from __future__ import annotations

from novel_system.db.models import (
    ChapterState,
    FinalScene,
    SceneMemory,
    SceneRunState,
    StoryProject,
)
from novel_system.services.archiver import Archiver
from novel_system.services.aggregator import Aggregator
from novel_system.services.catalog import CatalogService
from novel_system.services.chapter_state import ensure_chapter_state


def _make_project(session, project_id: str = "proj_cold") -> StoryProject:
    project = StoryProject(
        project_id=project_id,
        title="冷启动",
        outline_text="outline",
        planning_mode="snowflake",
    )
    session.add(project)
    session.flush()
    return project


def test_catalog_create_chapter_creates_chapter_state(session):
    project = _make_project(session)
    CatalogService(session).create_chapter(project.project_id, {"title": "第一章"})
    session.flush()
    # create_chapter 的返回形状不作强假设：直接断言库里每个章都有状态行
    from novel_system.db.models import ChapterGoal

    chapters = session.query(ChapterGoal).filter(ChapterGoal.project_id == project.project_id).all()
    assert chapters, "catalog 应创建至少一个章"
    for chapter in chapters:
        state = session.get(ChapterState, chapter.chapter_id)
        assert state is not None, f"冷启动章 {chapter.chapter_id} 缺少 ChapterState 运行时状态行"
        assert state.aggregate_block_reason == "none"


def test_archiver_survives_missing_chapter_state(session):
    """存量库中已存在的无状态行章：归档段补建而不是 None 解引用。"""
    session.add(
        FinalScene(
            row_id="fs_cold_1",
            scene_id="scene_cold_1",
            chapter_id="chapter_without_state",
            content="正文",
            source_bundle_id="bundle_x",
            source_bundle_hash="hash_x",
        )
    )
    session.add(SceneRunState(scene_id="scene_cold_1"))
    session.flush()

    result = Archiver(session).archive_final_scene("scene_cold_1", "fs_cold_1")

    assert result["scene_status"] == "archived"
    state = session.get(ChapterState, "chapter_without_state")
    assert state is not None
    assert state.chapter_passed_scene_count == 1
    memory = (
        session.query(SceneMemory)
        .filter(SceneMemory.scene_id == "scene_cold_1", SceneMemory.active_flag == 1)
        .one()
    )
    assert memory.content == "正文"


def test_aggregator_final_aggregate_survives_missing_chapter_state(session):
    result = Aggregator(session).run_final_aggregate("chapter_without_state_2")
    # 无场景记忆 → no_op，但不允许 AttributeError；状态行应已补建
    assert result["status"] == "no_op"
    assert session.get(ChapterState, "chapter_without_state_2") is not None


def test_ensure_chapter_state_is_idempotent(session):
    first = ensure_chapter_state(session, "chapter_idem")
    first.chapter_passed_scene_count = 3
    session.flush()
    second = ensure_chapter_state(session, "chapter_idem")
    assert second is first or second.chapter_passed_scene_count == 3
