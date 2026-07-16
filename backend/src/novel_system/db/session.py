from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from novel_system.settings import get_settings

_ENGINE = None
_SESSION_FACTORY = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        settings = get_settings(include_runtime_config=False)
        is_sqlite = settings.database_url.startswith("sqlite")
        connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
        _ENGINE = create_engine(settings.database_url, connect_args=connect_args, future=True)
        if is_sqlite:
            _install_sqlite_pragmas(
                _ENGINE,
                enforce_foreign_keys=settings.sqlite_foreign_keys_enabled,
            )
    return _ENGINE


def _configure_sqlite_connection(
    dbapi_connection,
    *,
    enforce_foreign_keys: bool,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(
            "PRAGMA foreign_keys=ON"
            if enforce_foreign_keys
            else "PRAGMA foreign_keys=OFF"
        )
        cursor.execute("PRAGMA foreign_keys")
        row = cursor.fetchone()
        actual = int(row[0]) if row else -1
        expected = 1 if enforce_foreign_keys else 0
        if actual != expected:
            mode = "enabled" if enforce_foreign_keys else "disabled"
            raise RuntimeError(
                f"sqlite_foreign_keys_not_{mode}: expected={expected}, actual={actual}"
            )
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()


def _install_sqlite_pragmas(
    sqlalchemy_engine,
    *,
    enforce_foreign_keys: bool = True,
) -> None:
    @event.listens_for(sqlalchemy_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        _configure_sqlite_connection(
            dbapi_connection,
            enforce_foreign_keys=enforce_foreign_keys,
        )

    if enforce_foreign_keys:

        @event.listens_for(sqlalchemy_engine, "begin")
        def defer_sqlite_foreign_keys(sqlalchemy_connection) -> None:
            _configure_sqlite_transaction(sqlalchemy_connection)


def _configure_sqlite_transaction(sqlalchemy_connection) -> None:
    """Defer FK checks until commit for every SQLite transaction.

    The model layer intentionally has few ORM relationships, so SQLAlchemy
    cannot always topologically order a valid parent/child graph added in one
    unit of work.  SQLite resets ``defer_foreign_keys`` after each commit or
    rollback; the engine ``begin`` hook therefore must set and verify it for
    every transaction while keeping enforcement itself enabled.
    """

    foreign_keys = sqlalchemy_connection.exec_driver_sql(
        "PRAGMA foreign_keys"
    ).scalar_one()
    if int(foreign_keys) != 1:
        raise RuntimeError(
            f"sqlite_foreign_keys_not_enabled_at_transaction_begin: actual={foreign_keys}"
        )
    sqlalchemy_connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    deferred = sqlalchemy_connection.exec_driver_sql(
        "PRAGMA defer_foreign_keys"
    ).scalar_one()
    if int(deferred) != 1:
        raise RuntimeError(
            f"sqlite_defer_foreign_keys_not_enabled: expected=1, actual={deferred}"
        )


def session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return _SESSION_FACTORY


def SessionLocal() -> Session:
    return session_factory()()


def reset_engine() -> None:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
