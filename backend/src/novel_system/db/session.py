from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from novel_system.settings import get_settings

_ENGINE = None
_SESSION_FACTORY = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        settings = get_settings(include_runtime_config=False)
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _ENGINE = create_engine(settings.database_url, connect_args=connect_args, future=True)
    return _ENGINE


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
