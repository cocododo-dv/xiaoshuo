from __future__ import annotations

from novel_system.services.llm_providers.base import LLMConfigurationError, ProviderAdapter


_REGISTRY: dict[str, ProviderAdapter] = {}


def register(adapter: ProviderAdapter) -> ProviderAdapter:
    provider_type = adapter.provider_type
    if provider_type in _REGISTRY:
        raise ValueError(f"llm provider adapter {provider_type} is already registered")
    _REGISTRY[provider_type] = adapter
    return adapter


def get_adapter(provider_type: str) -> ProviderAdapter:
    adapter = _REGISTRY.get(provider_type)
    if adapter is None:
        raise LLMConfigurationError(
            "LLM_PROVIDER_UNSUPPORTED",
            f"unsupported llm provider {provider_type}",
        )
    return adapter


def adapter_registry() -> dict[str, ProviderAdapter]:
    return dict(_REGISTRY)


def supported_provider_types() -> frozenset[str]:
    return frozenset(_REGISTRY)
