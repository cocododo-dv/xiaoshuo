"""add scene quality contracts and auto rewrite runs

Revision ID: 20260426_0023
Revises: 20260426_0022
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0023"
down_revision = "20260426_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "scene_quality_contracts" not in tables:
        op.create_table(
            "scene_quality_contracts",
            sa.Column("contract_id", sa.String(), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=False),
            sa.Column("contract_version", sa.String(), nullable=False),
            sa.Column("contract_hash", sa.String(), nullable=False),
            sa.Column("source_snapshot_hash", sa.String(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint("status IN ('active','superseded')", name="ck_scene_quality_contracts_status"),
            sa.PrimaryKeyConstraint("contract_id"),
        )

    if "auto_rewrite_runs" not in tables:
        op.create_table(
            "auto_rewrite_runs",
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=False),
            sa.Column("contract_id", sa.String(), nullable=True),
            sa.Column("contract_hash", sa.String(), nullable=True),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("branch", sa.String(), nullable=False),
            sa.Column("failure_class", sa.String(), nullable=True),
            sa.Column("source_final_scene_row_id", sa.String(), nullable=True),
            sa.Column("candidate_draft_row_id", sa.String(), nullable=True),
            sa.Column("promoted_final_scene_row_id", sa.String(), nullable=True),
            sa.Column("rollback_target_final_scene_row_id", sa.String(), nullable=True),
            sa.Column("llm_call_id", sa.String(), nullable=True),
            sa.Column("gate_results_json", sa.JSON(), nullable=False),
            sa.Column("policy_json", sa.JSON(), nullable=False),
            sa.Column("promotion_blockers_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("actor_ref", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status IN ('diagnosed','candidate_ready','human_review_required','promoted','rolled_back','blocked')",
                name="ck_auto_rewrite_runs_status",
            ),
            sa.CheckConstraint(
                "branch IN ('full_scene','local_patch','human_review','diagnose_only')",
                name="ck_auto_rewrite_runs_branch",
            ),
            sa.PrimaryKeyConstraint("run_id"),
        )

    if "writer_evaluations" in tables:
        columns = {column["name"] for column in inspector.get_columns("writer_evaluations")}
        with op.batch_alter_table("writer_evaluations") as batch_op:
            if "failure_class" not in columns:
                batch_op.add_column(sa.Column("failure_class", sa.String(), nullable=True))
            if "auto_rewrite_eligible" not in columns:
                batch_op.add_column(sa.Column("auto_rewrite_eligible", sa.Integer(), nullable=True))
            if "contract_field_refs_json" not in columns:
                batch_op.add_column(sa.Column("contract_field_refs_json", sa.JSON(), nullable=True))
            if "promotion_blockers_json" not in columns:
                batch_op.add_column(sa.Column("promotion_blockers_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    pass
