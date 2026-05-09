"""add scene execution contracts and project backtracks

Revision ID: 20260427_0027
Revises: 20260426_0026
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260427_0027"
down_revision = "20260426_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    _add_nullable_column(
        "scene_drafts",
        "status",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    _add_nullable_column(
        "qc_reports",
        "status",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )

    tables = set(sa.inspect(bind).get_table_names())
    if "scene_execution_contracts" not in tables:
        op.create_table(
            "scene_execution_contracts",
            sa.Column("contract_id", sa.String(), primary_key=True),
            sa.Column("scene_id", sa.String(), sa.ForeignKey("scene_cards.scene_id"), nullable=False),
            sa.Column("chapter_id", sa.String(), sa.ForeignKey("chapter_goals.chapter_id"), nullable=False),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=True),
            sa.Column("contract_version", sa.String(), nullable=False),
            sa.Column("source_snapshot_hash", sa.String(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("missing_fields_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(), nullable=False, server_default="operator"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status in ('active','blocked','stale','superseded')",
                name="ck_scene_execution_contract_status",
            ),
        )

    if "project_backtrack_items" not in tables:
        op.create_table(
            "project_backtrack_items",
            sa.Column("item_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("chapter_id", sa.String(), sa.ForeignKey("chapter_goals.chapter_id"), nullable=True),
            sa.Column("scene_id", sa.String(), sa.ForeignKey("scene_cards.scene_id"), nullable=True),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("target_ref", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("problem_summary", sa.Text(), nullable=False),
            sa.Column("recommended_fix", sa.Text(), nullable=False),
            sa.Column("reason_codes_json", sa.JSON(), nullable=True),
            sa.Column("source_qc_report_id", sa.String(), sa.ForeignKey("qc_reports.qc_report_id"), nullable=True),
            sa.Column("source_contract_id", sa.String(), sa.ForeignKey("scene_execution_contracts.contract_id"), nullable=True),
            sa.Column("resolution_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False, server_default="scene_triage"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status in ('pending','resolved','superseded')",
                name="ck_project_backtrack_status",
            ),
        )


def downgrade() -> None:
    pass


def _add_nullable_column(table_name: str, column_name: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    columns = {existing["name"] for existing in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(column)
