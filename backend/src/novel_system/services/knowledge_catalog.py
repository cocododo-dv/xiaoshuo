from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import SceneBundle, VectorAliasRegistry, VersionRegistry
from novel_system.services.errors import DomainError
from novel_system.services.knowledge_registry import all_descriptors, descriptor_for_object_type


def list_knowledge(
    session: Session,
    *,
    object_type: str | None = None,
    scope: str | None = None,
    scope_ref_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    query = select(VersionRegistry)
    if object_type:
        query = query.where(VersionRegistry.object_type == object_type)
    registries = session.execute(
        query.order_by(
            VersionRegistry.object_type.asc(),
            VersionRegistry.lineage_key.asc(),
            VersionRegistry.version.desc(),
        )
    ).scalars().all()

    grouped: dict[tuple[str, str], list[VersionRegistry]] = defaultdict(list)
    for registry in registries:
        try:
            descriptor_for_object_type(registry.object_type)
        except KeyError:
            continue
        grouped[(registry.object_type, registry.lineage_key)].append(registry)

    items: list[dict[str, Any]] = []
    for (current_object_type, lineage_key), grouped_registries in grouped.items():
        item = _serialize_entry(session, current_object_type, lineage_key, grouped_registries)
        if _matches_filters(item, scope=scope, scope_ref_id=scope_ref_id, status=status):
            items.append(item)

    items.sort(key=lambda item: (item["object_type"], item["lineage_key"]))
    return items


def get_knowledge(session: Session, *, object_type: str, lineage_key: str) -> dict[str, Any]:
    try:
        descriptor_for_object_type(object_type)
    except KeyError as exc:
        raise DomainError("KNOWLEDGE_OBJECT_TYPE_NOT_FOUND", f"unknown object type {object_type}", status_code=404) from exc

    registries = session.execute(
        select(VersionRegistry)
        .where(
            VersionRegistry.object_type == object_type,
            VersionRegistry.lineage_key == lineage_key,
        )
        .order_by(VersionRegistry.version.desc())
    ).scalars().all()
    if not registries:
        raise DomainError("KNOWLEDGE_NOT_FOUND", f"{object_type}/{lineage_key} not found", status_code=404)
    return _serialize_entry(session, object_type, lineage_key, registries)


def _serialize_entry(
    session: Session,
    object_type: str,
    lineage_key: str,
    registries: list[VersionRegistry],
) -> dict[str, Any]:
    descriptor = descriptor_for_object_type(object_type)
    registries = sorted(registries, key=lambda registry: registry.version, reverse=True)
    versions = [_serialize_version(session, descriptor, registry) for registry in registries]
    active_version = next((version for version in versions if version["active_flag"]), None)
    candidate_version = next((version for version in versions if not version["active_flag"]), None)
    runtime_refs = _runtime_refs(session, descriptor.object_type, registries)
    review_refs = [version["source_review_id"] for version in versions if version.get("source_review_id")]
    return {
        "object_type": descriptor.object_type,
        "lineage_key": lineage_key,
        "status": _entry_status(active_version, candidate_version),
        "active_version": active_version,
        "candidate_version": candidate_version,
        "versions": versions,
        "review_refs": list(dict.fromkeys(review_refs)),
        "runtime_refs": runtime_refs,
        "bundle_refs": _bundle_refs(session, object_type=descriptor.object_type, lineage_key=lineage_key),
    }


def _serialize_version(session: Session, descriptor, registry: VersionRegistry) -> dict[str, Any]:
    row = session.get(descriptor.model_cls, registry.physical_row_id)
    if row is None:
        return {
            "version": registry.version,
            "row_id": registry.physical_row_id,
            "active_flag": False,
            "runtime_eligible": False,
            "materialize_status": registry.materialize_status,
            "reindex_status": registry.reindex_status,
            "verify_status": registry.verify_status,
        }

    payload: dict[str, Any] = {
        "version": registry.version,
        "row_id": row.row_id,
        "lineage_key": getattr(row, descriptor.lineage_field),
        "text": getattr(row, descriptor.text_field),
        "active_flag": bool(getattr(row, "active_flag", 0)),
        "runtime_eligible": bool(getattr(row, "runtime_eligible", 0)),
        "runtime_eligibility_basis": getattr(row, "runtime_eligibility_basis", None),
        "effective_at": getattr(row, "effective_at", None),
        "created_at": getattr(row, "created_at", None),
        "source_review_id": getattr(row, "source_review_id", None),
        "materialize_status": registry.materialize_status,
        "reindex_status": registry.reindex_status,
        "verify_status": registry.verify_status,
        "activated_at": registry.activated_at,
        "alias_scope": registry.alias_scope,
    }
    if hasattr(row, "scope"):
        payload["scope"] = row.scope
        payload["scope_ref_id"] = row.scope_ref_id
    if hasattr(row, "character_id"):
        payload["character_id"] = row.character_id
    if hasattr(row, "left_character_id"):
        payload["left_character_id"] = row.left_character_id
        payload["right_character_id"] = row.right_character_id
    if hasattr(row, "chapter_id"):
        payload["chapter_id"] = row.chapter_id
    if hasattr(row, "scene_id"):
        payload["scene_id"] = row.scene_id
    if hasattr(row, "tracker_status"):
        payload["status"] = row.tracker_status
    if hasattr(row, "rule_tier"):
        payload["rule_tier"] = row.rule_tier
    if hasattr(row, "expires_at"):
        payload["expires_at"] = row.expires_at
    return payload


def _runtime_refs(session: Session, object_type: str, registries: list[VersionRegistry]) -> dict[str, Any]:
    alias_scope = next((registry.alias_scope for registry in registries if registry.alias_scope), None)
    if not alias_scope:
        return {"mode": "direct_read"}
    alias = session.get(VectorAliasRegistry, alias_scope)
    return {
        "mode": "vector",
        "alias_scope": alias_scope,
        "active_alias": alias.active_alias if alias else None,
        "candidate_alias": alias.candidate_alias if alias else None,
        "verify_status": alias.verify_status if alias else None,
        "sample_query_success": bool(alias.sample_query_success) if alias else None,
        "object_type": object_type,
    }


def _bundle_refs(session: Session, *, object_type: str, lineage_key: str) -> list[dict[str, Any]]:
    bundles = session.execute(select(SceneBundle).order_by(SceneBundle.created_at.desc())).scalars().all()
    refs: list[dict[str, Any]] = []
    for bundle in bundles:
        snapshot = bundle.frozen_snapshot_json or {}
        source_values = list((snapshot.get("source_version_refs") or {}).values())
        resolved_values = list((snapshot.get("resolved_ref_ids") or {}).values())
        flat_values: list[str] = []
        for value in [*source_values, *resolved_values]:
            if isinstance(value, list):
                flat_values.extend(str(item) for item in value)
            elif value is not None:
                flat_values.append(str(value))
        if lineage_key not in flat_values:
            continue
        refs.append(
            {
                "bundle_id": bundle.bundle_id,
                "scene_id": bundle.scene_id,
                "chapter_id": bundle.chapter_id,
                "object_type": object_type,
            }
        )
    return refs


def _entry_status(active_version: dict[str, Any] | None, candidate_version: dict[str, Any] | None) -> str:
    if active_version and active_version.get("status") == "resolved":
        return "resolved"
    if active_version is not None:
        return "active"
    if candidate_version is not None:
        return "candidate"
    return "unknown"


def _matches_filters(
    item: dict[str, Any],
    *,
    scope: str | None,
    scope_ref_id: str | None,
    status: str | None,
) -> bool:
    version = item.get("active_version") or item.get("candidate_version") or {}
    if scope and version.get("scope") != scope:
        return False
    if scope_ref_id and version.get("scope_ref_id") != scope_ref_id:
        return False
    if status and item.get("status") != status:
        return False
    return True


def supported_object_types() -> list[str]:
    return [descriptor.object_type for descriptor in all_descriptors()]
