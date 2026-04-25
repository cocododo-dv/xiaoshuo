from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorDraft,
    AuthorDraftEvent,
    ChapterMemory,
    ChapterState,
    FinalScene,
    SceneCard,
    SceneRunState,
)
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.errors import DomainError

AUTHOR_DRAFT_EVENT_TYPES = {
    "created",
    "edited",
    "candidate_inserted",
    "candidate_saved",
    "candidate_rejected",
}


class AuthorDraftService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lifecycle = AuthorLifecycleService(session)

    def current(self, object_type: str, object_id: str) -> dict[str, Any]:
        self._require_target(object_type, object_id)
        return {"draft": self.serialize_draft(self._current_row(object_type, object_id))}

    def ensure(self, object_type: str, object_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        self._require_target(object_type, object_id)
        current = self._current_row(object_type, object_id)
        if current is not None:
            return {"draft": self.serialize_draft(current)}
        source = self._source_for_target(object_type, object_id)
        draft = AuthorDraft(
            draft_id=f"author_draft_{object_type}_{object_id}_{uuid.uuid4().hex[:10]}",
            object_type=object_type,
            object_id=object_id,
            source_text_ref=source["source_text_ref"],
            content=source["content"],
            revision_no=1,
            status="current",
            created_by=actor_ref or "author_draft",
            updated_by=actor_ref or "author_draft",
        )
        self.session.add(draft)
        self.session.flush()
        self._add_event(
            draft,
            event_type="created",
            actor_ref=actor_ref,
            payload={"source_text_ref": source["source_text_ref"]},
        )
        self.session.flush()
        return {"draft": self.serialize_draft(draft)}

    def save(self, draft_id: str, payload: dict[str, Any], *, actor_ref: str = "operator") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        base_revision_no = payload.get("base_revision_no")
        if int(base_revision_no or 0) != int(draft.revision_no):
            raise DomainError(
                "AUTHOR_DRAFT_CONFLICT",
                "author draft has changed; refresh before saving",
                status_code=409,
                details={"current_revision_no": draft.revision_no},
            )
        content = payload.get("content")
        if not isinstance(content, str):
            raise DomainError("AUTHOR_DRAFT_INVALID", "content must be a string", status_code=400)
        draft.content = content
        draft.revision_no += 1
        draft.updated_by = actor_ref or draft.updated_by
        self._add_event(
            draft,
            event_type="edited",
            actor_ref=actor_ref,
            patch_id=_optional_text(payload, "patch_id"),
            revision_id=_optional_text(payload, "revision_id"),
            option_id=_optional_text(payload, "option_id"),
            note=_optional_text(payload, "note"),
            payload={"base_revision_no": base_revision_no, "revision_no": draft.revision_no},
        )
        self.session.flush()
        return {"draft": self.serialize_draft(draft)}

    def record_candidate_event(self, draft_id: str, payload: dict[str, Any], *, actor_ref: str = "operator") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        event_type = _optional_text(payload, "event_type") or ""
        if event_type not in AUTHOR_DRAFT_EVENT_TYPES - {"created", "edited"}:
            raise DomainError("AUTHOR_DRAFT_EVENT_INVALID", "candidate event type is invalid", status_code=400)
        event = self._add_event(
            draft,
            event_type=event_type,
            actor_ref=actor_ref,
            patch_id=_optional_text(payload, "patch_id"),
            revision_id=_optional_text(payload, "revision_id"),
            option_id=_optional_text(payload, "option_id"),
            note=_optional_text(payload, "note"),
            payload=payload.get("payload_json") if isinstance(payload.get("payload_json"), dict) else {},
        )
        self.session.flush()
        return {"event": self.serialize_event(event)}

    @staticmethod
    def serialize_draft(row: AuthorDraft | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "draft_id": row.draft_id,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "source_text_ref": row.source_text_ref,
            "content": row.content,
            "revision_no": row.revision_no,
            "status": row.status,
            "created_by": row.created_by,
            "updated_by": row.updated_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def serialize_event(row: AuthorDraftEvent) -> dict[str, Any]:
        return {
            "event_id": row.event_id,
            "draft_id": row.draft_id,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "event_type": row.event_type,
            "patch_id": row.patch_id,
            "revision_id": row.revision_id,
            "option_id": row.option_id,
            "note": row.note,
            "payload_json": row.payload_json or {},
            "created_by": row.created_by,
            "created_at": row.created_at,
        }

    def _require_target(self, object_type: str, object_id: str) -> None:
        if object_type == "chapter":
            self.lifecycle.require_active_chapter(object_id)
            return
        if object_type == "scene":
            self.lifecycle.require_active_scene(object_id)
            return
        raise DomainError("AUTHOR_DRAFT_TARGET_INVALID", "object_type must be scene or chapter", status_code=400)

    def _current_row(self, object_type: str, object_id: str) -> AuthorDraft | None:
        return self.session.execute(
            select(AuthorDraft)
            .where(
                AuthorDraft.object_type == object_type,
                AuthorDraft.object_id == object_id,
                AuthorDraft.status == "current",
            )
            .order_by(AuthorDraft.updated_at.desc(), AuthorDraft.draft_id.desc())
        ).scalars().first()

    def _require_draft(self, draft_id: str) -> AuthorDraft:
        draft = self.session.get(AuthorDraft, draft_id)
        if draft is None:
            raise DomainError("AUTHOR_DRAFT_NOT_FOUND", "author draft not found", status_code=404)
        if draft.status != "current":
            raise DomainError("AUTHOR_DRAFT_NOT_CURRENT", "author draft is not current", status_code=409)
        return draft

    def _source_for_target(self, object_type: str, object_id: str) -> dict[str, str]:
        if object_type == "scene":
            return self._scene_source(object_id)
        return self._chapter_source(object_id)

    def _scene_source(self, scene_id: str) -> dict[str, str]:
        scene = self.lifecycle.require_active_scene(scene_id)
        state = self.session.get(SceneRunState, scene.scene_id)
        final_row = self.session.get(FinalScene, state.current_final_scene_row_id) if state and state.current_final_scene_row_id else None
        if final_row is None:
            raise DomainError("AUTHOR_DRAFT_SOURCE_MISSING", "scene has no current final scene", status_code=409)
        return {"source_text_ref": f"final_scene:{final_row.row_id}", "content": final_row.content or ""}

    def _chapter_source(self, chapter_id: str) -> dict[str, str]:
        self.lifecycle.require_active_chapter(chapter_id)
        aggregate = self._chapter_aggregate(chapter_id)
        if aggregate is not None:
            return {"source_text_ref": f"chapter_memory:{aggregate.row_id}", "content": aggregate.content or ""}
        scenes = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        parts: list[str] = []
        for scene in scenes:
            state = self.session.get(SceneRunState, scene.scene_id)
            final_row = self.session.get(FinalScene, state.current_final_scene_row_id) if state and state.current_final_scene_row_id else None
            if final_row is not None:
                parts.append(final_row.content or "")
        if not parts:
            raise DomainError("AUTHOR_DRAFT_SOURCE_MISSING", "chapter has no manuscript text", status_code=409)
        return {"source_text_ref": f"chapter_assembled:{chapter_id}", "content": "\n".join(parts)}

    def _chapter_aggregate(self, chapter_id: str) -> ChapterMemory | None:
        state = self.session.get(ChapterState, chapter_id)
        if state is not None and state.last_final_memory_row_id:
            pointed = self.session.get(ChapterMemory, state.last_final_memory_row_id)
            if pointed is not None and pointed.chapter_id == chapter_id and pointed.aggregate_stage == "final":
                return pointed
        return self.session.execute(
            select(ChapterMemory)
            .where(
                ChapterMemory.chapter_id == chapter_id,
                ChapterMemory.aggregate_stage == "final",
                ChapterMemory.active_flag == 1,
            )
            .order_by(ChapterMemory.created_at.desc(), ChapterMemory.row_id.desc())
        ).scalars().first()

    def _add_event(
        self,
        draft: AuthorDraft,
        *,
        event_type: str,
        actor_ref: str,
        patch_id: str | None = None,
        revision_id: str | None = None,
        option_id: str | None = None,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuthorDraftEvent:
        event = AuthorDraftEvent(
            event_id=f"author_draft_event_{uuid.uuid4().hex[:12]}",
            draft_id=draft.draft_id,
            object_type=draft.object_type,
            object_id=draft.object_id,
            event_type=event_type,
            patch_id=patch_id,
            revision_id=revision_id,
            option_id=option_id,
            note=note,
            payload_json=payload or {},
            created_by=actor_ref or "author_draft",
        )
        self.session.add(event)
        return event


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
