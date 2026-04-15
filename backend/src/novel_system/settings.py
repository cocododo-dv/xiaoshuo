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
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_enabled: bool = False


def _get_bool_env(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid number") from exc


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
    llm_provider = os.environ.get("NOVEL_SYSTEM_LLM_PROVIDER", "openai_compatible")
    llm_base_url = os.environ.get("NOVEL_SYSTEM_LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key = os.environ.get("NOVEL_SYSTEM_LLM_API_KEY")
    llm_timeout_seconds = _get_float_env("NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS", 30.0)
    llm_enabled = _get_bool_env("NOVEL_SYSTEM_LLM_ENABLED", False)
    vector_store_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        database_url=database_url,
        vector_backend=vector_backend,
        vector_store_dir=vector_store_dir,
        chroma_collection_prefix=chroma_collection_prefix,
        llm_provider=llm_provider,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_timeout_seconds=llm_timeout_seconds,
        llm_enabled=llm_enabled,
    )
