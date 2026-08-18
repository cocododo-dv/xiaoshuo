"""Enforce core artifact ownership and deterministic author ordering.

Revision ID: 20260802_0078
Revises: 20260802_0077
Create Date: 2026-08-02

Historical runtime-artifact tables stored scene/chapter identifiers as plain
strings.  That allowed an artifact to outlive, or silently point outside, its
catalog parent.  Active chapter and scene positions were also indexed but not
unique, so concurrent or direct writes could create ambiguous order.

This revision repairs nullable legacy references, fails closed for orphaned
non-null audit artifacts, installs the missing foreign keys, normalizes invalid
positions, and adds partial unique indexes for active author objects.
"""

from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from alembic import op


revision = "20260802_0078"
down_revision = "20260802_0077"
branch_labels = None
depends_on = None


_NON_NULL_SCENE_TABLES = (
    "scene_bundles",
    "scene_blueprints",
    "scene_quality_contracts",
    "scene_execution_contracts",
    "scene_drafts",
    "final_scenes",
)

_NULLABLE_SCENE_TABLES = (
    "attempt_tracker",
    "chapter_run_jobs",
    "qc_reports",
    "human_review_events",
)

_LONGFORM_CHAPTER_TABLES = (
    "chapter_contracts",
    "chapter_audit_findings",
)

_FOREIGN_KEYS = (
    ("scene_bundles", "chapter_id", "chapter_goals", "chapter_id", "fk_scene_bundles_chapter_id"),
    ("scene_blueprints", "scene_id", "scene_cards", "scene_id", "fk_scene_blueprints_scene_id"),
    ("scene_blueprints", "chapter_id", "chapter_goals", "chapter_id", "fk_scene_blueprints_chapter_id"),
    (
        "scene_quality_contracts",
        "scene_id",
        "scene_cards",
        "scene_id",
        "fk_scene_quality_contracts_scene_id",
    ),
    (
        "scene_quality_contracts",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_scene_quality_contracts_chapter_id",
    ),
    (
        "scene_execution_contracts",
        "scene_id",
        "scene_cards",
        "scene_id",
        "fk_scene_execution_contracts_scene_id",
    ),
    (
        "scene_execution_contracts",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_scene_execution_contracts_chapter_id",
    ),
    (
        "scene_execution_contracts",
        "project_id",
        "story_projects",
        "project_id",
        "fk_scene_execution_contracts_project_id",
    ),
    ("scene_drafts", "scene_id", "scene_cards", "scene_id", "fk_scene_drafts_scene_id"),
    (
        "scene_drafts",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_scene_drafts_chapter_id",
    ),
    ("qc_reports", "scene_id", "scene_cards", "scene_id", "fk_qc_reports_scene_id"),
    ("qc_reports", "chapter_id", "chapter_goals", "chapter_id", "fk_qc_reports_chapter_id"),
    ("final_scenes", "scene_id", "scene_cards", "scene_id", "fk_final_scenes_scene_id"),
    (
        "final_scenes",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_final_scenes_chapter_id",
    ),
    (
        "attempt_tracker",
        "scene_id",
        "scene_cards",
        "scene_id",
        "fk_attempt_tracker_scene_id",
    ),
    (
        "attempt_tracker",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_attempt_tracker_chapter_id",
    ),
    (
        "chapter_run_jobs",
        "scene_id",
        "scene_cards",
        "scene_id",
        "fk_chapter_run_jobs_scene_id",
    ),
    (
        "chapter_run_jobs",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_chapter_run_jobs_chapter_id",
    ),
    (
        "human_review_events",
        "scene_id",
        "scene_cards",
        "scene_id",
        "fk_human_review_events_scene_id",
    ),
    (
        "human_review_events",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_human_review_events_chapter_id",
    ),
    (
        "chapter_contracts",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_chapter_contracts_chapter_id",
    ),
    (
        "chapter_audit_findings",
        "chapter_id",
        "chapter_goals",
        "chapter_id",
        "fk_chapter_audit_findings_chapter_id",
    ),
)

_CHECKS = (
    (
        "chapter_goals",
        "ck_chapter_goals_display_order_nonnegative",
        "display_order IS NULL OR display_order >= 0",
    ),
    (
        "scene_cards",
        "ck_scene_cards_scene_seq_positive",
        "scene_seq >= 1",
    ),
)

_ORDER_INDEXES = (
    (
        "ux_chapter_goals_active_project_display_order",
        "chapter_goals",
        ["project_id", "display_order"],
        "trashed_flag = 0 AND project_id IS NOT NULL AND display_order IS NOT NULL",
    ),
    (
        "ux_scene_cards_active_chapter_scene_seq",
        "scene_cards",
        ["chapter_id", "scene_seq"],
        "trashed_flag = 0",
    ),
)

