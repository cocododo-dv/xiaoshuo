from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from novel_system.api.app import create_app
from novel_system.db.base import Base
from novel_system.db.session import SessionLocal, engine


@pytest.fixture(scope="session", autouse=True)
def _style_reference_legacy_backup_stub() -> Generator[Path, None, None]:
    """所有跑 alembic upgrade(含 subprocess)的测试都会触发 0036 的 backup glob 断言。

    本 fixture 创建一个会话级临时仓库根,内含 placeholder backup 文件,并通过
    `STYLE_REFERENCE_REPO_ROOT` 让 0036 把 glob 指向它。session 结束自动清理。
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="style_reference_test_repo_"))
    backup_dir = tmp_root / "backups"
    backup_dir.mkdir(parents=True)
    (backup_dir / "style_reference_legacy_test_session.json").write_text(
        '{"row_count": 0, "profiles": [], "source": "pytest-session-stub"}',
        encoding="utf-8",
    )
    previous = os.environ.get("STYLE_REFERENCE_REPO_ROOT")
    os.environ["STYLE_REFERENCE_REPO_ROOT"] = str(tmp_root)
    try:
        yield tmp_root
    finally:
        if previous is None:
            os.environ.pop("STYLE_REFERENCE_REPO_ROOT", None)
        else:
            os.environ["STYLE_REFERENCE_REPO_ROOT"] = previous
        import shutil

        shutil.rmtree(tmp_root, ignore_errors=True)


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
