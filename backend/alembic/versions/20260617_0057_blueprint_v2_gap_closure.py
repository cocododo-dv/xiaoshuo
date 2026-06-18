"""blueprint v2 gap closure: event theme_tags/obligations + foreshadow project_id

Add theme_tags and obligation_ids to NarrativeEvent for §2 (theme-aware queries
and forward-pointing causal obligations).
Add project_id to ForeshadowTracker for §5 (cross-chapter lifecycle management).

Revision ID: 20260617_0057
Revises: 20260617_0056
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "20260617_0057"
down_revision = "20260617_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- NarrativeEvent: theme_tags + obligation_ids (Blueprint §2) ---
    if inspector.has_table("narrative_events"):
        ne_cols = {col["name"] for col in inspector.get_columns("narrative_events")}
        if "theme_tags" not in ne_cols:
            op.add_column(
                "narrative_events",
                sa.Column("theme_tags", sa.JSON(), nullable=True, server_default="[]"),
            )
        if "obligation_ids" not in ne_cols:
            op.add_column(
                "narrative_events",
                sa.Column("obligation_ids", sa.JSON(), nullable=True, server_default="[]"),
            )

    # --- ForeshadowTracker: project_id for cross-chapter queries (Blueprint §5) ---
    if inspector.has_table("foreshadow_tracker"):
        ft_cols = {col["name"] for col in inspector.get_columns("foreshadow_tracker")}
        if "project_id" not in ft_cols:
            op.add_column(
                "foreshadow_tracker",
                sa.Column("project_id", sa.String(), nullable=True),
            )
            # Backfill project_id from chapter → scene → project chain where possible
            try:
                op.execute(
                    """
                    UPDATE foreshadow_tracker
                    SET project_id = (
                        SELECT sc.project_id
                        FROM scene_cards sc
                        WHERE sc.scene_id = foreshadow_tracker.scene_id
                        LIMIT 1
                    )
                    WHERE project_id IS NULL AND scene_id IS NOT NULL
                    """
                )
            except Exception:
                pass  # best-effort backfill; new rows will have project_id set
            op.create_index(
                "ix_foreshadow_tracker_project_id",
                "foreshadow_tracker",
                ["project_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("foreshadow_tracker"):
        try:
            op.drop_index("ix_foreshadow_tracker_project_id", "foreshadow_tracker")
        except Exception:
            pass
        op.drop_column("foreshadow_tracker", "project_id")
    if inspector.has_table("narrative_events"):
        op.drop_column("narrative_events", "obligation_ids")
        op.drop_column("narrative_events", "theme_tags")