_IDENTITY_INDEXES = (
    (
        "ux_chapter_contracts_project_chapter",
        "chapter_contracts",
        ["project_id", "chapter_id"],
    ),
)


def _require_schema(bind) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required = {
        "story_projects",
        "outline_plans",
        "chapter_goals",
        "scene_cards",
        *_NON_NULL_SCENE_TABLES,
        *_NULLABLE_SCENE_TABLES,
        *_LONGFORM_CHAPTER_TABLES,
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "cannot enforce core artifact integrity; missing tables: "
            + ", ".join(missing)
        )
    required_columns = {
        "chapter_goals": {"chapter_id", "project_id", "outline_plan_id", "display_order", "trashed_flag"},
        "scene_cards": {
            "scene_id",
            "chapter_id",
            "project_id",
            "outline_plan_id",
            "scene_seq",
            "trashed_flag",
        },
    }
    for table_name in (*_NON_NULL_SCENE_TABLES, *_NULLABLE_SCENE_TABLES):
        required_columns[table_name] = {"scene_id", "chapter_id"}
    for table_name in _LONGFORM_CHAPTER_TABLES:
        required_columns[table_name] = {"project_id", "chapter_id"}
    required_columns["scene_execution_contracts"].add("project_id")
    for table_name, expected in required_columns.items():
        actual = {
            str(column["name"])
            for column in inspector.get_columns(table_name)
        }
        missing_columns = sorted(expected - actual)
        if missing_columns:
            raise RuntimeError(
                "cannot enforce core artifact integrity; missing columns in "
                f"{table_name}: {', '.join(missing_columns)}"
            )


def _null_invalid_reference(
    bind,
    *,
    child_table: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
) -> None:
    bind.execute(
        sa.text(
            f"UPDATE {child_table} AS child SET {child_column} = NULL "
            f"WHERE {child_column} IS NOT NULL AND NOT EXISTS ("
            f"SELECT 1 FROM {parent_table} AS parent "
            f"WHERE parent.{parent_column} = child.{child_column})"
        )
    )


def _repair_catalog_references(bind) -> None:
    _null_invalid_reference(
        bind,
        child_table="chapter_goals",
        child_column="project_id",
        parent_table="story_projects",
        parent_column="project_id",
    )
    _null_invalid_reference(
        bind,
        child_table="chapter_goals",
        child_column="outline_plan_id",
        parent_table="outline_plans",
        parent_column="plan_id",
    )
    invalid_scene_chapters = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM scene_cards AS scene "
                "WHERE NOT EXISTS (SELECT 1 FROM chapter_goals AS chapter "
                "WHERE chapter.chapter_id = scene.chapter_id)"
            )
        ).scalar_one()
    )
    if invalid_scene_chapters:
        raise RuntimeError(
            "CORE_PARENT_REFERENCE_INVALID: "
            f"scene_cards.chapter_id has {invalid_scene_chapters} orphan row(s)"
        )
    _null_invalid_reference(
        bind,
        child_table="scene_cards",
        child_column="project_id",
        parent_table="story_projects",
        parent_column="project_id",
    )
    _null_invalid_reference(
        bind,
        child_table="scene_cards",
        child_column="outline_plan_id",
        parent_table="outline_plans",
        parent_column="plan_id",
    )
    # A chapter with explicit project ownership is authoritative for its scenes.
    bind.execute(
        sa.text(
            "UPDATE scene_cards AS scene SET project_id = ("
            "SELECT chapter.project_id FROM chapter_goals AS chapter "
            "WHERE chapter.chapter_id = scene.chapter_id) "
            "WHERE EXISTS (SELECT 1 FROM chapter_goals AS chapter "
            "WHERE chapter.chapter_id = scene.chapter_id "
            "AND chapter.project_id IS NOT NULL)"
        )
    )


