from __future__ import annotations

from novel_system.settings import get_settings


def llm_generation_mode() -> str:
    settings = get_settings()
    if not settings.llm_enabled:
        return "offline_placeholder"
    if settings.llm_api_key:
        return "live"

    from novel_system.services.system_config import load_llm_provider_runtime_configs

    provider_configs = load_llm_provider_runtime_configs()
    for provider_config in provider_configs.values():
        if not provider_config.enabled:
            continue
        if provider_config.credential_mode == "none":
            return "live"
        if provider_config.api_key or provider_config.access_token:
            return "live"
    return "offline_placeholder"
