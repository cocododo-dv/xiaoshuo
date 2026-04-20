from __future__ import annotations

from novel_system.settings import get_settings


def llm_generation_mode() -> str:
    settings = get_settings()
    return "live" if settings.llm_enabled and bool(settings.llm_api_key) else "offline_placeholder"