def _repair_artifact_references(bind) -> None:
    for table_name in _NON_NULL_SCENE_TABLES:
        orphan_count = int(
            bind.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {table_name} AS child "
                    "WHERE NOT EXISTS (SELECT 1 FROM scene_cards AS scene "
                    "WHERE scene.scene_id = child.scene_id)"
                )
            ).scalar_one()
        )
        if orphan_count:
            raise RuntimeError(
                "CORE_PARENT_REFERENCE_INVALID: "
                f"{table_name}.scene_id has {orphan_count} orphan row(s)"
            )
        bind.execute(
            sa.text(
                f"UPDATE {table_name} AS child SET chapter_id = ("
                "SELECT scene.chapter_id FROM scene_cards AS scene "
                "WHERE scene.scene_id = child.scene_id)"
            )
        )

    for table_name in _NULLABLE_SCENE_TABLES:
        _null_invalid_reference(
            bind,
            child_table=table_name,
            child_column="scene_id",
            parent_table="scene_cards",
            parent_column="scene_id",
        )
        bind.execute(
            sa.text(
                f"UPDATE {table_name} AS child SET chapter_id = ("
                "SELECT scene.chapter_id FROM scene_cards AS scene "
                "WHERE scene.scene_id = child.scene_id) "
                "WHERE child.scene_id IS NOT NULL"
            )
        )
        _null_invalid_reference(
            bind,
            child_table=table_name,
            child_column="chapter_id",
            parent_table="chapter_goals",
            parent_column="chapter_id",
        )

    # project_id is optional; retain the contract while replacing an impossible
    # or mismatched value with the scene's real, still-existing project owner.
    bind.execute(
        sa.text(
            "UPDATE scene_execution_contracts AS contract SET project_id = ("
            "SELECT project.project_id FROM scene_cards AS scene "
            "LEFT JOIN story_projects AS project "
            "ON project.project_id = scene.project_id "
            "WHERE scene.scene_id = contract.scene_id)"
        )
    )


def _repair_longform_references(bind) -> None:
    for table_name in _LONGFORM_CHAPTER_TABLES:
        invalid_count = int(
            bind.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {table_name} AS child "
                    "LEFT JOIN chapter_goals AS chapter "
                    "ON chapter.chapter_id = child.chapter_id "
                    "WHERE chapter.chapter_id IS NULL "
                    "OR chapter.project_id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_count:
            raise RuntimeError(
                "CORE_PARENT_REFERENCE_INVALID: "
                f"{table_name}.chapter_id has {invalid_count} orphan or unowned row(s)"
            )
        # Chapter ownership is authoritative.  This repairs legacy rows that
        # paired a real chapter with the wrong project before the API enforced
        # project/chapter isolation.
        bind.execute(
            sa.text(
                f"UPDATE {table_name} AS child SET project_id = ("
                "SELECT chapter.project_id FROM chapter_goals AS chapter "
                "WHERE chapter.chapter_id = child.chapter_id)"
            )
        )

    duplicate_contracts = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM ("
                "SELECT project_id, chapter_id FROM chapter_contracts "
                "GROUP BY project_id, chapter_id HAVING COUNT(*) > 1"
                ") AS duplicate_contracts"
            )
        ).scalar_one()
    )
    if duplicate_contracts:
        raise RuntimeError(
            "CORE_IDENTITY_CONFLICT: chapter_contracts has "
            f"{duplicate_contracts} duplicate project/chapter pair(s)"
        )


def _repair_chapter_orders(bind) -> None:
    rows = [
        dict(row)
        for row in bind.execute(
            sa.text(
                "SELECT chapter_id, project_id, display_order, trashed_flag "
                "FROM chapter_goals ORDER BY project_id, chapter_id"
            )
        ).mappings()
    ]
    by_project: dict[str | None, list[dict]] = defaultdict(list)
    for row in rows:
        by_project[row["project_id"]].append(row)

    for project_id, project_rows in by_project.items():
        next_order = max(
            (
                int(row["display_order"])
                for row in project_rows
                if row["display_order"] is not None
                and int(row["display_order"]) >= 0
            ),
            default=0,
        ) + 1
        for row in project_rows:
            if row["display_order"] is None or int(row["display_order"]) >= 0:
                continue
            replacement = None if project_id is None else next_order
            bind.execute(
                sa.text(
                    "UPDATE chapter_goals SET display_order = :display_order "
                    "WHERE chapter_id = :chapter_id"
                ),
                {
                    "display_order": replacement,
                    "chapter_id": row["chapter_id"],
                },
            )
            row["display_order"] = replacement
            if replacement is not None:
                next_order += 1

        occupied: set[int] = set()
        for row in project_rows:
            if (
                project_id is None
                or int(row["trashed_flag"] or 0) != 0
                or row["display_order"] is None
            ):
                continue
            order = int(row["display_order"])
            if order not in occupied:
                occupied.add(order)
                continue
            bind.execute(
                sa.text(
                    "UPDATE chapter_goals SET display_order = :display_order "
                    "WHERE chapter_id = :chapter_id"
                ),
                {"display_order": next_order, "chapter_id": row["chapter_id"]},
            )
            row["display_order"] = next_order
            occupied.add(next_order)
            next_order += 1


