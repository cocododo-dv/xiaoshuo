"""Environment-only core runtime values shared below the service layer."""

from __future__ import annotations

import os
from dataclasses import dataclass

from novel_system.runtime_defaults import DEFAULT_LLM_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class CoreRuntime:
    llm_provider: str
    llm_base_url: str
    llm_api_key: str | None
    llm_timeout_seconds: float
    llm_enabled: bool
    admin_token: str | None
    config_secret: str | None


def load_core_runtime() -> CoreRuntime:
    return CoreRuntime(
        llm_provider=os.environ.get("NOVEL_SYSTEM_LLM_PROVIDER", "openai_compatible"),
        llm_base_url=os.environ.get("NOVEL_SYSTEM_LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_api_key=os.environ.get("NOVEL_SYSTEM_LLM_API_KEY"),
        llm_timeout_seconds=_non_negative_float(
            "NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS",
            DEFAULT_LLM_TIMEOUT_SECONDS,
        ),
        llm_enabled=_bool_env("NOVEL_SYSTEM_LLM_ENABLED", False),
        admin_token=os.environ.get("NOVEL_SYSTEM_ADMIN_TOKEN"),
        config_secret=os.environ.get("NOVEL_SYSTEM_CONFIG_SECRET"),
    )


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _non_negative_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid number") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value
