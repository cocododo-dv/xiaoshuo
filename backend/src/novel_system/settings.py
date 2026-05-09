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
    admin_token: str | None = None
    config_secret: str | None = None
    auto_create_tables: bool = True
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8081",
        "http://localhost:8081",
    )
    cors_allow_credentials: bool = True
    expose_error_detail: bool = False


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


def _get_list_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    items = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    return items or default


def get_settings(*, include_runtime_config: bool = True) -> Settings:
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
    admin_token = os.environ.get("NOVEL_SYSTEM_ADMIN_TOKEN")
    config_secret = os.environ.get("NOVEL_SYSTEM_CONFIG_SECRET")
    auto_create_tables = _get_bool_env("NOVEL_SYSTEM_AUTO_CREATE_TABLES", True)
    cors_origins = _get_list_env(
        "NOVEL_SYSTEM_CORS_ORIGINS",
        (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8081",
            "http://localhost:8081",
        ),
    )
    cors_allow_credentials = _get_bool_env("NOVEL_SYSTEM_CORS_ALLOW_CREDENTIALS", True)
    expose_error_detail = _get_bool_env("NOVEL_SYSTEM_EXPOSE_ERROR_DETAIL", False)
    vector_store_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        database_url=database_url,
        vector_backend=vector_backend,
        vector_store_dir=vector_store_dir,
        chroma_collection_prefix=chroma_collection_prefix,
        llm_provider=llm_provider,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_timeout_seconds=llm_timeout_seconds,
        llm_enabled=llm_enabled,
        admin_token=admin_token,
        config_secret=config_secret,
        auto_create_tables=auto_create_tables,
        cors_origins=cors_origins,
        cors_allow_credentials=cors_allow_credentials,
        expose_error_detail=expose_error_detail,
    )
    if not include_runtime_config:
        return settings

    from novel_system.services.system_config import apply_active_api_config

    return apply_active_api_config(settings)
