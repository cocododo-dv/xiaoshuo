from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from novel_system.db import session as db_session
from novel_system.settings import get_settings


def test_runtime_engine_enables_sqlite_foreign_keys_by_default() -> None:
    with db_session.engine().connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [(True, 1), (False, 0)],
)
def test_sqlite_connection_policy_is_explicit_and_verified(enabled, expected) -> None:
    test_engine = create_engine("sqlite:///:memory:", future=True)
    db_session._install_sqlite_pragmas(
        test_engine,
        enforce_foreign_keys=enabled,
    )
    try:
        with test_engine.connect() as connection:
            assert (
                connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
                == expected
            )
    finally:
        test_engine.dispose()


def test_foreign_key_enablement_fails_closed_when_sqlite_does_not_accept_it() -> None:
    class RefusingCursor:
        def execute(self, _statement):
            return self

        @staticmethod
        def fetchone():
            return (0,)

        @staticmethod
        def close() -> None:
            return None

    class RefusingConnection:
        @staticmethod
        def cursor():
            return RefusingCursor()

    with pytest.raises(RuntimeError, match="sqlite_foreign_keys_not_enabled"):
        db_session._configure_sqlite_connection(
            RefusingConnection(),
            enforce_foreign_keys=True,
        )


def test_runtime_foreign_key_policy_blocks_orphan_inserts() -> None:
    raw_connection = sqlite3.connect(":memory:")
    try:
        db_session._configure_sqlite_connection(
            raw_connection,
            enforce_foreign_keys=True,
        )
        raw_connection.executescript(
            """
            CREATE TABLE parent_rows (parent_id TEXT PRIMARY KEY);
            CREATE TABLE child_rows (
                child_id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES parent_rows(parent_id)
            );
            """
        )
        with pytest.raises(
            sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"
        ):
            raw_connection.execute(
                "INSERT INTO child_rows VALUES ('child', 'missing-parent')"
            )
    finally:
        raw_connection.close()


def _make_deferred_fk_engine():
    test_engine = create_engine("sqlite:///:memory:", future=True)
    db_session._install_sqlite_pragmas(
        test_engine,
        enforce_foreign_keys=True,
    )
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE parent_rows (parent_id TEXT PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE child_rows (
                child_id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES parent_rows(parent_id)
            )
            """
        )
    return test_engine


def test_same_transaction_child_before_parent_is_validated_at_commit() -> None:
    test_engine = _make_deferred_fk_engine()
    try:
        with test_engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert (
                connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one()
                == 1
            )
            connection.exec_driver_sql(
                "INSERT INTO child_rows VALUES ('child', 'parent')"
            )
            connection.exec_driver_sql("INSERT INTO parent_rows VALUES ('parent')")
        with test_engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM child_rows"
                ).scalar_one()
                == 1
            )
    finally:
        test_engine.dispose()


def test_missing_parent_still_fails_when_deferred_transaction_commits() -> None:
    test_engine = _make_deferred_fk_engine()
    try:
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            with test_engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO child_rows VALUES ('orphan', 'missing-parent')"
                )
    finally:
        test_engine.dispose()


def test_deferred_fk_is_reenabled_after_commit_and_rollback() -> None:
    test_engine = _make_deferred_fk_engine()
    try:
        with test_engine.connect() as connection:
            first = connection.begin()
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert (
                connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one()
                == 1
            )
            connection.exec_driver_sql("INSERT INTO parent_rows VALUES ('committed')")
            first.commit()

            second = connection.begin()
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert (
                connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one()
                == 1
            )
            connection.exec_driver_sql("INSERT INTO parent_rows VALUES ('rolled-back')")
            second.rollback()

            third = connection.begin()
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert (
                connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one()
                == 1
            )
            connection.exec_driver_sql(
                "INSERT INTO child_rows VALUES ('third-child', 'third-parent')"
            )
            connection.exec_driver_sql(
                "INSERT INTO parent_rows VALUES ('third-parent')"
            )
            third.commit()
    finally:
        test_engine.dispose()


def test_emergency_switch_defaults_on_and_requires_a_valid_boolean(
    monkeypatch,
) -> None:
    monkeypatch.delenv("NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED", raising=False)
    assert (
        get_settings(include_runtime_config=False).sqlite_foreign_keys_enabled is True
    )

    monkeypatch.setenv("NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED", "off")
    assert (
        get_settings(include_runtime_config=False).sqlite_foreign_keys_enabled is False
    )

    monkeypatch.setenv("NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED", "typo")
    with pytest.raises(ValueError, match="must be a boolean"):
        get_settings(include_runtime_config=False)
