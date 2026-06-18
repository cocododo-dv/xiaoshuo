from __future__ import annotations

from typing import Any, ClassVar

from novel_system.services.llm_providers.base import LLMRequest, ProviderRuntimeConfig
from novel_system.services.llm_providers.openai_chat_family import OpenAIChatFamilyAdapter


class DeepseekAdapter(OpenAIChatFamilyAdapter):
    provider_type: ClassVar[str] = "deepseek"
    label_zh: ClassVar[str] = "DeepSeek"
    default_base_url: ClassVar[str] = "https://api.deepseek.com/v1"
    appends_v1_to_bare_host: ClassVar[bool] = True
    category: ClassVar[str] = "cn"
    docs_url: ClassVar[str | None] = "https://api-docs.deepseek.com"

    def chat_extra_payload(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if request.reasoning_level in {"medium", "high"}:
            native_reasoning = {"type": "enabled"}
            return {"thinking": native_reasoning}, native_reasoning
        return {}, None
