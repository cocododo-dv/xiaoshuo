from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    database_url: str
    vector_backend: str
    vector_store_dir: Path
    chroma_collection_prefix: str = "novel_system"
    idempotency_ttl_seconds: int = 90
    verify_lease_ttl_seconds: int = 180
    reindex_lease_ttl_seconds: int = 180


def get_settings() -> Settings:
    database_url = os.environ.get(
        "NOVEL_SYSTEM_DATABASE_URL",
        "sqlite:///./novel_system.db",
    )
    vector_backend = os.environ.get("NOVEL_SYSTEM_VECTOR_BACKEND", "chroma")
    vector_store_dir = Path(
        os.environ.get("NOVEL_SYSTEM_CHROMA_DIR", "./.vector_store")
    )
    chroma_collection_prefix = os.environ.get("NOVEL_SYSTEM_CHROMA_COLLECTION_PREFIX", "novel_system")
    vector_store_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        database_url=database_url,
        vector_backend=vector_backend,
        vector_store_dir=vector_store_dir,
        chroma_collection_prefix=chroma_collection_prefix,
    )
