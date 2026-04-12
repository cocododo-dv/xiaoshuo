from __future__ import annotations

from datetime import UTC, datetime
from collections import defaultdict
from typing import Any

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    HumanReviewEvent,
    OperationLog,
    ReconcileFault,
    ReindexJob,
    ReviewItem,
    SceneBundle,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.services.errors import DomainError
from novel_system.services.pagination import paginate_items, resolve_pagination_request
from novel_system.services.human_review_support import (
    human_review_followup_target,
    human_review_linked_target,
    structured_target,
    structured_target_from_ref,
    structured_target_from_replay_result,
)
from novel_system.services.knowledge_registry import all_descriptors, descriptor_for_item_type, descriptor_for_object_type


def list_knowledge_entries(
    session: Session,
    *,
    object_type: str | None = None,
    scope: str | None = None,
    scope_ref_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    return _list_knowledge_items(
        session,
        object_type=object_type,
        scope=scope,
        scope_ref_id=scope_ref_id,
        status=status,
        include_pending=True,
    )


def list_knowledge(
    session: Session,
    *,
    object_type: str | None = None,
    scope: str | None = None,
    scope_ref_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    return _list_knowledge_items(
        session,
        object_type=object_type,
        scope=scope,
        scope_ref_id=scope_ref_id,
        status=status,
        include_pending=False,
    )


def get_knowledge_entry(session: Session, *, object_type: str, lineage_key: str) -> dict[str, Any]:
    payload, _, _ = _resolve_knowledge_entry(session, object_type=object_type, lineage_key=lineage_key)
    return payload


def get_knowledge_workflow(session: Session, *, object_type: str, lineage_key: str) -> dict[str, Any]:
    payload, reviews, descriptor = _resolve_knowledge_entry(session, object_type=object_type, lineage_key=lineage_key)
    return _serialize_workflow(
        session,
        object_type=descriptor.object_type,
        lineage_key=lineage_key,
        payload=payload,
        reviews=reviews,
    )


def get_knowledge(session: Session, *, object_type: str, lineage_key: str) -> dict[str, Any]:
    payload = get_knowledge_entry(session, object_type=object_type, lineage_key=lineage_key)
    payload["workflow"] = get_knowledge_workflow(session, object_type=object_type, lineage_key=lineage_key)
    return payload


def list_vector_alias_scopes(
    session: Session,
    *,
    object_type: str | None = None,
    scope: str | None = None,
    scope_ref_id: str | None = None,
    verify_status: str | None = None,
) -> list[dict[str, Any]]:
    query = select(VectorAliasRegistry)
    if object_type:
        query = query.where(VectorAliasRegistry.object_type == object_type)
    if scope:
        query = query.where(VectorAliasRegistry.scope == scope)
    if scope_ref_id:
        query = query.where(VectorAliasRegistry.scope_ref_id == scope_ref_id)
    if verify_status:
        query = query.where(VectorAliasRegistry.verify_status == verify_status)
    items = session.execute(query.order_by(VectorAliasRegistry.alias_scope.asc())).scalars().all()
    return [_serialize_alias_scope(item, session=session) for item in items]


def get_vector_alias_scope(session: Session, alias_scope: str) -> dict[str, Any] | None:
    item = session.get(VectorAliasRegistry, alias_scope)
    if item is None:
        return None
    return _serialize_alias_scope(item, session=session)


def list_jobs(
    session: Session,
    *,
    job_type: str | None = None,
    status: str | None = None,
    object_type: str | None = None,
    review_id: str | None = None,
    alias_scope: str | None = None,
    worker_id: str | None = None,
    stuck_only: bool | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    reindex_query = select(ReindexJob)
    verify_query = select(VerifyJob)
    if status:
        reindex_query = reindex_query.where(ReindexJob.status == status)
        verify_query = verify_query.where(VerifyJob.status == status)
    if object_type:
        reindex_query = reindex_query.where(ReindexJob.object_type == object_type)
        verify_query = verify_query.where(VerifyJob.object_type == object_type)
    if review_id:
        reindex_query = reindex_query.where(ReindexJob.review_id == review_id)
        verify_query = verify_query.where(VerifyJob.review_id == review_id)
    if alias_scope:
        reindex_query = reindex_query.where(ReindexJob.alias_scope == alias_scope)
        verify_query = verify_query.where(VerifyJob.alias_scope == alias_scope)
    if worker_id:
        reindex_query = reindex_query.where(ReindexJob.worker_id == worker_id)
        verify_query = verify_query.where(VerifyJob.worker_id == worker_id)
    reindex_jobs = [] if job_type == "verify" else session.execute(reindex_query).scalars().all()
    verify_jobs = [] if job_type == "reindex" else session.execute(verify_query).scalars().all()
    items = [_serialize_reindex_job(job) for job in reindex_jobs] + [_serialize_verify_job(job) for job in verify_jobs]
    if stuck_only:
        items = [item for item in items if _job_is_stuck(item)]
    items.sort(key=lambda item: (item["job_type"], item["job_id"]))
    request = resolve_pagination_request(page=page, page_size=page_size, cursor=cursor, limit=limit)
    page_items, pagination = paginate_items(
        items,
        request=request,
        cursor_values=lambda item: [item["job_type"], item["job_id"]],
    )
    return {"items": page_items, "pagination": pagination}


def get_job(session: Session, job_id: str) -> dict[str, Any] | None:
    job = session.get(ReindexJob, job_id)
    if job is not None:
        return _serialize_reindex_job(job)
    job = session.get(VerifyJob, job_id)
    if job is not None:
        return _serialize_verify_job(job)
    return None


def list_activity_events(
    session: Session,
    *,
    stream: str,
    target_ref: str | None = None,
    actor_ref: str | None = None,
) -> list[dict[str, Any]]:
    if stream == "recovery_timeline":
        return _filter_recovery_timeline(_serialize_recovery_timeline(session), target_ref=target_ref, actor_ref=actor_ref)
    if stream == "system_runtime":
        return _filter_activity_timeline(_serialize_system_runtime_timeline(session), target_ref=target_ref, actor_ref=actor_ref)
    if stream == "operator_action":
        return _filter_activity_timeline(_serialize_operator_action_timeline(session), target_ref=target_ref, actor_ref=actor_ref)
    raise DomainError("ACTIVITY_STREAM_INVALID", f"unsupported activity stream {stream}", status_code=400)


def list_target_activity_groups(
    session: Session,
    *,
    target_ref: str | None = None,
    source: str | None = None,
    actor_ref: str | None = None,
) -> list[dict[str, Any]]:
    recovery_timeline = list_activity_events(
        session,
        stream="recovery_timeline",
        target_ref=target_ref,
        actor_ref=actor_ref,
    )
    system_runtime_timeline = list_activity_events(
        session,
        stream="system_runtime",
        target_ref=target_ref,
        actor_ref=actor_ref,
    )
    operator_action_timeline = list_activity_events(
        session,
        stream="operator_action",
        target_ref=target_ref,
        actor_ref=actor_ref,
    )

    if source == "recovery_timeline":
        system_runtime_timeline = []
        operator_action_timeline = []
    elif source == "system_runtime":
        recovery_timeline = []
        operator_action_timeline = []
    elif source == "operator_action":
        recovery_timeline = []
        system_runtime_timeline = []

    return _serialize_target_activity_groups(
        recovery_timeline,
        system_runtime_timeline,
        operator_action_timeline,
    )


def latest_recovery_action_receipt(
    session: Session,
    *,
    target_ref: str | None = None,
    actor_ref: str | None = None,
) -> dict[str, Any] | None:
    recovery_timeline = list_activity_events(
        session,
        stream="recovery_timeline",
        target_ref=target_ref,
        actor_ref=actor_ref,
    )
    latest_receipt = next((item for item in recovery_timeline if item["last_action_at"]), None)
    return _serialize_recovery_receipt(latest_receipt)


def _job_is_stuck(item: dict[str, Any]) -> bool:
    lease_expires_at = item.get("lease_expires_at")
    if item.get("status") != "running" or not lease_expires_at:
        return False
    expires_at = _parse_datetime(lease_expires_at)
    if expires_at is None:
        return False
    return expires_at <= datetime.now(UTC)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _list_knowledge_items(
    session: Session,
    *,
    object_type: str | None = None,
    scope: str | None = None,
    scope_ref_id: str | None = None,
    status: str | None = None,
    include_pending: bool,
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

    items: dict[tuple[str, str], dict[str, Any]] = {}
    for (current_object_type, lineage_key), grouped_registries in grouped.items():
        item = _serialize_entry(session, current_object_type, lineage_key, grouped_registries)
        _merge_related_reviews_into_item(
            session,
            item,
            object_type=current_object_type,
            lineage_key=lineage_key,
        )
        items[(current_object_type, lineage_key)] = item

    if include_pending:
        reviews = session.execute(
            select(ReviewItem).order_by(ReviewItem.created_at.desc(), ReviewItem.review_id.desc())
        ).scalars().all()
        for review in reviews:
            if review.status == "rejected":
                continue
            try:
                descriptor = descriptor_for_item_type(review.item_type)
            except KeyError:
                continue
            if object_type and descriptor.object_type != object_type:
                continue
            lineage_key = _review_lineage_key(review)
            key = (descriptor.object_type, lineage_key)
            if key in items:
                continue
            related_reviews = _related_reviews(
                session,
                object_type=descriptor.object_type,
                lineage_key=lineage_key,
                review_refs=[review.review_id],
            )
            items[key] = _serialize_pending_entry(descriptor.object_type, lineage_key, related_reviews)

    filtered_items = [
        item
        for item in items.values()
        if _matches_filters(item, scope=scope, scope_ref_id=scope_ref_id, status=status)
    ]
    filtered_items.sort(key=lambda item: (item["object_type"], item["lineage_key"]))
    return filtered_items


def _resolve_knowledge_entry(
    session: Session,
    *,
    object_type: str,
    lineage_key: str,
) -> tuple[dict[str, Any], list[ReviewItem], Any]:
    try:
        descriptor = descriptor_for_object_type(object_type)
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
    related_reviews = _related_reviews(
        session,
        object_type=object_type,
        lineage_key=lineage_key,
        review_refs=[],
    )
    if not registries and not related_reviews:
        raise DomainError("KNOWLEDGE_NOT_FOUND", f"{object_type}/{lineage_key} not found", status_code=404)

    if registries:
        payload = _serialize_entry(session, object_type, lineage_key, registries)
        related_reviews = _related_reviews(
            session,
            object_type=object_type,
            lineage_key=lineage_key,
            review_refs=payload.get("review_refs", []),
        )
        if related_reviews:
            payload["review_refs"] = list(
                dict.fromkeys([*payload.get("review_refs", []), *(review.review_id for review in related_reviews)])
            )
            pending_candidate = _candidate_version_from_reviews(related_reviews)
            if pending_candidate is not None:
                payload["candidate_version"] = pending_candidate
    else:
        payload = _serialize_pending_entry(descriptor.object_type, lineage_key, related_reviews)
    return payload, related_reviews, descriptor


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


def _merge_related_reviews_into_item(
    session: Session,
    item: dict[str, Any],
    *,
    object_type: str,
    lineage_key: str,
) -> None:
    related_reviews = _related_reviews(
        session,
        object_type=object_type,
        lineage_key=lineage_key,
        review_refs=item.get("review_refs", []),
    )
    if not related_reviews:
        return
    item["review_refs"] = list(
        dict.fromkeys([*item.get("review_refs", []), *(review.review_id for review in related_reviews)])
    )
    pending_candidate = _candidate_version_from_reviews(related_reviews)
    if pending_candidate is not None and (
        item.get("candidate_version") is None or related_reviews[0].materialize_status != "succeeded"
    ):
        item["candidate_version"] = pending_candidate


def supported_object_types() -> list[str]:
    return [descriptor.object_type for descriptor in all_descriptors()]


def _serialize_pending_entry(object_type: str, lineage_key: str, reviews: list[ReviewItem]) -> dict[str, Any]:
    candidate_version = _candidate_version_from_reviews(reviews)
    return {
        "object_type": object_type,
        "lineage_key": lineage_key,
        "status": "candidate" if candidate_version is not None else "unknown",
        "active_version": None,
        "candidate_version": candidate_version,
        "versions": [],
        "review_refs": [review.review_id for review in reviews],
        "runtime_refs": {"mode": "pending_review"},
        "bundle_refs": [],
    }


def _candidate_version_from_reviews(reviews: list[ReviewItem]) -> dict[str, Any] | None:
    for review in reviews:
        if review.status == "rejected":
            continue
        return _serialize_review_candidate(review)
    return None


def _serialize_review_candidate(review: ReviewItem) -> dict[str, Any]:
    payload = review.candidate_payload_json or {}
    return {
        "review_id": review.review_id,
        "text": review.candidate_text,
        "active_flag": False,
        "runtime_eligible": False,
        "review_status": review.status,
        "materialize_status": review.materialize_status,
        "target_collection": review.target_collection,
        "scope": payload.get("scope"),
        "scope_ref_id": payload.get("scope_ref_id"),
        "character_id": payload.get("character_id"),
        "left_character_id": payload.get("left_character_id"),
        "right_character_id": payload.get("right_character_id"),
        "chapter_id": payload.get("chapter_id") or review.chapter_id,
        "scene_id": payload.get("scene_id") or review.scene_id,
        "lineage_key": _review_lineage_key(review),
    }


def _latest_alias_fault_summary(session: Session, alias_scope: str) -> dict[str, Any] | None:
    fault = session.execute(
        select(ReconcileFault)
        .where(
            ReconcileFault.fault_scope == "alias_mismatch",
            ReconcileFault.object_ref == alias_scope,
        )
        .order_by(ReconcileFault.created_at.desc(), ReconcileFault.fault_id.desc())
    ).scalars().first()
    if fault is None:
        return None
    return {
        "fault_scope": fault.fault_scope,
        "severity": fault.severity,
        "object_ref": fault.object_ref,
        "details_json": fault.details_json,
        "created_at": fault.created_at,
    }


def _serialize_alias_scope(item: VectorAliasRegistry, *, session: Session) -> dict[str, Any]:
    return {
        "alias_scope": item.alias_scope,
        "object_type": item.object_type,
        "scope": item.scope,
        "scope_ref_id": item.scope_ref_id,
        "collection_family": item.collection_family,
        "active_alias": item.active_alias,
        "candidate_alias": item.candidate_alias,
        "active_snapshot_version": item.active_snapshot_version,
        "candidate_snapshot_version": item.candidate_snapshot_version,
        "active_embedding_version": item.active_embedding_version,
        "candidate_embedding_version": item.candidate_embedding_version,
        "verify_status": item.verify_status,
        "sample_query_success": bool(item.sample_query_success),
        "updated_at": item.updated_at,
        "recent_fault_summary": _latest_alias_fault_summary(session, item.alias_scope),
    }


def _related_reviews(
    session: Session,
    *,
    object_type: str,
    lineage_key: str,
    review_refs: list[str],
) -> list[ReviewItem]:
    related: list[ReviewItem] = []
    review_ref_set = set(review_refs)
    items = session.execute(
        select(ReviewItem).order_by(ReviewItem.created_at.desc(), ReviewItem.review_id.desc())
    ).scalars().all()
    for item in items:
        if item.review_id in review_ref_set:
            related.append(item)
            continue
        try:
            descriptor = descriptor_for_item_type(item.item_type)
        except KeyError:
            continue
        if descriptor.object_type != object_type:
            continue
        if _review_lineage_key(item) == lineage_key:
            related.append(item)
    deduped: list[ReviewItem] = []
    seen_review_ids: set[str] = set()
    for item in related:
        if item.review_id in seen_review_ids:
            continue
        seen_review_ids.add(item.review_id)
        deduped.append(item)
    return deduped


def _review_lineage_key(review: ReviewItem) -> str:
    payload = review.candidate_payload_json or {}
    return payload.get("lineage_key") or payload.get("scene_id") or payload.get("chapter_id") or review.review_id


def _serialize_workflow(
    session: Session,
    *,
    object_type: str,
    lineage_key: str,
    payload: dict[str, Any],
    reviews: list[ReviewItem],
) -> dict[str, Any]:
    serialized_reviews = [_serialize_review_item(review) for review in reviews]
    review_ids = [review.review_id for review in reviews]
    alias_scope = payload.get("runtime_refs", {}).get("alias_scope")
    serialized_jobs = _related_jobs(session, review_ids=review_ids, alias_scope=alias_scope)
    target_refs = {
        *(f"review_item:{review_id}" for review_id in review_ids),
        *(item["target_ref"] for item in serialized_jobs),
    }
    serialized_events = _related_human_review_events(session, target_refs=target_refs)
    return {
        "review_items": serialized_reviews,
        "jobs": serialized_jobs,
        "human_review_events": serialized_events,
        "target_activity_groups": _related_target_activity_groups(session, target_refs=target_refs),
        "recommended_primary_action": _recommended_primary_action(
            payload=payload,
            reviews=serialized_reviews,
            jobs=serialized_jobs,
            events=serialized_events,
        ),
    }


def _serialize_review_item(item: ReviewItem) -> dict[str, Any]:
    return {
        "review_id": item.review_id,
        "scene_id": item.scene_id,
        "chapter_id": item.chapter_id,
        "item_type": item.item_type,
        "target_collection": item.target_collection,
        "status": item.status,
        "candidate_text": item.candidate_text,
        "candidate_payload_json": item.candidate_payload_json,
        "active_on_approve": item.active_on_approve,
        "materialize_status": item.materialize_status,
        "approved_item_row_id": item.approved_item_row_id,
    }


def _related_jobs(session: Session, *, review_ids: list[str], alias_scope: str | None) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    seen_job_ids: set[str] = set()
    review_id_set = set(review_ids)
    for job in session.execute(select(ReindexJob)).scalars().all():
        if job.review_id in review_id_set or (alias_scope and job.alias_scope == alias_scope):
            if job.job_id in seen_job_ids:
                continue
            seen_job_ids.add(job.job_id)
            related.append(_serialize_reindex_job(job))
    for job in session.execute(select(VerifyJob)).scalars().all():
        if job.review_id in review_id_set or (alias_scope and job.alias_scope == alias_scope):
            if job.job_id in seen_job_ids:
                continue
            seen_job_ids.add(job.job_id)
            related.append(_serialize_verify_job(job))
    related.sort(key=lambda item: (item["job_type"], item["job_id"]))
    return related


def _serialize_reindex_job(job: ReindexJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "review_id": job.review_id,
        "status": job.status,
        "job_type": "reindex",
        "object_type": job.object_type,
        "alias_scope": job.alias_scope,
        "target_snapshot_version": job.target_snapshot_version,
        "target_embedding_version": job.target_embedding_version,
        "worker_id": job.worker_id,
        "attempt_no": job.attempt_no,
        "heartbeat_at": job.heartbeat_at,
        "lease_expires_at": job.lease_expires_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error_text": job.error_text,
        "target_ref": f"reindex_job:{job.job_id}",
    }


def _serialize_verify_job(job: VerifyJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "review_id": job.review_id,
        "status": job.status,
        "job_type": "verify",
        "object_type": job.object_type,
        "alias_scope": job.alias_scope,
        "target_snapshot_version": job.target_snapshot_version,
        "target_embedding_version": job.target_embedding_version,
        "worker_id": job.worker_id,
        "attempt_no": job.attempt_no,
        "heartbeat_at": job.heartbeat_at,
        "lease_expires_at": job.lease_expires_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error_text": job.error_text,
        "target_ref": f"verify_job:{job.job_id}",
    }


def _related_human_review_events(session: Session, *, target_refs: set[str]) -> list[dict[str, Any]]:
    if not target_refs:
        return []
    related: list[dict[str, Any]] = []
    events = session.execute(
        select(HumanReviewEvent).order_by(HumanReviewEvent.created_at.desc(), HumanReviewEvent.event_id.desc())
    ).scalars().all()
    for item in events:
        serialized = _serialize_human_review_event(item)
        candidate_refs = {
            target["target_ref"]
            for target in (
                serialized.get("linked_target"),
                serialized.get("followup_target"),
                serialized.get("replay_target"),
            )
            if target is not None
        }
        if candidate_refs & target_refs:
            related.append(serialized)
    return related


def _serialize_human_review_event(item: HumanReviewEvent) -> dict[str, Any]:
    details = dict(item.details_json or {})
    return {
        "event_id": item.event_id,
        "scene_id": item.scene_id,
        "chapter_id": item.chapter_id,
        "object_ref": item.object_ref,
        "event_source": item.event_source,
        "priority": item.priority,
        "owner": item.owner,
        "status": item.status,
        "allowed_actions_json": item.allowed_actions_json,
        "result_status_map_json": item.result_status_map_json,
        "details_json": details,
        "linked_target": human_review_linked_target(details, item.scene_id),
        "followup_target": human_review_followup_target(details),
        "replay_target": structured_target_from_replay_result(details.get("last_replay_result")),
        "default_action": item.default_action,
    }


def _related_target_activity_groups(session: Session, *, target_refs: set[str]) -> list[dict[str, Any]]:
    if not target_refs:
        return []
    groups = _serialize_target_activity_groups(
        _serialize_recovery_timeline(session),
        _serialize_system_runtime_timeline(session),
        _serialize_operator_action_timeline(session),
    )
    return [group for group in groups if group["target"]["target_ref"] in target_refs]


def _recommended_primary_action(
    *,
    payload: dict[str, Any],
    reviews: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for event in events:
        if event["status"] == "resolved":
            continue
        action = event.get("default_action")
        if not action or action == "inspect":
            continue
        return {
            "kind": "human_review_event",
            "action": action,
            "event_id": event["event_id"],
            "label": _action_label(action),
            "target_ref": f"human_review_event:{event['event_id']}",
        }

    for review in reviews:
        if review["status"] == "pending":
            return {
                "kind": "review",
                "action": "approve_review",
                "review_id": review["review_id"],
                "label": "Approve",
                "target_ref": f"review_item:{review['review_id']}",
            }

    for job in jobs:
        if job["job_type"] == "verify" and job["status"] != "succeeded":
            return {
                "kind": "verify_job",
                "action": "retry_verify",
                "job_id": job["job_id"],
                "label": "Retry Verify",
                "target_ref": job["target_ref"],
            }

    active_row_id = (payload.get("active_version") or {}).get("row_id")
    for review in reviews:
        if review["status"] != "approved" or review["materialize_status"] != "succeeded":
            continue
        if not review.get("approved_item_row_id") or review["approved_item_row_id"] == active_row_id:
            continue
        verify_jobs = [
            job
            for job in jobs
            if job["job_type"] == "verify" and job.get("review_id") == review["review_id"]
        ]
        if verify_jobs and not any(job["status"] == "succeeded" for job in verify_jobs):
            continue
        if not _effective_at_is_due((payload.get("candidate_version") or {}).get("effective_at")):
            continue
        return {
            "kind": "review",
            "action": "release_review",
            "review_id": review["review_id"],
            "label": "Release",
            "target_ref": f"review_item:{review['review_id']}",
        }
    return None


def _effective_at_is_due(effective_at: str | None) -> bool:
    if not effective_at:
        return True
    try:
        return datetime.fromisoformat(effective_at.replace("Z", "+00:00")) <= datetime.now(UTC)
    except ValueError:
        return True


def _action_label(action: str) -> str:
    return {
        "approve_review": "Approve",
        "retry_verify": "Retry Verify",
        "release_review": "Release",
        "retry_request": "Retry Request",
        "inspect": "Inspect",
    }.get(action, action.replace("_", " ").title())


def _serialize_recovery_timeline(session: Session) -> list[dict[str, Any]]:
    items = session.execute(
        select(HumanReviewEvent)
        .where(HumanReviewEvent.event_source == "idempotency_recovery")
    ).scalars().all()
    serialized = [_serialize_recovery_event(item) for item in items]
    serialized.sort(
        key=lambda item: (
            item["last_action_at"] or "",
            item["created_at"] or "",
            item["event_id"] or "",
        ),
        reverse=True,
    )
    return serialized


def _serialize_recovery_event(item: HumanReviewEvent) -> dict[str, Any]:
    details = dict(item.details_json or {})
    linked_target = human_review_linked_target(details, item.scene_id)
    followup_target = human_review_followup_target(details)
    replay_target = structured_target_from_replay_result(details.get("last_replay_result"))
    return {
        "event_id": item.event_id,
        "event_source": item.event_source,
        "priority": item.priority,
        "status": item.status,
        "object_ref": item.object_ref,
        "default_action": item.default_action,
        "linked_target": linked_target,
        "allowed_actions_json": item.allowed_actions_json,
        "result_status_map_json": item.result_status_map_json,
        "linked_target_ref": linked_target["target_ref"] if linked_target else details.get("linked_target_ref"),
        "resolution_reason": details.get("resolution_reason"),
        "followup_action": details.get("followup_action"),
        "followup_target": followup_target,
        "followup_target_ref": followup_target["target_ref"] if followup_target else details.get("followup_target_ref"),
        "last_action": details.get("last_action"),
        "last_action_at": details.get("last_action_at"),
        "last_action_status": details.get("last_action_status"),
        "last_actor_ref": details.get("last_actor_ref"),
        "last_replay_result": details.get("last_replay_result"),
        "replay_target": replay_target,
        "details_json": details,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _serialize_recovery_receipt(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "event_id": item["event_id"],
        "event_source": item["event_source"],
        "status": item["status"],
        "action": item["last_action"],
        "action_at": item["last_action_at"],
        "actor_ref": item["last_actor_ref"],
        "object_ref": item["object_ref"],
        "linked_target": item["linked_target"],
        "linked_target_ref": item["linked_target_ref"],
        "resolution_reason": item["resolution_reason"],
        "followup_action": item["followup_action"],
        "followup_target": item["followup_target"],
        "followup_target_ref": item["followup_target_ref"],
        "replay_result": item["last_replay_result"],
        "replay_target": item["replay_target"],
    }


def _filter_recovery_timeline(items: list[dict[str, Any]], *, target_ref: str | None, actor_ref: str | None) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        targets = [item.get("linked_target"), item.get("followup_target"), item.get("replay_target")]
        if target_ref and not any(target and target.get("target_ref") == target_ref for target in targets):
            continue
        if actor_ref and item.get("last_actor_ref") != actor_ref:
            continue
        filtered.append(item)
    return filtered


def _filter_activity_timeline(items: list[dict[str, Any]], *, target_ref: str | None, actor_ref: str | None) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        if target_ref and not any(target.get("target_ref") == target_ref for target in item.get("target_refs") or []):
            continue
        if actor_ref and item.get("actor_ref") != actor_ref:
            continue
        filtered.append(item)
    return filtered


def _serialize_system_runtime_timeline(session: Session) -> list[dict[str, Any]]:
    items = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "runtime_activity")
        .order_by(OperationLog.created_at.desc(), OperationLog.operation_id.desc())
    ).scalars().all()
    return [_serialize_system_runtime_activity(item) for item in items]


def _serialize_operator_action_timeline(session: Session) -> list[dict[str, Any]]:
    items = session.execute(
        select(OperationLog)
        .where(or_(OperationLog.event_type == "human_review_action", OperationLog.event_type == "operator_action"))
        .order_by(OperationLog.created_at.desc(), OperationLog.operation_id.desc())
    ).scalars().all()
    return [_serialize_operator_action(item) for item in items]


def _serialize_system_runtime_activity(item: OperationLog) -> dict[str, Any]:
    payload = dict(item.payload_json or {})
    return {
        "operation_id": item.operation_id,
        "event_type": item.event_type,
        "object_ref": item.object_ref,
        "actor_ref": payload.get("actor_ref"),
        "summary": payload.get("summary"),
        "created_at": item.created_at,
        "target_refs": _operation_log_target_refs(item.object_type, item.event_type, item.object_ref, payload),
        "payload_json": payload,
    }


def _serialize_operator_action(item: OperationLog) -> dict[str, Any]:
    payload = dict(item.payload_json or {})
    data = {
        "operation_id": item.operation_id,
        "event_type": item.event_type,
        "event_id": item.object_ref if item.object_type == "human_review_event" else None,
        "object_ref": item.object_ref,
        "actor_ref": payload.get("actor_ref"),
        "action": payload.get("action"),
        "status_before": payload.get("status_before"),
        "status_after": payload.get("status_after"),
        "resolution_reason": payload.get("resolution_reason") or payload.get("summary"),
        "created_at": item.created_at,
        "target_refs": _operation_log_target_refs(item.object_type, item.event_type, item.object_ref, payload),
        "payload_json": payload,
    }
    if item.event_type == "operator_action":
        data["summary"] = payload.get("summary")
    return data


def _operation_log_target_refs(
    object_type: str,
    event_type: str,
    object_ref: str,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []

    if object_type == "human_review_event" and object_ref:
        event_target = structured_target("human_review_event", object_ref)
        if event_target is not None:
            targets.append(event_target)

    for value in payload.get("target_refs") or []:
        target = _coerce_target(value)
        if target is not None:
            targets.append(target)

    if object_type in {"review_item", "scene_card", "verify_job", "reindex_job"} and object_ref:
        direct_target = structured_target(object_type, object_ref)
        if direct_target is not None:
            targets.append(direct_target)

    review_id = payload.get("review_id")
    if isinstance(review_id, str) and review_id:
        targets.append(
            {
                "target_type": "review_item",
                "target_id": review_id,
                "target_ref": f"review_item:{review_id}",
            }
        )

    event_id = payload.get("event_id")
    if isinstance(event_id, str) and event_id:
        targets.append(
            {
                "target_type": "human_review_event",
                "target_id": event_id,
                "target_ref": f"human_review_event:{event_id}",
            }
        )

    job_id = payload.get("job_id")
    job_type = payload.get("job_type")
    if isinstance(job_id, str) and job_id:
        if job_type == "reindex" or job_id.startswith("reindex_"):
            target_type = "reindex_job"
        else:
            target_type = "verify_job"
        targets.append(
            {
                "target_type": target_type,
                "target_id": job_id,
                "target_ref": f"{target_type}:{job_id}",
            }
        )
    elif event_type == "runtime_job_reclaimed":
        if object_ref.startswith("reindex_"):
            target_type = "reindex_job"
        else:
            target_type = "verify_job"
        targets.append(
            {
                "target_type": target_type,
                "target_id": object_ref,
                "target_ref": f"{target_type}:{object_ref}",
            }
        )

    for key in ("linked_target", "followup_target", "replay_target"):
        target = _coerce_target(payload.get(key))
        if target is not None:
            targets.append(target)

    for key in ("linked_target_ref", "followup_target_ref", "replay_target_ref"):
        target = structured_target_from_ref(payload.get(key))
        if target is not None:
            targets.append(target)

    deduped: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for target in targets:
        target_ref = target["target_ref"]
        if target_ref in seen_refs:
            continue
        seen_refs.add(target_ref)
        deduped.append(target)
    return deduped


def _coerce_target(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return structured_target(value.get("target_type"), value.get("target_id"), value.get("target_ref"))


def _serialize_target_activity_groups(
    recovery_timeline: list[dict[str, Any]],
    system_runtime_timeline: list[dict[str, Any]],
    operator_action_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}

    for item in recovery_timeline:
        targets = _dedupe_targets([item.get("linked_target"), item.get("followup_target"), item.get("replay_target")])
        entry = {
            "activity_key": f"recovery_timeline:{item['event_id']}",
            "source": "recovery_timeline",
            "timestamp": item.get("last_action_at") or item.get("created_at"),
            "actor_ref": item.get("last_actor_ref"),
            "label": item.get("last_action") or item.get("default_action"),
            "status": item.get("status"),
            "summary": item.get("resolution_reason"),
            "object_ref": item.get("object_ref"),
            "target_refs": targets,
        }
        _append_target_group_entries(groups, targets, entry)

    for item in system_runtime_timeline:
        targets = _dedupe_targets(item.get("target_refs") or [])
        entry = {
            "activity_key": f"system_runtime:{item['operation_id']}",
            "source": "system_runtime",
            "timestamp": item.get("created_at"),
            "actor_ref": item.get("actor_ref"),
            "label": item.get("event_type"),
            "status": None,
            "summary": item.get("summary"),
            "object_ref": item.get("object_ref"),
            "target_refs": targets,
        }
        _append_target_group_entries(groups, targets, entry)

    for item in operator_action_timeline:
        targets = _dedupe_targets(item.get("target_refs") or [])
        entry = {
            "activity_key": f"operator_action:{item['operation_id']}",
            "source": "operator_action",
            "timestamp": item.get("created_at"),
            "actor_ref": item.get("actor_ref"),
            "label": item.get("action") or item.get("event_type"),
            "status": item.get("status_after"),
            "summary": item.get("resolution_reason"),
            "object_ref": item.get("object_ref"),
            "target_refs": targets,
        }
        _append_target_group_entries(groups, targets, entry)

    serialized: list[dict[str, Any]] = []
    for group in groups.values():
        activity_items = sorted(
            group["activity_items"],
            key=lambda item: ((item.get("timestamp") or ""), item.get("activity_key") or ""),
            reverse=True,
        )
        sources: list[str] = []
        seen_sources: set[str] = set()
        for item in activity_items:
            source = item["source"]
            if source in seen_sources:
                continue
            seen_sources.add(source)
            sources.append(source)
        serialized.append(
            {
                "target": group["target"],
                "latest_at": activity_items[0].get("timestamp") if activity_items else None,
                "activity_count": len(activity_items),
                "sources": sources,
                "activity_items": activity_items,
            }
        )
    serialized.sort(key=lambda item: ((item.get("latest_at") or ""), item["target"]["target_ref"]), reverse=True)
    return serialized


def _append_target_group_entries(
    groups: dict[str, dict[str, Any]],
    targets: list[dict[str, str]],
    entry: dict[str, Any],
) -> None:
    for target in targets:
        if target["target_type"] == "human_review_event":
            continue
        target_ref = target["target_ref"]
        group = groups.setdefault(
            target_ref,
            {
                "target": target,
                "activity_items": [],
                "_seen_keys": set(),
            },
        )
        activity_key = entry["activity_key"]
        if activity_key in group["_seen_keys"]:
            continue
        group["_seen_keys"].add(activity_key)
        group["activity_items"].append(entry)


def _dedupe_targets(targets: list[dict[str, str] | None]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for target in targets:
        if target is None:
            continue
        target_ref = target["target_ref"]
        if target_ref in seen_refs:
            continue
        seen_refs.add(target_ref)
        deduped.append(target)
    return deduped
