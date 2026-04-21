from __future__ import annotations

from sqlalchemy.exc import OperationalError

from novel_system.services.database_errors import is_database_busy_error


def test_database_busy_error_detects_sqlite_lock_messages() -> None:
    exc = OperationalError("SELECT 1", {}, Exception("database is locked"))

    assert is_database_busy_error(exc) is True


def test_database_busy_error_ignores_other_operational_errors() -> None:
    exc = OperationalError("SELECT 1", {}, Exception("no such table: missing"))

    assert is_database_busy_error(exc) is False
