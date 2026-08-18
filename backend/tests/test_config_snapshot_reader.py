from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from novel_system.services.config_snapshot_reader import read_with_transient_retry


def _busy_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("database is locked"))


def test_transient_busy_errors_retry_then_return_value() -> None:
    attempts = 0
    sleeps: list[float] = []

    def reader() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _busy_error()
        return "configured"

    assert read_with_transient_retry(reader, sleep=sleeps.append) == "configured"
    assert attempts == 3
    assert sleeps == [0.05, 0.15]


def test_exhausted_busy_error_is_raised_instead_of_becoming_none() -> None:
    sleeps: list[float] = []

    with pytest.raises(OperationalError):
        read_with_transient_retry(lambda: (_ for _ in ()).throw(_busy_error()), sleep=sleeps.append)

    assert sleeps == [0.05, 0.15]


def test_non_transient_sqlalchemy_error_is_not_retried_or_hidden() -> None:
    sleeps: list[float] = []

    with pytest.raises(SQLAlchemyError, match="broken schema"):
        read_with_transient_retry(
            lambda: (_ for _ in ()).throw(SQLAlchemyError("broken schema")),
            sleep=sleeps.append,
        )

    assert sleeps == []
