"""document explicit reset boundary for snowflake workspace

Revision ID: 20260428_0028
Revises: 20260427_0027
Create Date: 2026-04-28
"""

from __future__ import annotations

revision = "20260428_0028"
down_revision = "20260427_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The snowflake workbench reset is intentionally destructive and must stay
    # behind `python -m novel_system.tools.reset_author_state --execute --yes`.
    # Migrations only linearize the schema baseline and never clear author data.
    pass


def downgrade() -> None:
    pass
