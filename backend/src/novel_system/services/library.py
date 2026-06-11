"""资料库服务 — 实体与关系(设计稿 ws-library 的后端)。

人物的权威实体是 StoryCharacter(P0-4),资料库不复制人物数据;
overview 聚合接口把人物与非人物实体合并输出,关系边的端点用
"character:<id>" / "entity:<id>" 前缀 ref 指向两类对象。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import LibraryEntity, LibraryRelation, StoryCharacter, TimelineEvent
from novel_system.services.errors import DomainError
from novel_system.services.projects import ProjectService

ENTITY_KINDS = {"location", "item", "faction", "concept"}
ENTITY_STATUSES = {"active", "archived"}


def _entity_payload(entity: LibraryEntity) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "project_id": entity.project_id,
        "kind": entity.kind,
        "name": entity.name,
        "aliases": entity.aliases_json or [],
        "summary": entity.summary or "",
        "details": entity.details_json or {},
        "tags": entity.tags_json or [],
        "status": entity.status,
        "ref": f"entity:{entity.entity_id}",
        "updated_at": entity.updated_at,
    }


def _character_payload(character: StoryCharacter) -> dict[str, Any]:
    summary = character.summary_json or {}
    return {
        "character_id": character.character_id,
        "project_id": character.project_id,
        "kind": "character",
        "name": character.display_name,
        "role": character.role or "",
        "summary": str(summary.get("one_line") or summary.get("summary") or ""),
        # FE-ALIGN P6：资料卡扩展字段（facts/blurb/arc/appears 等自由字段组）
        "details": dict(summary.get("fe_details") or {}),
        "status": character.status,
        "ref": f"character:{character.character_id}",
        "updated_at": character.updated_at,
    }


def _timeline_payload(event: TimelineEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "project_id": event.project_id,
        "label": event.label,
        "time_label": event.time_label or "",
        "chapter_ref": event.chapter_ref or "",
        "entity_refs": event.entity_refs_json or [],
        "note": event.note or "",
        "display_order": event.display_order,
        "updated_at": event.updated_at,
    }


def _relation_payload(relation: LibraryRelation) -> dict[str, Any]:
    return {
        "relation_id": relation.relation_id,
        "project_id": relation.project_id,
        "from_ref": relation.from_ref,
        "to_ref": relation.to_ref,
        "kind": relation.kind,
        "note": relation.note or "",
        "updated_at": relation.updated_at,
    }


class LibraryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _require_project(self, project_id: str):
        return ProjectService(self.session).require_project(project_id)

    def overview(self, project_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        characters = self.session.scalars(
            select(StoryCharacter)
            .where(StoryCharacter.project_id == project.project_id)
            .order_by(StoryCharacter.created_at)
        ).all()
        entities = self.session.scalars(
            select(LibraryEntity)
            .where(LibraryEntity.project_id == project.project_id)
            .order_by(LibraryEntity.created_at)
        ).all()
        relations = self.session.scalars(
            select(LibraryRelation)
            .where(LibraryRelation.project_id == project.project_id)
            .order_by(LibraryRelation.created_at)
        ).all()
        return {
            "project_id": project.project_id,
            "characters": [_character_payload(item) for item in characters],
            "entities": [_entity_payload(item) for item in entities],
            "relations": [_relation_payload(item) for item in relations],
            # FE-ALIGN P6：时间线并入聚合（前端一次装载）
            "timeline": [_timeline_payload(item) for item in self._timeline_rows(project.project_id)],
        }

    # ---- FE-ALIGN P6：时间线 ----

    def _timeline_rows(self, project_id: str) -> list[TimelineEvent]:
        rows = list(
            self.session.scalars(
                select(TimelineEvent).where(TimelineEvent.project_id == project_id)
            ).all()
        )
        rows.sort(key=lambda r: (r.display_order is None, r.display_order or 0, r.created_at))
        return rows

    def list_timeline(self, project_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        return {"items": [_timeline_payload(item) for item in self._timeline_rows(project.project_id)]}

    def create_timeline_event(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        label = str(payload.get("label") or "").strip()
        if not label:
            raise DomainError("TIMELINE_LABEL_REQUIRED", "event label is required", status_code=400)
        rows = self._timeline_rows(project.project_id)
        event = TimelineEvent(
            event_id=f"EVT_{uuid.uuid4().hex[:10].upper()}",
            project_id=project.project_id,
            label=label,
            time_label=str(payload.get("time_label") or "").strip() or None,
            chapter_ref=str(payload.get("chapter_ref") or "").strip() or None,
            entity_refs_json=list(payload.get("entity_refs") or []),
            note=str(payload.get("note") or "").strip() or None,
            display_order=int(payload["display_order"]) if payload.get("display_order") is not None else len(rows) + 1,
        )
        self.session.add(event)
        self.session.flush()
        return _timeline_payload(event)

    def _require_event(self, project_id: str, event_id: str) -> TimelineEvent:
        event = self.session.get(TimelineEvent, event_id)
        if event is None or event.project_id != project_id:
            raise DomainError("TIMELINE_EVENT_NOT_FOUND", "timeline event not found", status_code=404)
        return event

    def update_timeline_event(self, project_id: str, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        event = self._require_event(project.project_id, event_id)
        if "label" in payload:
            label = str(payload.get("label") or "").strip()
            if not label:
                raise DomainError("TIMELINE_LABEL_REQUIRED", "event label is required", status_code=400)
            event.label = label
        if "time_label" in payload:
            event.time_label = str(payload.get("time_label") or "").strip() or None
        if "chapter_ref" in payload:
            event.chapter_ref = str(payload.get("chapter_ref") or "").strip() or None
        if "entity_refs" in payload:
            event.entity_refs_json = list(payload.get("entity_refs") or [])
        if "note" in payload:
            event.note = str(payload.get("note") or "").strip() or None
        if "display_order" in payload and payload.get("display_order") is not None:
            event.display_order = int(payload["display_order"])
        self.session.flush()
        return _timeline_payload(event)

    def delete_timeline_event(self, project_id: str, event_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        event = self._require_event(project.project_id, event_id)
        self.session.delete(event)
        self.session.flush()
        return {"event_id": event_id, "deleted": True}

    # ---- FE-ALIGN P6：图投影（实体+关系 → nodes/edges，纯投影） ----

    def graph(self, project_id: str) -> dict[str, Any]:
        overview = self.overview(project_id)
        nodes = [
            {"id": item["ref"], "kind": "character", "name": item["name"]}
            for item in overview["characters"]
        ] + [
            {"id": item["ref"], "kind": item["kind"], "name": item["name"]}
            for item in overview["entities"]
        ]
        edges = [
            {
                "from": item["from_ref"],
                "to": item["to_ref"],
                "relation": item["kind"],
                "note": item["note"],
            }
            for item in overview["relations"]
        ]
        return {"nodes": nodes, "edges": edges}

    # ---- FE-ALIGN P6：人物档案的资料卡编辑（改名后引用经 character_id 不断） ----

    def create_character(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """资料库侧新建人物档案（雪花角色同步之外的手动入口）。"""
        project = self._require_project(project_id)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise DomainError("LIBRARY_ENTITY_NAME_REQUIRED", "character name is required", status_code=400)
        character = StoryCharacter(
            character_id=f"CHAR_{uuid.uuid4().hex[:10].upper()}",
            project_id=project.project_id,
            display_name=name,
            role=str(payload.get("role") or "").strip() or None,
            summary_json={
                "one_line": str(payload.get("summary") or "").strip(),
                "fe_details": dict(payload.get("details") or {}),
            },
            status="active",
        )
        self.session.add(character)
        self.session.flush()
        return _character_payload(character)

    def update_character(self, project_id: str, character_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        character = self.session.get(StoryCharacter, character_id)
        if character is None or character.project_id != project.project_id:
            raise DomainError("LIBRARY_CHARACTER_NOT_FOUND", "character not found in project", status_code=404)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise DomainError("LIBRARY_ENTITY_NAME_REQUIRED", "character name is required", status_code=400)
            character.display_name = name
        if "role" in payload:
            character.role = str(payload.get("role") or "").strip() or None
        if "summary" in payload:
            summary = dict(character.summary_json or {})
            summary["one_line"] = str(payload.get("summary") or "").strip()
            character.summary_json = summary
        if "details" in payload:
            summary = dict(character.summary_json or {})
            summary["fe_details"] = dict(payload.get("details") or {})
            character.summary_json = summary
        self.session.flush()
        return _character_payload(character)

    def create_entity(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise DomainError("LIBRARY_ENTITY_NAME_REQUIRED", "entity name is required", status_code=400)
        kind = str(payload.get("kind") or "concept").strip()
        if kind not in ENTITY_KINDS:
            raise DomainError("LIBRARY_ENTITY_KIND_INVALID", f"kind must be one of {sorted(ENTITY_KINDS)}", status_code=400)
        entity = LibraryEntity(
            entity_id=f"ENT_{uuid.uuid4().hex[:10].upper()}",
            project_id=project.project_id,
            kind=kind,
            name=name,
            aliases_json=list(payload.get("aliases") or []),
            summary=str(payload.get("summary") or "").strip() or None,
            details_json=dict(payload.get("details") or {}),
            tags_json=list(payload.get("tags") or []),
            status="active",
        )
        self.session.add(entity)
        self.session.flush()
        return _entity_payload(entity)

    def _require_entity(self, project_id: str, entity_id: str) -> LibraryEntity:
        entity = self.session.get(LibraryEntity, entity_id)
        if entity is None or entity.project_id != project_id:
            raise DomainError("LIBRARY_ENTITY_NOT_FOUND", "library entity not found", status_code=404)
        return entity

    def update_entity(self, project_id: str, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        entity = self._require_entity(project.project_id, entity_id)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise DomainError("LIBRARY_ENTITY_NAME_REQUIRED", "entity name is required", status_code=400)
            entity.name = name
        if "kind" in payload:
            kind = str(payload.get("kind") or "").strip()
            if kind not in ENTITY_KINDS:
                raise DomainError("LIBRARY_ENTITY_KIND_INVALID", f"kind must be one of {sorted(ENTITY_KINDS)}", status_code=400)
            entity.kind = kind
        if "status" in payload:
            status = str(payload.get("status") or "").strip()
            if status not in ENTITY_STATUSES:
                raise DomainError("LIBRARY_ENTITY_STATUS_INVALID", f"status must be one of {sorted(ENTITY_STATUSES)}", status_code=400)
            entity.status = status
        if "aliases" in payload:
            entity.aliases_json = list(payload.get("aliases") or [])
        if "summary" in payload:
            entity.summary = str(payload.get("summary") or "").strip() or None
        if "details" in payload:
            entity.details_json = dict(payload.get("details") or {})
        if "tags" in payload:
            entity.tags_json = list(payload.get("tags") or [])
        self.session.flush()
        return _entity_payload(entity)

    def _validate_ref(self, project_id: str, ref: str) -> str:
        value = str(ref or "").strip()
        if value.startswith("entity:"):
            self._require_entity(project_id, value.split(":", 1)[1])
            return value
        if value.startswith("character:"):
            character_id = value.split(":", 1)[1]
            character = self.session.get(StoryCharacter, character_id)
            if character is None or character.project_id != project_id:
                raise DomainError("LIBRARY_RELATION_CHARACTER_NOT_FOUND", "character not found in project", status_code=404)
            return value
        raise DomainError(
            "LIBRARY_RELATION_REF_INVALID",
            'relation refs must look like "entity:<id>" or "character:<id>"',
            status_code=400,
        )

    def create_relation(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._require_project(project_id)
        from_ref = self._validate_ref(project.project_id, str(payload.get("from_ref") or ""))
        to_ref = self._validate_ref(project.project_id, str(payload.get("to_ref") or ""))
        if from_ref == to_ref:
            raise DomainError("LIBRARY_RELATION_SELF_LOOP", "relation endpoints must differ", status_code=400)
        relation = LibraryRelation(
            relation_id=f"REL_{uuid.uuid4().hex[:10].upper()}",
            project_id=project.project_id,
            from_ref=from_ref,
            to_ref=to_ref,
            kind=str(payload.get("kind") or "related").strip() or "related",
            note=str(payload.get("note") or "").strip() or None,
        )
        self.session.add(relation)
        self.session.flush()
        return _relation_payload(relation)

    def delete_relation(self, project_id: str, relation_id: str) -> dict[str, Any]:
        project = self._require_project(project_id)
        relation = self.session.get(LibraryRelation, relation_id)
        if relation is None or relation.project_id != project.project_id:
            raise DomainError("LIBRARY_RELATION_NOT_FOUND", "library relation not found", status_code=404)
        self.session.delete(relation)
        self.session.flush()
        return {"relation_id": relation_id, "deleted": True}
