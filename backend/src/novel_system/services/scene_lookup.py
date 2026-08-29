"""场景/章节存在性校验的共享实现。

约束：
- 多数调用方契约：记录不存在或已入回收站（trashed_flag == 1）一律 404，
  错误码/文案（SCENE_NOT_FOUND / CHAPTER_NOT_FOUND）不可变。
- scene_notes / scene_deep_review_preferences 契约：入回收站需区分为
  409 SCENE_TRASHED（传 trashed_as_conflict=True），文案同样不可变。
- catalog / chapter_plan_llm / longform_tower 的带 project_id 变体签名不同，不归此模块。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, SceneCard
from novel_system.services.errors import DomainError


def require_scene(session: Session, scene_id: str, *, trashed_as_conflict: bool = False) -> SceneCard:
    scene = session.get(SceneCard, scene_id)
    if scene is None:
        raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
    if scene.trashed_flag == 1:
        if trashed_as_conflict:
            raise DomainError("SCENE_TRASHED", "scene is currently in author trash", status_code=409)
        raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
    return scene


def require_chapter(session: Session, chapter_id: str) -> ChapterGoal:
    chapter = session.get(ChapterGoal, chapter_id)
    if chapter is None or chapter.trashed_flag == 1:
        raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)
    return chapter
