"""blueprint v2 schema drift: scene constraint/criticality + memory_kind + volume_summaries

The "蓝图质量地板 v2" model changes added several ORM columns and one table that
never received a migration, leaving existing databases behind `Base` and causing
`OperationalError: no such column: scene_cards.constraint_intensity` (and friends)
on every read of those tables — which broke the dev backend health check.

This migration closes that drift:
- scene_cards.constraint_intensity (§16 breathing-gap slider)
- scene_run_states.candidate_dispersion_score / criticality_level / criticality_reasons_json (§6)
- chapter_memories.memory_kind (§2 summary tower)
- volume_summaries table (§2 summary tower, volume-level atmosphere digest)

All steps are guarded so the migration is safe to run against databases that may
already have some of these objects (e.g. created via auto_create_tables).

Revision ID: 20260618_0059
Revises: 20260618_0058
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "20260618_0059"
down_revision = "20260618_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- scene_cards.constraint_intensity (§16 breathing gap) ---
    if inspector.has_table("scene_cards"):
        sc_cols = {col["name"] for col in inspector.get_columns("scene_cards")}
        if "constraint_intensity" not in sc_cols:
            op.add_column(
                "scene_cards",
                sa.Column("constraint_intensity", sa.Float(), nullable=True),
            )

    # --- scene_run_states.{candidate_dispersion_score,criticality_*} (§6) ---
    if inspector.has_table("scene_run_states"):
        srs_cols = {col["name"] for col in inspector.get_columns("scene_run_states")}
        if "candidate_dispersion_score" not in srs_cols:
            op.add_column(
                "scene_run_states",
                sa.Column("candidate_dispersion_score", sa.Float(), nullable=True),
            )
        if "criticality_level" not in srs_cols:
            op.add_column(
                "scene_run_states",
                sa.Column("criticality_level", sa.String(), nullable=True),
            )
        if "criticality_reasons_json" not in srs_cols:
            op.add_column(
                "scene_run_states",
                sa.Column("criticality_reasons_json", sa.JSON(), nullable=True),
            )

    # --- chapter_memories.memory_kind (§2 summary tower) ---
    if inspector.has_table("chapter_memories"):
        cm_cols = {col["name"] for col in inspector.get_columns("chapter_memories")}
        if "memory_kind" not in cm_cols:
            # NOT NULL on a populated table requires a server_default to backfill
            # existing rows; "mixed" is the documented legacy value.
            op.add_column(
                "chapter_memories",
                sa.Column(
                    "memory_kind",
                    sa.String(),
                    nullable=False,
                    server_default="mixed",
                ),
            )

    # --- volume_summaries table (§2 summary tower) ---
    if not inspector.has_table("volume_summaries"):
        op.create_table(
            "volume_summaries",
            sa.Column("row_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("volume_seq", sa.Integer(), nullable=False),
            sa.Column("chapter_id_start", sa.String(), nullable=True),
            sa.Column("chapter_id_end", sa.String(), nullable=True),
            sa.Column("chapter_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("atmosphere_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("factual_digest", sa.Text(), nullable=True),
            sa.Column("active_flag", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("runtime_eligible", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "runtime_eligibility_basis",
                sa.String(),
                nullable=False,
                server_default="direct_read",
            ),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("volume_summaries"):
        op.drop_table("volume_summaries")

    if inspector.has_table("chapter_memories"):
        cm_cols = {col["name"] for col in inspector.get_columns("chapter_memories")}
        if "memory_kind" in cm_cols:
            op.drop_column("chapter_memories", "memory_kind")

    if inspector.has_table("scene_run_states"):
        srs_cols = {col["name"] for col in inspector.get_columns("scene_run_states")}
        for name in ("criticality_reasons_json", "criticality_level", "candidate_dispersion_score"):
            if name in srs_cols:
                op.drop_column("scene_run_states", name)

    if inspector.has_table("scene_cards"):
        sc_cols = {col["name"] for col in inspector.get_columns("scene_cards")}
        if "constraint_intensity" in sc_cols:
            op.drop_column("scene_cards", "constraint_intensity")
