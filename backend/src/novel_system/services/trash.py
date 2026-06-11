"""FE-ALIGN Phase 4: 回收站 —— 作品级软删 + 三级（作品/章/场景）统一列表。

章/场景级沿用既有 AuthorLifecycleService（trashed_flag 软删，同一机制）；
本服务补：作品级软删/恢复（级联只动可见性——子数据不动，列表查询过滤）、
统一回收站列表、永久清除（D3：仅手动，不做自动清理）。

条目 id 约定："work:{project_id}" / "chapter:{chapter_id}" / "scene:{scene_id}"。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorDraft,
    AuthorDraftEvent,
    ChapterAuditFinding,
    ChapterContract,
    ChapterGoal,
    ChapterState,
    LibraryEntity,
    LibraryRelation,
    LongformAnchor,
    OutlinePlan,
    ProjectWritingStats,
    SceneCard,
    SceneRunState,
    SnowflakeArtifact,
    SnowflakeAssistantTurn,
    SnowflakeCharacterPlan,
    SnowflakeScenePlan,
    SnowflakeSceneTriageItem,
    SnowflakeStepRun,
    StoryProject,
    utcnow,
)
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.catalog import chapter_title, scene_title
from novel_system.services.errors import DomainError


class TrashService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._lifecycle = AuthorLifecycleService(session)

    # ---- 作品级 ----

    def trash_project(self, project_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        project = self._require_project(project_id, allow_trashed=True)
        if project.trashed_flag != 1:
            project.trashed_flag = 1
            project.trashed_at = utcnow()
            project.trashed_by = actor_ref
            self.session.flush()
        return {"project_id": project_id, "trashed": True}

    def restore_project(self, project_id: str) -> dict[str, Any]:
        project = self._require_project(project_id, allow_trashed=True)
        if project.trashed_flag == 1:
            project.trashed_flag = 0
            project.trashed_at = None
            project.trashed_by = None
            self.session.flush()
        return {"project_id": project_id, "trashed": False}

    # ---- 统一列表 ----

    def list_trash(self, project_id: str | None = None) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        # 全局桶：被删除的整部作品（不随作品命名空间）
        works = self.session.execute(
            select(StoryProject).where(StoryProject.trashed_flag == 1)
        ).scalars().all()
        for project in works:
            items.append(
                {
                    "id": f"work:{project.project_id}",
                    "kind": "work",
                    "title": project.title,
                    "removed_at": project.trashed_at,
                    "restorable": True,
                }
            )
        if project_id:
            chapters = self.session.execute(
                select(ChapterGoal).where(
                    ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 1
                )
            ).scalars().all()
            for chapter in chapters:
                items.append(
                    {
                        "id": f"chapter:{chapter.chapter_id}",
                        "kind": "chapter",
                        "title": chapter_title(chapter),
                        "removed_at": chapter.trashed_at,
                        "restorable": True,
                    }
                )
            scenes = self.session.execute(
                select(SceneCard).where(
                    SceneCard.project_id == project_id, SceneCard.trashed_flag == 1
                )
            ).scalars().all()
            trashed_chapter_ids = {c.chapter_id for c in chapters}
            for scene in scenes:
                items.append(
                    {
                        "id": f"scene:{scene.scene_id}",
                        "kind": "scene",
                        "title": scene_title(scene),
                        "removed_at": scene.trashed_at,
                        # 所在章也被删时，恢复场景会被既有服务阻止（先恢复章）
                        "restorable": scene.chapter_id not in trashed_chapter_ids,
                        "chapter_id": scene.chapter_id,
                    }
                )
        items.sort(key=lambda item: item.get("removed_at") or "", reverse=True)
        return {"items": items}

    # ---- 章/场景级软删（v2 catalog 桥接；校验归属后走既有 lifecycle 服务） ----

    def trash_chapter_in_project(self, project_id: str, chapter_id: str, *, actor_ref: str) -> dict[str, Any]:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or chapter.project_id != project_id:
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found in project", status_code=404)
        result = self._lifecycle.trash_chapters([chapter_id], actor_ref)
        return self._lifecycle_result(f"chapter:{chapter_id}", result)

    def trash_scene_in_project(self, project_id: str, scene_id: str, *, actor_ref: str) -> dict[str, Any]:
        scene = self.session.get(SceneCard, scene_id)
        owner = scene.project_id if scene else None
        if scene is not None and not owner:
            chapter = self.session.get(ChapterGoal, scene.chapter_id)
            owner = chapter.project_id if chapter else None
        if scene is None or owner != project_id:
            raise DomainError("SCENE_NOT_FOUND", "scene not found in project", status_code=404)
        result = self._lifecycle.trash_scenes([scene_id], actor_ref)
        return self._lifecycle_result(f"scene:{scene_id}", result)

    # ---- 恢复 / 永久清除（按条目 id 分发） ----

    def restore_entry(self, entry_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        kind, target = self._parse_entry(entry_id)
        if kind == "work":
            return self.restore_project(target)
        if kind == "chapter":
            result = self._lifecycle.restore_chapters([target])
            return self._lifecycle_result(entry_id, result)
        result = self._lifecycle.restore_scenes([target])
        return self._lifecycle_result(entry_id, result)

    def purge_entry(self, entry_id: str) -> dict[str, Any]:
        kind, target = self._parse_entry(entry_id)
        if kind == "work":
            return self.purge_project(target)
        if kind == "chapter":
            result = self._lifecycle.purge_chapters([target])
            return self._lifecycle_result(entry_id, result)
        result = self._lifecycle.purge_scenes([target])
        return self._lifecycle_result(entry_id, result)

    def purge_project(self, project_id: str) -> dict[str, Any]:
        """整部作品永久清除（D3 手动）。删除项目本体与其 FE 域子数据。"""
        project = self._require_project(project_id, allow_trashed=True)
        if project.trashed_flag != 1:
            raise DomainError(
                "PROJECT_NOT_TRASHED", "project must be trashed before purge", status_code=409
            )
        chapter_ids = [
            row
            for row in self.session.execute(
                select(ChapterGoal.chapter_id).where(ChapterGoal.project_id == project_id)
            ).scalars().all()
        ]
        scene_ids = [
            row
            for row in self.session.execute(
                select(SceneCard.scene_id).where(SceneCard.project_id == project_id)
            ).scalars().all()
        ]
        draft_ids = []
        if scene_ids or chapter_ids:
            draft_ids = [
                row
                for row in self.session.execute(
                    select(AuthorDraft.draft_id).where(
                        (
                            (AuthorDraft.object_type == "scene") & AuthorDraft.object_id.in_(scene_ids or [""])
                        )
                        | (
                            (AuthorDraft.object_type == "chapter") & AuthorDraft.object_id.in_(chapter_ids or [""])
                        )
                        | ((AuthorDraft.object_type == "project") & (AuthorDraft.object_id == project_id))
                    )
                ).scalars().all()
            ]
        if draft_ids:
            self.session.execute(delete(AuthorDraftEvent).where(AuthorDraftEvent.draft_id.in_(draft_ids)))
            self.session.execute(delete(AuthorDraft).where(AuthorDraft.draft_id.in_(draft_ids)))
        if scene_ids:
            self.session.execute(delete(SceneRunState).where(SceneRunState.scene_id.in_(scene_ids)))
            self.session.execute(delete(SceneCard).where(SceneCard.scene_id.in_(scene_ids)))
        if chapter_ids:
            self.session.execute(delete(ChapterState).where(ChapterState.chapter_id.in_(chapter_ids)))
            self.session.execute(delete(ChapterGoal).where(ChapterGoal.chapter_id.in_(chapter_ids)))
        from novel_system.db.models import StoryCharacter, TimelineEvent

        for model in (
            SnowflakeSceneTriageItem,
            SnowflakeScenePlan,
            SnowflakeCharacterPlan,
            SnowflakeAssistantTurn,
            SnowflakeStepRun,
            SnowflakeArtifact,
            ChapterAuditFinding,
            ChapterContract,
            LongformAnchor,
            LibraryRelation,
            LibraryEntity,
            TimelineEvent,
            StoryCharacter,
            OutlinePlan,
            ProjectWritingStats,
        ):
            self.session.execute(delete(model).where(model.project_id == project_id))
        self.session.delete(project)
        self.session.flush()
        return {"project_id": project_id, "purged": True}

    # ---- internals ----

    def _require_project(self, project_id: str, *, allow_trashed: bool = False) -> StoryProject:
        project = self.session.get(StoryProject, project_id)
        if project is None or (not allow_trashed and project.trashed_flag == 1):
            raise DomainError("PROJECT_NOT_FOUND", "project not found", status_code=404)
        return project

    @staticmethod
    def _parse_entry(entry_id: str) -> tuple[str, str]:
        kind, _, target = str(entry_id or "").partition(":")
        if kind not in {"work", "chapter", "scene"} or not target:
            raise DomainError("TRASH_ENTRY_INVALID", "invalid trash entry id", status_code=400)
        return kind, target

    @staticmethod
    def _lifecycle_result(entry_id: str, result: dict[str, Any]) -> dict[str, Any]:
        blocked = list(result.get("blocked") or [])
        if blocked:
            raise DomainError(
                "TRASH_OPERATION_BLOCKED",
                str(blocked[0].get("message") or "operation blocked"),
                status_code=409,
                details={"entry_id": entry_id, "blocked": blocked},
            )
        return {"entry_id": entry_id, "processed": result.get("processed") or []}
