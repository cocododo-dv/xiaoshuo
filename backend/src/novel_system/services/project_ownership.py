"""Single source of truth for rows directly owned by a story project.

Every ORM table that carries ``project_id`` is project-scoped by construction.
Keeping this inventory derived from SQLAlchemy metadata prevents purge/reset
code from silently missing a newly introduced project model.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import Table, delete
from sqlalchemy.orm import Session

from novel_system.db import models as _models  # noqa: F401 - register all mappers
from novel_system.db.base import Base


@lru_cache(maxsize=1)
def project_owned_tables_child_first() -> tuple[Table, ...]:
    """Return every non-root table with ``project_id`` in FK-safe delete order."""

    return tuple(
        table
        for table in reversed(Base.metadata.sorted_tables)
        if table.name != "story_projects" and "project_id" in table.c
    )


@lru_cache(maxsize=1)
def project_owned_models_child_first() -> tuple[type[Any], ...]:
    model_by_table = {
        mapper.local_table: mapper.class_
        for mapper in Base.registry.mappers
    }
    missing_mappers = [
        table.name
        for table in project_owned_tables_child_first()
        if table not in model_by_table
    ]
    if missing_mappers:
        raise RuntimeError(
            "project-owned tables are missing ORM mappers: "
            + ", ".join(sorted(missing_mappers))
        )
    return tuple(
        model_by_table[table] for table in project_owned_tables_child_first()
    )


def delete_project_owned_rows(session: Session, project_id: str) -> dict[str, int]:
    """Delete every directly project-scoped row, children before parents."""

    deleted: dict[str, int] = {}
    for table in project_owned_tables_child_first():
        result = session.execute(
            delete(table).where(table.c.project_id == project_id)
        )
        deleted[table.name] = max(int(result.rowcount or 0), 0)
    return deleted