def _repair_scene_orders(bind) -> None:
    rows = [
        dict(row)
        for row in bind.execute(
            sa.text(
                "SELECT scene_id, chapter_id, scene_seq, trashed_flag "
                "FROM scene_cards ORDER BY chapter_id, scene_id"
            )
        ).mappings()
    ]
    by_chapter: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_chapter[str(row["chapter_id"])].append(row)

    for chapter_rows in by_chapter.values():
        next_seq = max(
            (
                int(row["scene_seq"])
                for row in chapter_rows
                if row["scene_seq"] is not None and int(row["scene_seq"]) >= 1
            ),
            default=0,
        ) + 1
        for row in chapter_rows:
            if row["scene_seq"] is not None and int(row["scene_seq"]) >= 1:
                continue
            bind.execute(
                sa.text(
                    "UPDATE scene_cards SET scene_seq = :scene_seq "
                    "WHERE scene_id = :scene_id"
                ),
                {"scene_seq": next_seq, "scene_id": row["scene_id"]},
            )
            row["scene_seq"] = next_seq
            next_seq += 1

        occupied: set[int] = set()
        for row in chapter_rows:
            if int(row["trashed_flag"] or 0) != 0:
                continue
            seq = int(row["scene_seq"])
            if seq not in occupied:
                occupied.add(seq)
                continue
            bind.execute(
                sa.text(
                    "UPDATE scene_cards SET scene_seq = :scene_seq "
                    "WHERE scene_id = :scene_id"
                ),
                {"scene_seq": next_seq, "scene_id": row["scene_id"]},
            )
            row["scene_seq"] = next_seq
            occupied.add(next_seq)
            next_seq += 1


def _has_foreign_key(
    inspector: sa.Inspector,
    *,
    table_name: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
) -> bool:
    return any(
        tuple(foreign_key.get("constrained_columns") or ()) == (child_column,)
        and str(foreign_key.get("referred_table") or "") == parent_table
        and tuple(foreign_key.get("referred_columns") or ()) == (parent_column,)
        for foreign_key in inspector.get_foreign_keys(table_name)
    )


def _install_constraints(bind) -> None:
    inspector = sa.inspect(bind)
    missing_fks: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for table_name, child_column, parent_table, parent_column, name in _FOREIGN_KEYS:
        if not _has_foreign_key(
            inspector,
            table_name=table_name,
            child_column=child_column,
            parent_table=parent_table,
            parent_column=parent_column,
        ):
            missing_fks[table_name].append(
                (name, child_column, parent_table, parent_column)
            )

    existing_checks = {
        table_name: {
            str(check.get("name") or "")
            for check in inspector.get_check_constraints(table_name)
        }
        for table_name, _name, _condition in _CHECKS
    }
    checks_by_table = {
        table_name: (name, condition)
        for table_name, name, condition in _CHECKS
        if name not in existing_checks[table_name]
    }

    table_names = sorted(set(missing_fks) | set(checks_by_table))
    for table_name in table_names:
        with op.batch_alter_table(table_name) as batch_op:
            for name, child_column, parent_table, parent_column in missing_fks.get(
                table_name, []
            ):
                batch_op.create_foreign_key(
                    name,
                    parent_table,
                    [child_column],
                    [parent_column],
                )
            check = checks_by_table.get(table_name)
            if check is not None:
                name, condition = check
                batch_op.create_check_constraint(name, condition)


def _install_order_indexes(bind) -> None:
    inspector = sa.inspect(bind)
    for index_name, table_name, columns, predicate in _ORDER_INDEXES:
        existing = {
            str(index.get("name") or "")
            for index in inspector.get_indexes(table_name)
        }
        if index_name in existing:
            continue
        op.create_index(
            index_name,
            table_name,
            columns,
            unique=True,
            sqlite_where=sa.text(predicate),
            postgresql_where=sa.text(predicate),
        )

    inspector = sa.inspect(bind)
    for index_name, table_name, columns in _IDENTITY_INDEXES:
        existing = {
            str(index.get("name") or "")
            for index in inspector.get_indexes(table_name)
        }
        if index_name in existing:
            continue
        op.create_index(index_name, table_name, columns, unique=True)


def upgrade() -> None:
    bind = op.get_bind()
    _require_schema(bind)
    _repair_catalog_references(bind)
    _repair_artifact_references(bind)
    _repair_longform_references(bind)
    _repair_chapter_orders(bind)
    _repair_scene_orders(bind)
    _install_constraints(bind)
    _install_order_indexes(bind)


def downgrade() -> None:
    raise RuntimeError(
        "20260802_0078 is intentionally irreversible: it canonically repairs "
        "parent references and ambiguous author ordering before enforcing them"
    )
