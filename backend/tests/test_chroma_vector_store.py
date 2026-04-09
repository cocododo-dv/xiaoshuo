from __future__ import annotations

from pathlib import Path

import pytest

from novel_system.services.vector_store import (
    ChromaVectorStore,
    InMemoryVectorStore,
    get_vector_store,
)

pytestmark = pytest.mark.chroma_integration


def test_chroma_vector_store_persists_and_queries_documents(tmp_path: Path) -> None:
    store = ChromaVectorStore(tmp_path / "chroma")
    collection_name = "style_observation_global_global_candidate_v1"
    documents = [
        {"id": "doc-1", "text": "moonlit rooftops and quiet rain", "scope": "global"},
        {"id": "doc-2", "text": "battle drums under a red sky", "scope": "global"},
    ]

    store.write_collection(collection_name, documents)

    assert store.collection_exists(collection_name) is True
    assert {item["id"] for item in store.load_collection(collection_name)} == {"doc-1", "doc-2"}

    results = store.query(collection_name, "quiet rain over rooftops", top_k=1)

    assert [item["id"] for item in results] == ["doc-1"]


def test_get_vector_store_returns_in_memory_backend_for_tests(tmp_path: Path) -> None:
    store = get_vector_store(backend="memory", persist_directory=tmp_path / "ignored")

    assert isinstance(store, InMemoryVectorStore)
