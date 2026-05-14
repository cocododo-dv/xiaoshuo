"""allow project-level author discovery drafts

Revision ID: 20260514_0033
Revises: 20260429_0032
Create Date: 2026-05-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260514_0033"
down_revision = "20260429_0032"
branch_labels = None
depends_on = None

AUTHOR_OBJECT_TYPE_SQL = "object_type IN ('scene','chapter','project')"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "author_drafts" in tables:
        checks = {row.get("name") for row in inspector.get_check_constraints("author_drafts")}
        if "ck_author_drafts_object_type" in checks:
            with op.batch_alter_table("author_drafts", recreate="always") as batch_op:
                batch_op.drop_constraint("ck_author_drafts_object_type", type_="check")
                batch_op.create_check_constraint("ck_author_drafts_object_type", AUTHOR_OBJECT_TYPE_SQL)

    if "author_draft_proposals" in tables:
        checks = {row.get("name") for row in inspector.get_check_constraints("author_draft_proposals")}
        if "ck_author_draft_proposals_object_type" in checks:
            with op.batch_alter_table("author_draft_proposals", recreate="always") as batch_op:
                batch_op.drop_constraint("ck_author_draft_proposals_object_type", type_="check")
                batch_op.create_check_constraint("ck_author_draft_proposals_object_type", AUTHOR_OBJECT_TYPE_SQL)

    if "author_structure_candidates" in tables:
        checks = {row.get("name") for row in inspector.get_check_constraints("author_structure_candidates")}
        if "ck_author_structure_candidates_object_type" in checks:
            with op.batch_alter_table("author_structure_candidates", recreate="always") as batch_op:
                batch_op.drop_constraint("ck_author_structure_candidates_object_type", type_="check")
                batch_op.create_check_constraint("ck_author_structure_candidates_object_type", AUTHOR_OBJECT_TYPE_SQL)


def downgrade() -> None:
    pass
