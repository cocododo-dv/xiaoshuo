from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from novel_system.api.app import create_app
from novel_system.db.base import Base
from novel_system.db.session import SessionLocal, engine


@pytest.fixture(autouse=True)
def isolated_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    is_chroma_integration = request.node.get_closest_marker("chroma_integration") is not None
    if is_chroma_integration and sys.platform == "win32":
        pytest.skip("Chroma integration tests require Linux/WSL; native Windows Chroma is blocked")

    vector_backend = "chroma" if is_chroma_integration else "memory"
    monkeypatch.setenv("NOVEL_SYSTEM_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("NOVEL_SYSTEM_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("NOVEL_SYSTEM_VECTOR_BACKEND", vector_backend)
    from novel_system.db.session import reset_engine

    reset_engine()
    Base.metadata.drop_all(bind=engine())
    Base.metadata.create_all(bind=engine())
    yield
    Base.metadata.drop_all(bind=engine())


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
