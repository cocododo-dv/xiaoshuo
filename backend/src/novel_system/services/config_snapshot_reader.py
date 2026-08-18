"""Read-only runtime configuration access.

Parsers and provider services depend on this small query boundary instead of
depending on the mutation-heavy ``system_config`` service that imports them.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from novel_system.db.models import SystemConfigSnapshot
from novel_system.db.session import SessionLocal
from novel_system.services.database_errors import is_database_busy_error


_TRANSIENT_DB_RETRY_DELAYS = (0.05, 0.15)


def read_with_transient_retry(reader, *, sleep: Callable[[float], None] = time.sleep):
    """Retry only SQLite busy errors and never turn a DB failure into absence."""

    for delay in (*_TRANSIENT_DB_RETRY_DELAYS, None):
        try:
            return reader()
        except SQLAlchemyError as exc:
            if not is_database_busy_error(exc) or delay is None:
                raise
            sleep(delay)
    raise AssertionError("unreachable")


def _active_snapshot(session, category: str) -> SystemConfigSnapshot | None:
    return session.execute(
        select(SystemConfigSnapshot)
        .where(SystemConfigSnapshot.category == category, SystemConfigSnapshot.active_flag == 1)
        .order_by(SystemConfigSnapshot.version.desc(), SystemConfigSnapshot.created_at.desc())
    ).scalars().first()


def load_active_config_payload(
    category: str,
    *,
    session_factory=SessionLocal,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    def _read():
        with session_factory() as session:
            snapshot = _active_snapshot(session, category)
            return None if snapshot is None else dict(snapshot.parsed_json or {})

    return read_with_transient_retry(_read, sleep=sleep)


def load_active_config_yaml(
    category: str,
    *,
    session_factory=SessionLocal,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    def _read():
        with session_factory() as session:
            snapshot = _active_snapshot(session, category)
            return snapshot.yaml_raw if snapshot is not None else None

    return read_with_transient_retry(_read, sleep=sleep)
