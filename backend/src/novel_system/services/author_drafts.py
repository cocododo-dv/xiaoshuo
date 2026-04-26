from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorDraft,
    AuthorDraftEvent,
    AuthorPreferenceProfile,
    AuthorStructureCandidate,
    ChapterMemory,
    ChapterState,
    FinalScene,
    PassagePatchCandidate,
    SceneCard,
    SceneRunState,
)
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.llm_task_runner import LLMNodeExecutionError, LLMNodeRunner
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.services.writer_review import (
    empty_chapter_writer_brief,
    empty_scene_writer_brief,
    normalize_chapter_writer_brief,
    normalize_scene_writer_brief,
)

AUTHOR_DRAFT_EVENT_TYPES = {
    "created",
    "edited",
    "candidate_inserted",
    "candidate_saved",
    "candidate_rejected",
}

DESK_DEFAULT_MODE = "write_first"


class AuthorDraftService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lifecycle = AuthorLifecycleService(session)

    def current(self, object_type: str, object_id: str) -> dict[str, Any]:
        self._require_target(object_type, object_id)
        draft = self._current_row(object_type, object_id)
        if draft is None:
            return {"draft": None}
        return self._draft_response(draft)

    def ensure(self, object_type: str, object_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        self._require_target(object_type, object_id)
        current = self._current_row(object_type, object_id)
        if current is not None:
            return self._draft_response(current)
        try:
            source = self._source_for_target(object_type, object_id)
        except DomainError as exc:
            if exc.code != "AUTHOR_DRAFT_SOURCE_MISSING":
                raise
            source = self._blank_source_for_target(object_type, object_id)
        draft = self._create_draft_row(object_type, object_id, source=source, actor_ref=actor_ref)
        return self._draft_response(draft)

    def ensure_blank(self, object_type: str, object_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        self._require_target(object_type, object_id)
        current = self._current_row(object_type, object_id)
        if current is not None:
            return self._draft_response(current)
        source = self._blank_source_for_target(object_type, object_id)
        draft = self._create_draft_row(object_type, object_id, source=source, actor_ref=actor_ref)
        return self._draft_response(draft)

    def _create_draft_row(
        self,
        object_type: str,
        object_id: str,
        *,
        source: dict[str, str],
        actor_ref: str,
    ) -> AuthorDraft:
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
        return draft

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
        return self._draft_response(draft)

    def derive_from_generation(self, draft_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        source = self._source_for_target(draft.object_type, draft.object_id)
        draft.content = source["content"]
        draft.source_text_ref = source["source_text_ref"]
        draft.revision_no += 1
        draft.updated_by = actor_ref or draft.updated_by
        self._add_event(
            draft,
            event_type="edited",
            actor_ref=actor_ref,
            note="derived from current generation output",
            payload={
                "source_text_ref": source["source_text_ref"],
                "source_layer": _source_layer(source["source_text_ref"]),
                "revision_no": draft.revision_no,
            },
        )
        self.session.flush()
        return self._draft_response(draft)

    def apply_patch_option(self, draft_id: str, payload: dict[str, Any], *, actor_ref: str = "operator") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        patch_id = _required_text(payload, "patch_id")
        patch = self.session.get(PassagePatchCandidate, patch_id)
        if patch is None:
            raise DomainError("PASSAGE_PATCH_NOT_FOUND", "passage patch candidate not found", status_code=404)
        if patch.source_draft_id and patch.source_draft_id != draft.draft_id:
            raise DomainError("AUTHOR_DRAFT_PATCH_MISMATCH", "patch candidate belongs to a different author draft", status_code=409)
        if patch.object_type != draft.object_type or patch.object_id != draft.object_id:
            raise DomainError("AUTHOR_DRAFT_PATCH_TARGET_MISMATCH", "patch candidate target does not match author draft", status_code=409)
        option_id = _optional_text(payload, "option_id")
        option = _patch_option(patch, option_id)
        source_excerpt = _optional_text(payload, "source_excerpt") or str(option.get("source_excerpt") or patch.source_excerpt or "")
        replacement = str(option.get("replacement_text") or "").strip()
        if not replacement:
            raise DomainError("AUTHOR_DRAFT_PATCH_OPTION_INVALID", "patch option has no replacement text", status_code=400)
        draft.content = _replace_or_append(draft.content or "", source_excerpt, replacement)
        draft.revision_no += 1
        draft.updated_by = actor_ref or draft.updated_by
        patch.inserted_into_author_draft = 1
        selected_option_id = str(option.get("option_id") or option_id or "")
        self._add_event(
            draft,
            event_type="candidate_inserted",
            actor_ref=actor_ref,
            patch_id=patch.patch_id,
            option_id=selected_option_id,
            note=_optional_text(payload, "note") or "patch option inserted into author draft",
            payload={
                "applied_to": "author_draft",
                "source_excerpt": source_excerpt,
                "replacement_text": replacement,
                "label": option.get("label") or option.get("tone") or "",
                "candidate_category": patch.candidate_category,
                "target_range": patch.target_range_json,
                "revision_strategy": patch.revision_strategy,
                "preference_tags": patch.preference_tags_json or [],
                "revision_no": draft.revision_no,
            },
        )
        self.session.flush()
        return self._draft_response(draft)

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

    def events(self, draft_id: str) -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        rows = self.session.execute(
            select(AuthorDraftEvent)
            .where(AuthorDraftEvent.draft_id == draft.draft_id)
            .order_by(AuthorDraftEvent.created_at.asc(), AuthorDraftEvent.event_id.asc())
        ).scalars().all()
        return {
            "draft_id": draft.draft_id,
            "object_type": draft.object_type,
            "object_id": draft.object_id,
            "revision_no": draft.revision_no,
            "events": [self.serialize_event(row) for row in rows],
        }

    def _draft_response(self, draft: AuthorDraft) -> dict[str, Any]:
        return {
            "draft": self.serialize_draft(draft),
            **self._desk_context(draft),
        }

    def _desk_context(self, draft: AuthorDraft) -> dict[str, Any]:
        runtime_final_ref = None
        aggregate_ref = None
        try:
            source = self._source_for_target(draft.object_type, draft.object_id)
            if source["source_text_ref"].startswith("final_scene:"):
                runtime_final_ref = source["source_text_ref"]
            elif source["source_text_ref"].startswith("chapter_memory:"):
                aggregate_ref = source["source_text_ref"]
        except DomainError:
            pass
        if draft.object_type == "scene":
            scene = self.lifecycle.require_active_scene(draft.object_id)
            aggregate = self._chapter_aggregate(scene.chapter_id)
            if aggregate is not None:
                aggregate_ref = f"chapter_memory:{aggregate.row_id}"
        else:
            aggregate = self._chapter_aggregate(draft.object_id)
            if aggregate is not None:
                aggregate_ref = f"chapter_memory:{aggregate.row_id}"
        preference = self.session.execute(
            select(AuthorPreferenceProfile)
            .where(AuthorPreferenceProfile.scope_type == "global", AuthorPreferenceProfile.scope_ref_id == "global")
            .order_by(AuthorPreferenceProfile.updated_at.desc(), AuthorPreferenceProfile.profile_id.desc())
        ).scalars().first()
        return {
            "draft_mode": draft.object_type,
            "desk_mode": DESK_DEFAULT_MODE,
            "source_layer": _source_layer(draft.source_text_ref),
            "runtime_final_ref": runtime_final_ref,
            "aggregate_ref": aggregate_ref,
            "open_structure_candidates": [
                self.serialize_structure_candidate(row)
                for row in self.session.execute(
                    select(AuthorStructureCandidate)
                    .where(
                        AuthorStructureCandidate.object_type == draft.object_type,
                        AuthorStructureCandidate.object_id == draft.object_id,
                        AuthorStructureCandidate.status == "candidate",
                    )
                    .order_by(AuthorStructureCandidate.created_at.desc(), AuthorStructureCandidate.candidate_id.desc())
                ).scalars().all()
            ],
            "open_patch_candidates": [
                _serialize_patch_candidate(row)
                for row in self.session.execute(
                    select(PassagePatchCandidate)
                    .where(
                        PassagePatchCandidate.object_type == draft.object_type,
                        PassagePatchCandidate.object_id == draft.object_id,
                        PassagePatchCandidate.status == "candidate",
                    )
                    .order_by(PassagePatchCandidate.created_at.desc(), PassagePatchCandidate.patch_id.desc())
                ).scalars().all()
            ],
            "author_preference_summary": preference.summary_json if preference is not None else {},
        }

    def extract_structure(self, draft_id: str, *, actor_ref: str = "operator") -> dict[str, Any]:
        draft = self._require_draft(draft_id)
        target = self._target_payload(draft.object_type, draft.object_id)
        snapshot = _structure_extract_snapshot(draft, target)
        prompt = PromptBuilder().build(snapshot, "author_structure_extract")
        bundle_hash = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
        runner = LLMNodeRunner(self.session)
        try:
            node_result = runner.run(
                scene_id=target["scene_id"] or draft.object_id,
                chapter_id=target["chapter_id"] or draft.object_id,
                bundle_id=f"author_draft:{draft.draft_id}",
                bundle_hash=bundle_hash,
                node_id="author_structure_extract",
                step="author_structure_extract",
                prompt=prompt,
                user_prompt=_structure_extract_user_prompt(prompt["user_prompt"], draft=draft, target=target),
                offline_client_factory=lambda: OfflineAuthorStructureExtractClient(draft=draft, target=target),
                source_draft_row_id=draft.draft_id,
                source_draft_content=draft.content,
            )
        except LLMNodeExecutionError as exc:
            raise DomainError(
                "AUTHOR_STRUCTURE_EXTRACT_FAILED",
                f"author structure extraction failed: {exc.message}",
                status_code=502,
                details={"llm_call_id": exc.llm_call_id, "error_code": exc.error_code},
            ) from exc

        normalized = _normalize_structure_payload(node_result.response.structured_output, draft=draft, target=target)
        for row in self.session.execute(
            select(AuthorStructureCandidate).where(
                AuthorStructureCandidate.object_type == draft.object_type,
                AuthorStructureCandidate.object_id == draft.object_id,
                AuthorStructureCandidate.status == "candidate",
            )
        ).scalars().all():
            row.status = "superseded"
        candidate = AuthorStructureCandidate(
            candidate_id=f"author_structure_{draft.object_type}_{draft.object_id}_{uuid.uuid4().hex[:10]}",
            object_type=draft.object_type,
            object_id=draft.object_id,
            chapter_id=target["chapter_id"],
            scene_id=target["scene_id"],
            source_draft_id=draft.draft_id,
            source_text_ref=f"author_draft:{draft.draft_id}",
            extraction_llm_call_id=node_result.llm_call_id,
            candidate_brief_json=normalized["candidate_brief"],
            uncertainty_notes_json=normalized["uncertainty_notes"],
            rationale=normalized["rationale"],
            created_by=actor_ref or "author_structure_extract",
        )
        self.session.add(candidate)
        self.session.flush()
        return {"candidate": self.serialize_structure_candidate(candidate)}

    def apply_structure_candidate(
        self,
        candidate_id: str,
        payload: dict[str, Any] | None = None,
        *,
        actor_ref: str = "operator",
    ) -> dict[str, Any]:
        candidate = self._require_structure_candidate(candidate_id)
        if candidate.status != "candidate":
            raise DomainError("AUTHOR_STRUCTURE_CANDIDATE_CLOSED", "structure candidate is not open", status_code=409)
        note = _optional_text(payload or {}, "note")
        if candidate.object_type == "scene":
            scene = self.lifecycle.require_active_scene(candidate.object_id)
            current = normalize_scene_writer_brief(scene.writer_brief_json)
            scene.writer_brief_json = _merge_briefs(current, candidate.candidate_brief_json)
        else:
            chapter = self.lifecycle.require_active_chapter(candidate.object_id)
            current = normalize_chapter_writer_brief(chapter.writer_brief_json)
            chapter.writer_brief_json = _merge_briefs(current, candidate.candidate_brief_json)
        candidate.status = "accepted"
        candidate.author_decision = "accepted"
        candidate.author_decision_note = note or candidate.author_decision_note
        self.session.flush()
        return {"candidate": self.serialize_structure_candidate(candidate)}

    def reject_structure_candidate(
        self,
        candidate_id: str,
        payload: dict[str, Any] | None = None,
        *,
        actor_ref: str = "operator",
    ) -> dict[str, Any]:
        candidate = self._require_structure_candidate(candidate_id)
        if candidate.status != "candidate":
            raise DomainError("AUTHOR_STRUCTURE_CANDIDATE_CLOSED", "structure candidate is not open", status_code=409)
        candidate.status = "rejected"
        candidate.author_decision = "rejected"
        candidate.author_decision_note = _optional_text(payload or {}, "note") or candidate.author_decision_note
        self.session.flush()
        return {"candidate": self.serialize_structure_candidate(candidate)}

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

    @staticmethod
    def serialize_structure_candidate(row: AuthorStructureCandidate) -> dict[str, Any]:
        return {
            "candidate_id": row.candidate_id,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "chapter_id": row.chapter_id,
            "scene_id": row.scene_id,
            "source_draft_id": row.source_draft_id,
            "source_text_ref": row.source_text_ref,
            "extraction_llm_call_id": row.extraction_llm_call_id,
            "candidate_brief": row.candidate_brief_json or {},
            "uncertainty_notes": row.uncertainty_notes_json or [],
            "rationale": row.rationale,
            "status": row.status,
            "author_decision": row.author_decision,
            "author_decision_note": row.author_decision_note,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
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

    def _blank_source_for_target(self, object_type: str, object_id: str) -> dict[str, str]:
        if object_type == "chapter":
            self.lifecycle.require_active_chapter(object_id)
            return {"source_text_ref": f"author_blank:chapter:{object_id}", "content": ""}
        scene = self.lifecycle.require_active_scene(object_id)
        chapter = self.lifecycle.require_active_chapter(scene.chapter_id)
        return {
            "source_text_ref": f"scene_card:{scene.scene_id}:blank",
            "content": _scene_blank_scaffold(scene, chapter_goal=chapter.chapter_goal),
        }

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

    def _target_payload(self, object_type: str, object_id: str) -> dict[str, Any]:
        if object_type == "scene":
            scene = self.lifecycle.require_active_scene(object_id)
            chapter = self.lifecycle.require_active_chapter(scene.chapter_id)
            return {
                "object_type": "scene",
                "object_id": scene.scene_id,
                "chapter_id": scene.chapter_id,
                "scene_id": scene.scene_id,
                "chapter_goal": chapter.chapter_goal or "",
                "chapter_writer_brief": normalize_chapter_writer_brief(chapter.writer_brief_json),
                "scene_card": {
                    "scene_goal": scene.scene_goal or "",
                    "beats": scene.beats_json or [],
                    "location": scene.location or "",
                    "exit_change": scene.exit_change or "",
                    "hook": scene.hook or "",
                },
                "current_writer_brief": normalize_scene_writer_brief(scene.writer_brief_json),
            }
        chapter = self.lifecycle.require_active_chapter(object_id)
        return {
            "object_type": "chapter",
            "object_id": chapter.chapter_id,
            "chapter_id": chapter.chapter_id,
            "scene_id": None,
            "chapter_goal": chapter.chapter_goal or "",
            "chapter_writer_brief": normalize_chapter_writer_brief(chapter.writer_brief_json),
            "scene_card": {},
            "current_writer_brief": normalize_chapter_writer_brief(chapter.writer_brief_json),
        }

    def _require_structure_candidate(self, candidate_id: str) -> AuthorStructureCandidate:
        row = self.session.get(AuthorStructureCandidate, candidate_id)
        if row is None:
            raise DomainError("AUTHOR_STRUCTURE_CANDIDATE_NOT_FOUND", "structure candidate not found", status_code=404)
        return row


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise DomainError("AUTHOR_DRAFT_INVALID", f"{key} is required", status_code=400)
    return value


def _source_layer(source_text_ref: str | None) -> str:
    value = str(source_text_ref or "")
    if value.startswith("author_blank:") or value.endswith(":blank"):
        return "author_blank"
    if value.startswith("final_scene:"):
        return "ai_draft"
    if value.startswith("chapter_memory:") or value.startswith("chapter_assembled:"):
        return "runtime_aggregate"
    if value.startswith("author_draft:"):
        return "author_draft"
    return "unknown"


def _patch_option(row: PassagePatchCandidate, option_id: str | None) -> dict[str, Any]:
    options = row.replacement_options_json or []
    if not isinstance(options, list) or not options:
        raise DomainError("AUTHOR_DRAFT_PATCH_OPTION_NOT_FOUND", "patch candidate has no replacement options", status_code=404)
    if option_id:
        for option in options:
            if isinstance(option, dict) and str(option.get("option_id") or "") == option_id:
                return option
        raise DomainError("AUTHOR_DRAFT_PATCH_OPTION_NOT_FOUND", "patch option not found", status_code=404)
    first = options[0]
    if not isinstance(first, dict):
        raise DomainError("AUTHOR_DRAFT_PATCH_OPTION_INVALID", "patch option must be an object", status_code=400)
    return first


def _replace_or_append(content: str, source_excerpt: str, replacement: str) -> str:
    current = str(content or "")
    needle = str(source_excerpt or "").strip()
    if needle and needle in current:
        return current.replace(needle, replacement, 1)
    trimmed = current.rstrip()
    return f"{trimmed}\n\n{replacement}" if trimmed else replacement


def _serialize_patch_candidate(row: PassagePatchCandidate) -> dict[str, Any]:
    return {
        "patch_id": row.patch_id,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "chapter_id": row.chapter_id,
        "scene_id": row.scene_id,
        "source_text_ref": row.source_text_ref,
        "target_text_ref": row.target_text_ref,
        "source_draft_id": row.source_draft_id,
        "source_excerpt": row.source_excerpt,
        "issue_dimension": row.issue_dimension,
        "candidate_category": row.candidate_category,
        "target_range": row.target_range_json or None,
        "revision_strategy": row.revision_strategy,
        "preference_tags": row.preference_tags_json or [],
        "inserted_into_author_draft": bool(row.inserted_into_author_draft),
        "replacement_options": row.replacement_options_json or [],
        "rationale": row.rationale,
        "status": row.status,
        "author_decision": row.author_decision,
        "selected_option_id": row.selected_option_id,
        "author_decision_note": row.author_decision_note,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class OfflineAuthorStructureExtractClient:
    def __init__(self, *, draft: AuthorDraft, target: dict[str, Any]) -> None:
        self.draft = draft
        self.target = target

    def generate(self, request: LLMRequest) -> LLMResponse:
        structured_output = _offline_structure_payload(self.draft, self.target)
        return LLMResponse(
            request_id=f"offline_author_structure_{uuid.uuid4().hex[:8]}",
            provider="offline_deterministic",
            model=request.model,
            text=json.dumps(structured_output, ensure_ascii=False),
            structured_output=structured_output,
            response_format=request.response_format,
            raw_response={"id": "offline_author_structure_extract"},
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            finish_reason="offline_fallback",
        )


def _scene_blank_scaffold(scene: SceneCard, *, chapter_goal: str) -> str:
    parts: list[str] = []
    if chapter_goal:
        parts.append(f"【章节目标】{chapter_goal}")
    if scene.scene_goal:
        parts.append(f"【场景目标】{scene.scene_goal}")
    if scene.location:
        parts.append(f"【地点】{scene.location}")
    beats = [str(item).strip() for item in (scene.beats_json or []) if str(item).strip()]
    if beats:
        parts.append(f"【节拍】{' / '.join(beats)}")
    if scene.exit_change:
        parts.append(f"【结尾变化】{scene.exit_change}")
    if scene.hook:
        parts.append(f"【读者钩子】{scene.hook}")
    return "\n".join(parts)


def _structure_extract_snapshot(draft: AuthorDraft, target: dict[str, Any]) -> dict[str, Any]:
    inline_digests = {
        "scene_summary": json.dumps(
            {
                "object_type": draft.object_type,
                "object_id": draft.object_id,
                "source_draft_id": draft.draft_id,
                "source_text_ref": f"author_draft:{draft.draft_id}",
                "author_draft": draft.content or "",
                "current_writer_brief": target.get("current_writer_brief") or {},
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "chapter_goal": str(target.get("chapter_goal") or ""),
    }
    if target.get("object_type") == "scene":
        inline_digests["scene_card"] = json.dumps(target.get("scene_card") or {}, ensure_ascii=False, sort_keys=True)
        inline_digests["chapter_writer_brief"] = json.dumps(target.get("chapter_writer_brief") or {}, ensure_ascii=False, sort_keys=True)
    return {
        "contract_version": "AUTHOR_STRUCTURE_EXTRACT_SOURCE_v1",
        "stage_allowlist_name": "author_structure_extract",
        "scene_id": target.get("scene_id") or "",
        "chapter_id": target.get("chapter_id") or "",
        "source_version_refs": {
            "source_draft_id": draft.draft_id,
            "object_type": draft.object_type,
            "object_id": draft.object_id,
        },
        "resolved_ref_ids": {},
        "ordered_injections": [
            {"slot": "author_draft", "ref_id": draft.draft_id, "digest_key": "scene_summary"},
            {"slot": "chapter_goal", "ref_id": target.get("chapter_id") or "", "digest_key": "chapter_goal"},
            {"slot": "scene_card", "ref_id": target.get("scene_id") or "", "digest_key": "scene_card"},
        ],
        "inline_digests": inline_digests,
    }


def _structure_extract_user_prompt(base_prompt: str, *, draft: AuthorDraft, target: dict[str, Any]) -> str:
    return "\n".join(
        [
            base_prompt,
            "",
            "## Author Draft Target",
            f"Object Type: {draft.object_type}",
            f"Object ID: {draft.object_id}",
            f"Chapter ID: {target.get('chapter_id') or ''}",
            f"Scene ID: {target.get('scene_id') or ''}",
            "",
            "## Current Author Draft",
            draft.content or "",
            "",
            "## Current Metadata",
            json.dumps(target, ensure_ascii=False, sort_keys=True),
        ]
    )


def _normalize_structure_payload(payload: Any, *, draft: AuthorDraft, target: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = _offline_structure_payload(draft, target)
    raw_brief = payload.get("candidate_brief")
    if not isinstance(raw_brief, dict):
        raw_brief = payload.get("scene_writer_brief") if draft.object_type == "scene" else payload.get("chapter_writer_brief")
    if not isinstance(raw_brief, dict):
        raw_brief = _offline_structure_payload(draft, target)["candidate_brief"]
    if draft.object_type == "scene":
        normalized = normalize_scene_writer_brief({**empty_scene_writer_brief(), **raw_brief})
    else:
        normalized = normalize_chapter_writer_brief({**empty_chapter_writer_brief(), **raw_brief})
    notes = payload.get("uncertainty_notes")
    uncertainty_notes = [str(item).strip() for item in notes if str(item).strip()] if isinstance(notes, list) else []
    rationale = payload.get("rationale")
    return {
        "candidate_brief": _nonempty_brief(normalized),
        "uncertainty_notes": uncertainty_notes,
        "rationale": str(rationale).strip() if isinstance(rationale, str) and rationale.strip() else "从作者稿反向提取戏剧意图。",
    }


def _offline_structure_payload(draft: AuthorDraft, target: dict[str, Any]) -> dict[str, Any]:
    text = (draft.content or "").strip()
    first_line = _first_sentence(text) or str(target.get("chapter_goal") or "作者稿已有一个需要澄清的戏剧方向")
    if draft.object_type == "scene":
        scene_card = target.get("scene_card") if isinstance(target.get("scene_card"), dict) else {}
        scene_goal = str(scene_card.get("scene_goal") or first_line)
        return {
            "candidate_brief": {
                "character_desire": _infer_desire(text, fallback=scene_goal),
                "obstacle": _infer_obstacle(text),
                "stakes": _infer_stakes(text),
                "secret_or_misunderstanding": "真相尚未被所有在场者同时理解。",
                "subtext": "人物没有把真正担心的代价说出口。",
                "irreversible_change": str(scene_card.get("exit_change") or "人物已经做出会改变后续关系的动作。"),
                "reader_question": str(scene_card.get("hook") or "这个选择会把谁推向危险？"),
                "choice_under_pressure": "公开真相，还是先保护仍会受伤的人。",
                "power_shift": "掌握证据的人获得主动权，也承担新的风险。",
                "new_information": first_line,
                "emotional_turn": "人物从观察进入承担后果。",
                "image_anchor": _image_anchor(text),
                "reader_aftertaste": "读者知道这次沉默不是退让，而是代价。",
            },
            "uncertainty_notes": ["离线提取只依据作者稿表层信息，需作者确认。"],
            "rationale": "从作者稿里的动作、选择词和结尾钩子反推场景戏剧卡。",
        }
    return {
        "candidate_brief": {
            "core_promise": first_line,
            "plot_movement": "让作者稿中的核心线索推动下一步行动。",
            "character_shift": "人物从被动感知转向主动承担。",
            "chapter_question": "这章提出的问题会迫使人物付出什么代价？",
            "ending_aftertaste": "结尾应留下一个尚未安全兑现的承诺。",
            "chapter_promise": first_line,
            "escalation_path": "线索出现后，压力通过选择和关系变化升级。",
            "relationship_delta": "关键关系因信息不对称发生偏移。",
            "reveal_or_reversal": "作者稿里的发现改变读者对局势的理解。",
            "payoff_target": "后续场景需要兑现或反转本章提出的问题。",
            "ending_question": "人物接下来会公开、隐藏，还是交换这份信息？",
        },
        "uncertainty_notes": ["离线提取无法判断作者长期主题，请人工确认。"],
        "rationale": "从作者稿反推章节承诺、推进和结尾问题。",
    }


def _merge_briefs(current: dict[str, str], candidate: dict[str, Any]) -> dict[str, str]:
    merged = dict(current)
    for key, value in candidate.items():
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    return merged


def _nonempty_brief(brief: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in brief.items() if key != "schema_version" and isinstance(value, str) and value.strip()}


def _first_sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for separator in ("。", "！", "？", "\n"):
        if separator in cleaned:
            return cleaned.split(separator, 1)[0].strip() + ("。" if separator == "。" else "")
    return cleaned[:80]


def _infer_desire(text: str, *, fallback: str) -> str:
    if any(token in text for token in ("公开", "真相", "证据")):
        return "确认证据是否应该公开，并掌握公开的时机。"
    if any(token in text for token in ("保护", "隐藏", "藏")):
        return "保护关键人物或秘密不被立刻暴露。"
    return fallback or "完成眼前必须处理的行动。"


def _infer_obstacle(text: str) -> str:
    if any(token in text for token in ("问", "阻止", "追踪", "危险")):
        return "他人的追问、追踪或危险让选择无法拖延。"
    return "信息不完整，人物不能同时保住真相与安全。"


def _infer_stakes(text: str) -> str:
    if any(token in text for token in ("保护", "危险", "追踪", "公开")):
        return "选择错误会让仍需保护的人暴露在危险里。"
    return "选择会改变人物关系和后续行动空间。"


def _image_anchor(text: str) -> str:
    for token in ("录音带", "证据袋", "门", "盐钟", "档案", "袖口", "船坞"):
        if token in text:
            return token
    return "一个被人物反复触碰的物件"
