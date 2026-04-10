"""add interop artifacts table

Revision ID: 20260411_0004
Revises: 20260410_0003
Create Date: 2026-04-11
"""

from __future__ import annotations

from alembic import op

from novel_system.db import models  # noqa: F401
from novel_system.db.base import Base

revision = "20260411_0004"
down_revision = "20260410_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["interop_artifacts"]])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["interop_artifacts"].drop(bind=bind, checkfirst=True)
