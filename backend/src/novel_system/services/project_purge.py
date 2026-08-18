"""Complete project ownership planning for irreversible purge operations.

Project-owned rows use several historical ownership shapes: direct ``project_id``,
scoped ``scope_ref_id``, scene/chapter/character references, and version/vector
registries.  Keeping the indirect inventory here prevents the trash service from
growing another hand-maintained deletion block and gives external vector cleanup a
deterministic plan that can be verified before the relational rows disappear.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorPreferenceProfile,
    BannedRuleCluster,
    CalibrationLine,
    InteropArtifact,
    LongformStructureGuidance,
    NarrativePattern,
    ReconcileFault,
    ReindexJob,
    RelationProfile,
    ReviewItem,
    SceneBundle,
    StyleObservation,
    StyleReferenceInjectionBinding,
    StyleRule,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
    VoiceProfile,
    WorkProfile,
    WorldRule,
)
from novel_system.services.errors import DomainError
from novel_system.services.vector_store import VectorStore


_SCOPED_KNOWLEDGE_MODELS = (
    StyleObservation,
    StyleRule,
    NarrativePattern,
    BannedRuleCluster,
    WorldRule,
    CalibrationLine,
)


@dataclass(frozen=True)
class ProjectPurgePlan:
    project_id: str
    chapter_ids: tuple[str, ...]
    scene_ids: tuple[str, ...]
    character_ids: tuple[str, ...]
    bundle_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    knowledge_row_ids: tuple[str, ...]
    alias_scopes: tuple[str, ...]
    vector_collections: tuple[str, ...]

    @property
    def scope_ref_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.project_id,
                    *self.chapter_ids,
                    *self.scene_ids,
                    *self.character_ids,
                )
            )
        )


def build_project_purge_plan(
    session: Session,
    *,
    project_id: str,
    chapter_ids: list[str],
    scene_ids: list[str],
    character_ids: list[str],
) -> ProjectPurgePlan:
    chapters = tuple(dict.fromkeys(chapter_ids))
    scenes = tuple(dict.fromkeys(scene_ids))
    characters = tuple(dict.fromkeys(character_ids))
    refs = tuple(dict.fromkeys((project_id, *chapters, *scenes, *characters)))

    bundle_ids = tuple(
        session.execute(
            select(SceneBundle.bundle_id).where(
                SceneBundle.scene_id.in_(scenes or ("",))
                | SceneBundle.chapter_id.in_(chapters or ("",))
            )
        ).scalars().all()
    )
    review_ids = tuple(
        session.execute(
            select(ReviewItem.review_id).where(
                (ReviewItem.project_id == project_id)
                | ReviewItem.scene_id.in_(scenes or ("",))
                | ReviewItem.chapter_id.in_(chapters or ("",))
            )
        ).scalars().all()
    )

    knowledge_row_ids: set[str] = set()
    for model in _SCOPED_KNOWLEDGE_MODELS:
        knowledge_row_ids.update(
            str(row_id)
            for row_id in session.execute(
                select(model.row_id).where(model.scope_ref_id.in_(refs))
            ).scalars().all()
        )
    if characters:
        knowledge_row_ids.update(
            str(row_id)
            for row_id in session.execute(
                select(VoiceProfile.row_id).where(VoiceProfile.character_id.in_(characters))
            ).scalars().all()
        )
        knowledge_row_ids.update(
            str(row_id)
            for row_id in session.execute(
                select(RelationProfile.row_id).where(
                    RelationProfile.left_character_id.in_(characters)
                    | RelationProfile.right_character_id.in_(characters)
                )
            ).scalars().all()
        )

    aliases = session.execute(
        select(VectorAliasRegistry).where(VectorAliasRegistry.scope_ref_id.in_(refs))
    ).scalars().all()
    alias_scopes = tuple(dict.fromkeys(alias.alias_scope for alias in aliases))
    collection_names: set[str] = {f"scenes_{project_id}"}
    for alias in aliases:
        if alias.active_alias:
            collection_names.add(alias.active_alias)
        if alias.candidate_alias:
            collection_names.add(alias.candidate_alias)

    if alias_scopes or knowledge_row_ids:
        registry_rows = session.execute(
            select(VersionRegistry).where(
                or_(
                    VersionRegistry.alias_scope.in_(alias_scopes or ("",)),
                    VersionRegistry.physical_row_id.in_(knowledge_row_ids or {""}),
                )
            )
        ).scalars().all()
        family_by_scope = {alias.alias_scope: alias.collection_family for alias in aliases}
        for registry in registry_rows:
            knowledge_row_ids.add(registry.physical_row_id)
            family = family_by_scope.get(registry.alias_scope or "")
            if family:
                collection_names.add(f"{family}__candidate__{registry.physical_row_id}")

    return ProjectPurgePlan(
        project_id=project_id,
        chapter_ids=chapters,
        scene_ids=scenes,
        character_ids=characters,
        bundle_ids=tuple(dict.fromkeys(bundle_ids)),
        review_ids=tuple(dict.fromkeys(review_ids)),
        knowledge_row_ids=tuple(sorted(knowledge_row_ids)),
        alias_scopes=alias_scopes,
        vector_collections=tuple(sorted(collection_names)),
    )


def purge_project_vectors(plan: ProjectPurgePlan, vector_store: VectorStore) -> tuple[str, ...]:
    """Delete and verify every known external vector collection.

    External deletion deliberately runs before the database transaction removes
    the ownership metadata.  A database failure can rebuild vectors from retained
    rows; deleting the database first would make an external privacy leak
    impossible to discover or repair deterministically.
    """

    deleted: list[str] = []
    for collection_name in plan.vector_collections:
        try:
            vector_store.delete_collection(collection_name)
            collection_remains = vector_store.collection_exists(collection_name)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "PROJECT_VECTOR_PURGE_FAILED",
                "project vector collection could not be permanently deleted",
                status_code=503,
                details={
                    "project_id": plan.project_id,
                    "collection_name": collection_name,
                    "retryable": True,
                },
            ) from exc
        if collection_remains:
            raise DomainError(
                "PROJECT_VECTOR_PURGE_FAILED",
                "project vector collection still exists after deletion",
                status_code=503,
                details={
                    "project_id": plan.project_id,
                    "collection_name": collection_name,
                    "retryable": True,
                },
            )
        deleted.append(collection_name)
    return tuple(deleted)


def delete_indirect_project_rows(session: Session, plan: ProjectPurgePlan) -> dict[str, int]:
    """Delete project-owned rows that cannot be discovered from ``project_id``."""

    refs = plan.scope_ref_ids
    counts: dict[str, int] = {}

    def execute(stmt: Any, key: str) -> None:
        result = session.execute(stmt)
        counts[key] = counts.get(key, 0) + max(int(result.rowcount or 0), 0)

    if plan.alias_scopes or plan.review_ids:
        job_filter = or_(
            ReindexJob.alias_scope.in_(plan.alias_scopes or ("",)),
            ReindexJob.review_id.in_(plan.review_ids or ("",)),
        )
        execute(delete(ReindexJob).where(job_filter), "reindex_jobs")
        verify_filter = or_(
            VerifyJob.alias_scope.in_(plan.alias_scopes or ("",)),
            VerifyJob.review_id.in_(plan.review_ids or ("",)),
        )
        execute(delete(VerifyJob).where(verify_filter), "verify_jobs")

    if plan.alias_scopes or plan.knowledge_row_ids:
        registry_filter = or_(
            VersionRegistry.alias_scope.in_(plan.alias_scopes or ("",)),
            VersionRegistry.physical_row_id.in_(plan.knowledge_row_ids or ("",)),
        )
        execute(delete(VersionRegistry).where(registry_filter), "version_registry")
        execute(
            delete(ReconcileFault).where(
                ReconcileFault.object_ref.in_(
                    (*plan.alias_scopes, *plan.knowledge_row_ids) or ("",)
                )
            ),
            "reconcile_faults",
        )

    execute(
        delete(VectorAliasRegistry).where(VectorAliasRegistry.scope_ref_id.in_(refs)),
        "vector_alias_registry",
    )
    execute(
        delete(StyleReferenceInjectionBinding).where(
            StyleReferenceInjectionBinding.scope_ref_id.in_(refs)
        ),
        "style_reference_injection_bindings",
    )
    execute(
        delete(AuthorPreferenceProfile).where(
            AuthorPreferenceProfile.scope_ref_id.in_(refs)
        ),
        "author_preference_profiles",
    )
    execute(
        delete(WorkProfile).where(WorkProfile.scope_ref_id.in_(refs)),
        "work_profiles",
    )
    execute(
        delete(LongformStructureGuidance).where(
            LongformStructureGuidance.scope_ref_id.in_(refs)
        ),
        "longform_structure_guidance",
    )

    for model in _SCOPED_KNOWLEDGE_MODELS:
        execute(
            delete(model).where(model.scope_ref_id.in_(refs)),
            model.__tablename__,
        )

    if plan.character_ids:
        execute(
            delete(VoiceProfile).where(VoiceProfile.character_id.in_(plan.character_ids)),
            "voice_profiles",
        )
        execute(
            delete(RelationProfile).where(
                RelationProfile.left_character_id.in_(plan.character_ids)
                | RelationProfile.right_character_id.in_(plan.character_ids)
            ),
            "relation_profiles",
        )

    execute(
        delete(InteropArtifact).where(
            InteropArtifact.scene_id.in_(plan.scene_ids or ("",))
            | InteropArtifact.chapter_id.in_(plan.chapter_ids or ("",))
            | InteropArtifact.source_bundle_id.in_(plan.bundle_ids or ("",))
        ),
        "interop_artifacts",
    )
    return counts
