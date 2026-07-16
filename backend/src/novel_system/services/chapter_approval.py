from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import ChapterGoal, SceneCard, StoryProject
from novel_system.services.errors import DomainError


APPROVED_CHAPTER_LOCK_CODE = "CHAPTER_APPROVED_LOCKED"
APPROVED_CHAPTER_LOCK_MESSAGE = (
    "approved chapter must be explicitly reopened before it or its scenes can change"
)


def is_chapter_approved(session: Session, chapter: ChapterGoal) -> bool:
    """Treat either persisted approval projection as authoritative, fail-closed.

    ``ChapterGoal.state`` and ``StoryProject.approved_chapter_ids_json`` are kept
    in sync by the project approval flow, but historical/imported data may have
    only one projection populated.  A write guard must therefore lock on either
    signal instead of allowing a drifted row to bypass approval immutability.
    """

    if str(chapter.state or "").strip() == "approved":
        return True
    if not chapter.project_id:
        return False
    project = session.get(StoryProject, chapter.project_id)
    return bool(
        project is not None
        and chapter.chapter_id in set(project.approved_chapter_ids_json or [])
    )


def require_chapter_mutation_allowed(
    session: Session,
    chapter: ChapterGoal,
    *,
    changed_fields: Iterable[str],
    operation: str,
) -> bool:
    """Reject actual writes to an approved chapter; true no-ops stay idempotent.

    Returns ``True`` when at least one field would change and ``False`` for a
    no-op.  Callers can expose that distinction in their response without
    touching timestamps, revision counters, audit rows, or related state.
    """

    fields = list(dict.fromkeys(str(field) for field in changed_fields if str(field)))
    if not fields:
        return False
    if is_chapter_approved(session, chapter):
        raise DomainError(
            APPROVED_CHAPTER_LOCK_CODE,
            APPROVED_CHAPTER_LOCK_MESSAGE,
            status_code=409,
            details={
                "project_id": chapter.project_id,
                "chapter_id": chapter.chapter_id,
                "operation": operation,
                "changed_fields": fields,
                "reopen_required": True,
            },
        )
    return True


def chapter_for_author_target(
    session: Session,
    object_type: str,
    object_id: str,
) -> ChapterGoal | None:
    if object_type == "chapter":
        return session.get(ChapterGoal, object_id)
    if object_type != "scene":
        return None
    scene = session.get(SceneCard, object_id)
    if scene is None:
        return None
    return session.get(ChapterGoal, scene.chapter_id)


def require_author_target_mutation_allowed(
    session: Session,
    *,
    object_type: str,
    object_id: str,
    changed_fields: Iterable[str],
    operation: str,
) -> bool:
    chapter = chapter_for_author_target(session, object_type, object_id)
    if chapter is None:
        return bool(list(changed_fields))
    return require_chapter_mutation_allowed(
        session,
        chapter,
        changed_fields=changed_fields,
        operation=operation,
    )


def approved_chapter_block(
    session: Session,
    chapter: ChapterGoal,
    *,
    object_id_key: str,
    object_id: str,
    operation: str,
) -> dict[str, Any] | None:
    """Batch lifecycle APIs report per-item blockers instead of raising."""

    if not is_chapter_approved(session, chapter):
        return None
    return {
        object_id_key: object_id,
        "code": APPROVED_CHAPTER_LOCK_CODE,
        "message": APPROVED_CHAPTER_LOCK_MESSAGE,
        "chapter_id": chapter.chapter_id,
        "project_id": chapter.project_id,
        "operation": operation,
        "reopen_required": True,
    }
