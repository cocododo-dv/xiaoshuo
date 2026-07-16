"""Constrain author preference scope and runtime eligibility.

Revision ID: 20260716_0072
Revises: 20260716_0071
Create Date: 2026-07-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260716_0072"
down_revision = "20260716_0071"
branch_labels = None
depends_on = None


TABLE_NAME = "author_preference_profiles"
SCOPE_CHECK = "ck_author_preference_profiles_scope_type"
RUNTIME_CHECK = "ck_author_preference_profiles_runtime_eligible"


def _check_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        return set()
    return {
        str(check.get("name"))
        for check in inspector.get_check_constraints(TABLE_NAME)
        if check.get("name")
    }


def _invalid_value_counts() -> tuple[int, int]:
    bind = op.get_bind()
    invalid_scope = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM author_preference_profiles "
                "WHERE scope_type IS NULL "
                "OR scope_type NOT IN ('global','genre','project','chapter')"
            )
        ).scalar_one()
    )
    invalid_runtime = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM author_preference_profiles "
                "WHERE runtime_eligible IS NULL OR runtime_eligible NOT IN (0,1)"
            )
        ).scalar_one()
    )
    return invalid_scope, invalid_runtime


def _batch_recreate_mode() -> str:
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        raise RuntimeError("author_preference_profiles table is required before revision 0072")

    invalid_scope, invalid_runtime = _invalid_value_counts()
    if invalid_scope or invalid_runtime:
        raise RuntimeError(
            "author_preference_profiles contains values that cannot be safely constrained: "
            f"invalid_scope_rows={invalid_scope}, "
            f"invalid_runtime_eligible_rows={invalid_runtime}"
        )

    existing = _check_names()
    missing_scope = SCOPE_CHECK not in existing
    missing_runtime = RUNTIME_CHECK not in existing
    if not missing_scope and not missing_runtime:
        return

    # SQLite cannot add CHECK constraints in-place, so its batch operation
    # rebuilds the table while retaining rows and the pre-existing status
    # constraint. Other databases use native ALTER TABLE operations.
    with op.batch_alter_table(TABLE_NAME, recreate=_batch_recreate_mode()) as batch_op:
        if missing_scope:
            batch_op.create_check_constraint(
                SCOPE_CHECK,
                "scope_type IN ('global','genre','project','chapter')",
            )
        if missing_runtime:
            batch_op.create_check_constraint(
                RUNTIME_CHECK,
                "runtime_eligible IN (0,1)",
            )


def downgrade() -> None:
    existing = _check_names()
    removable = [name for name in (RUNTIME_CHECK, SCOPE_CHECK) if name in existing]
    if not removable:
        return
    with op.batch_alter_table(TABLE_NAME, recreate=_batch_recreate_mode()) as batch_op:
        for name in removable:
            batch_op.drop_constraint(name, type_="check")
