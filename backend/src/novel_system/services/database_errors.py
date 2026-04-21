from __future__ import annotations

from sqlalchemy.exc import OperationalError


SQLITE_BUSY_MARKERS = (
    "database is locked",
    "database table is locked",
    "database is busy",
    "sqlite_busy",
    "sqlite_locked",
)


def is_database_busy_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    text = " ".join(str(part) for part in (exc, getattr(exc, "orig", None))).lower()
    return any(marker in text for marker in SQLITE_BUSY_MARKERS)
