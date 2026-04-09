from __future__ import annotations

import json
from pathlib import Path

from novel_system.services.vector_store import get_vector_store
from novel_system.settings import get_settings


def run_chroma_smoke(persist_directory: Path | None = None) -> dict:
    settings = get_settings()
    store = get_vector_store(
        backend="chroma",
        persist_directory=persist_directory or settings.vector_store_dir,
    )
    collection_name = "novel_system_smoke_candidate_v1"
    store.write_collection(
        collection_name,
        [
            {"id": "doc-1", "text": "moonlit rooftops and quiet rain", "scope": "global"},
            {"id": "doc-2", "text": "battle drums under a red sky", "scope": "global"},
        ],
    )
    results = store.query(collection_name, "quiet rain over rooftops", top_k=1)
    return {
        "backend": "chroma",
        "collection_name": collection_name,
        "collection_exists": store.collection_exists(collection_name),
        "query_ids": [item["id"] for item in results],
    }


def main() -> None:
    print(json.dumps(run_chroma_smoke(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
