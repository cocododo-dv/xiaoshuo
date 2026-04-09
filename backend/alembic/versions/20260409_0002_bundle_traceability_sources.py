"""bundle traceability sources

Revision ID: 20260409_0002
Revises: 20260408_0001
Create Date: 2026-04-09
"""

from __future__ import annotations

from alembic import op
from novel_system.db.base import Base
from novel_system.db import models  # noqa: F401

revision = "20260409_0002"
down_revision = "20260408_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["voice_profiles"],
            Base.metadata.tables["relation_profiles"],
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["relation_profiles"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["voice_profiles"].drop(bind=bind, checkfirst=True)
