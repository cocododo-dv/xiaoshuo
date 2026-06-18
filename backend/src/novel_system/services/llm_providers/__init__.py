"""LLM provider adapter registry.

Every supported provider type is an adapter registered here; ``llm_client``
and ``system_config`` derive their provider knowledge (dispatch, default base
URLs, catalog labels, probing) from this registry instead of hardcoding it.
"""

from __future__ import annotations

from novel_system.services.llm_providers.base import (
    AdapterHTTPRequest,
    CompletionProbeRequest,
    LLMClientError,
    LLMConfigurationError,
    LLMHTTPError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    ModelListRequest,
    ProviderAdapter,
    ProviderRuntimeConfig,
    SUPPORTED_API_MODES,
    SUPPORTED_CREDENTIAL_MODES,
    SUPPORTED_REASONING_LEVELS,
    SUPPORTED_RESPONSE_FORMATS,
)
from novel_system.services.llm_providers.registry import (
    adapter_registry,
    get_adapter,
    register,
    supported_provider_types,
)
from novel_system.services.llm_providers.anthropic import AnthropicAdapter
from novel_system.services.llm_providers.deepseek import DeepseekAdapter
from novel_system.services.llm_providers.doubao_ark import DoubaoArkAdapter
from novel_system.services.llm_providers.gemini import GeminiAdapter
from novel_system.services.llm_providers.minimax import MinimaxAdapter
from novel_system.services.llm_providers.moonshot import MoonshotAdapter
from novel_system.services.llm_providers.ollama import OllamaAdapter
from novel_system.services.llm_providers.openai import OpenAIAdapter, OpenAICompatibleAdapter
from novel_system.services.llm_providers.qwen_dashscope import QwenDashscopeAdapter
from novel_system.services.llm_providers.xai import XaiAdapter
from novel_system.services.llm_providers.zhipu_glm import ZhipuGLMAdapter


# Registration order doubles as the provider catalog display order.
register(OpenAICompatibleAdapter())
register(OpenAIAdapter())
register(AnthropicAdapter())
register(DeepseekAdapter())
register(ZhipuGLMAdapter())
register(GeminiAdapter())
register(QwenDashscopeAdapter())
register(MoonshotAdapter())
register(MinimaxAdapter())
register(DoubaoArkAdapter())
register(XaiAdapter())
register(OllamaAdapter())

# Presets import must come after adapter registration (resolvability assert).
from novel_system.services.llm_providers.presets import (  # noqa: E402
    ProviderPreset,
    get_provider_preset,
    provider_preset_payloads,
    provider_presets,
)


def default_provider_base_urls() -> dict[str, str]:
    return {provider_type: adapter.default_base_url for provider_type, adapter in adapter_registry().items()}


def provider_catalog() -> dict[str, dict[str, object]]:
    return {provider_type: adapter.catalog_entry() for provider_type, adapter in adapter_registry().items()}


__all__ = [
    "AdapterHTTPRequest",
    "AnthropicAdapter",
    "CompletionProbeRequest",
    "DeepseekAdapter",
    "GeminiAdapter",
    "LLMClientError",
    "LLMConfigurationError",
    "LLMHTTPError",
    "LLMRateLimitError",
    "LLMRequest",
    "LLMResponse",
    "LLMResponseError",
    "LLMTimeoutError",
    "ModelListRequest",
    "OpenAIAdapter",
    "OpenAICompatibleAdapter",
    "ProviderAdapter",
    "ProviderPreset",
    "ProviderRuntimeConfig",
    "SUPPORTED_API_MODES",
    "SUPPORTED_CREDENTIAL_MODES",
    "SUPPORTED_REASONING_LEVELS",
    "SUPPORTED_RESPONSE_FORMATS",
    "ZhipuGLMAdapter",
    "adapter_registry",
    "default_provider_base_urls",
    "get_adapter",
    "get_provider_preset",
    "provider_catalog",
    "provider_preset_payloads",
    "provider_presets",
    "register",
    "supported_provider_types",
]
