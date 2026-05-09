"""add structured snowflake workspace tables

Revision ID: 20260428_0030
Revises: 20260428_0029
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_0030"
down_revision = "20260428_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "snowflake_step_runs" not in tables:
        op.create_table(
            "snowflake_step_runs",
            sa.Column("step_run_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("step_key", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(), nullable=False, server_default="pending_review"),
            sa.Column("draft_json", sa.JSON(), nullable=True),
            sa.Column("health_json", sa.JSON(), nullable=True),
            sa.Column("input_refs_json", sa.JSON(), nullable=True),
            sa.Column("stale_reason", sa.Text(), nullable=True),
            sa.Column("llm_call_id", sa.String(), nullable=True),
            sa.Column("approved_at", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    if "snowflake_character_plans" not in tables:
        op.create_table(
            "snowflake_character_plans",
            sa.Column("character_plan_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("character_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=True),
            sa.Column("summary_json", sa.JSON(), nullable=True),
            sa.Column("synopsis_json", sa.JSON(), nullable=True),
            sa.Column("bible_json", sa.JSON(), nullable=True),
            sa.Column("source_step_key", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("stale_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    if "snowflake_scene_plans" not in tables:
        op.create_table(
            "snowflake_scene_plans",
            sa.Column("scene_plan_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=False),
            sa.Column("chapter_title", sa.String(), nullable=True),
            sa.Column("chapter_goal", sa.Text(), nullable=True),
            sa.Column("chapter_role", sa.Text(), nullable=True),
            sa.Column("scene_seq", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("pov_character_id", sa.String(), nullable=True),
            sa.Column("onstage_chars_json", sa.JSON(), nullable=True),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("scene_type", sa.String(), nullable=False, server_default="proactive"),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("scene_crucible", sa.Text(), nullable=True),
            sa.Column("goal", sa.Text(), nullable=True),
            sa.Column("conflict", sa.Text(), nullable=True),
            sa.Column("setback", sa.Text(), nullable=True),
            sa.Column("reaction", sa.Text(), nullable=True),
            sa.Column("dilemma", sa.Text(), nullable=True),
            sa.Column("decision", sa.Text(), nullable=True),
            sa.Column("beats_json", sa.JSON(), nullable=True),
            sa.Column("must_include_text", sa.Text(), nullable=True),
            sa.Column("exit_change", sa.Text(), nullable=True),
            sa.Column("hook", sa.Text(), nullable=True),
            sa.Column("target_length_band", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("source_step_run_id", sa.String(), nullable=True),
            sa.Column("stale_reason", sa.Text(), nullable=True),
            sa.Column("diagnosis_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    if "snowflake_scene_triage_items" not in tables:
        op.create_table(
            "snowflake_scene_triage_items",
            sa.Column("triage_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("scene_plan_id", sa.String(), sa.ForeignKey("snowflake_scene_plans.scene_plan_id"), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=False),
            sa.Column("recommended_status", sa.String(), nullable=False, server_default=""),
            sa.Column("manual_status", sa.String(), nullable=False, server_default=""),
            sa.Column("effective_status", sa.String(), nullable=False, server_default=""),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("missing_fields_json", sa.JSON(), nullable=True),
            sa.Column("fix_steps_json", sa.JSON(), nullable=True),
            sa.Column("repair_patch_json", sa.JSON(), nullable=True),
            sa.Column("pressure_flags_json", sa.JSON(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("blocking", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("manual_override", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("llm_call_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    if "snowflake_revision_links" not in tables:
        op.create_table(
            "snowflake_revision_links",
            sa.Column("revision_link_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("source_step_key", sa.String(), nullable=False),
            sa.Column("source_step_run_id", sa.String(), nullable=True),
            sa.Column("affected_kind", sa.String(), nullable=False),
            sa.Column("affected_id", sa.String(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("resolved_at", sa.String(), nullable=True),
        )


def downgrade() -> None:
    pass
