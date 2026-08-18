"""Authoritative scene-to-project ownership resolution."""

from __future__ import annotations

from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, SceneCard
from novel_system.services.errors import DomainError


def require_scene_project_id(
    session: Session,
    scene: SceneCard,
    *,
    explicit_project_id: str | None = None,
) -> str:
    """Resolve ownership from relational data and reject ambiguity.

    Structured chapter identifiers are opaque identities.  They must never be
    parsed to infer a project because current IDs such as ``{project}_CH_{hex}``
    do not have a reversible delimiter contract.
    """

    chapter = session.get(ChapterGoal, scene.chapter_id)
    candidates = {
        value.strip()
        for value in (
            scene.project_id,
            chapter.project_id if chapter is not None else None,
            explicit_project_id,
        )
        if isinstance(value, str) and value.strip()
    }
    if len(candidates) > 1:
        raise DomainError(
            "PROJECT_OWNERSHIP_CONFLICT",
            "scene ownership disagrees with its chapter or execution context",
            status_code=409,
            details={
                "scene_id": scene.scene_id,
                "chapter_id": scene.chapter_id,
                "scene_project_id": scene.project_id,
                "chapter_project_id": chapter.project_id if chapter is not None else None,
                "explicit_project_id": explicit_project_id,
            },
        )
    if not candidates:
        raise DomainError(
            "PROJECT_OWNERSHIP_UNRESOLVED",
            "scene has no authoritative project ownership",
            status_code=409,
            details={
                "scene_id": scene.scene_id,
                "chapter_id": scene.chapter_id,
            },
        )
    return next(iter(candidates))
