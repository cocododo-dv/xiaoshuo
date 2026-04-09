from __future__ import annotations

import sys
from pathlib import Path

import pytest

from novel_system.services.errors import DomainError
from novel_system.services.vector_store import _DeterministicEmbeddingFunction, get_vector_store
from novel_system.settings import get_settings


def test_non_integration_tests_default_to_memory_backend() -> None:
    assert get_settings().vector_backend == "memory"


def test_native_windows_chroma_backend_fails_fast(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("native Windows guard only applies on Windows")

    with pytest.raises(DomainError) as exc_info:
        get_vector_store(backend="chroma", persist_directory=tmp_path / "chroma")

    assert exc_info.value.code == "CHROMA_RUNTIME_UNSUPPORTED"
    assert "WSL" in exc_info.value.message


def test_deterministic_embedding_function_supports_query_embedding() -> None:
    embedding_function = _DeterministicEmbeddingFunction()

    doc_embedding = embedding_function(["quiet rain over rooftops"])
    query_embedding = embedding_function.embed_query(["quiet rain over rooftops"])

    assert query_embedding == doc_embedding
