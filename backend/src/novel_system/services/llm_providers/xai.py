"""xAI Grok — OpenAI 兼容 Chat Completions。

文档锚点(2026-06 核验,docs.x.ai):
- base: https://api.x.ai/v1,Bearer;GET /v1/models 可用
- response_format 支持 json_object / json_schema
- max_tokens 已标记弃用 → max_completion_tokens
- ``reasoning_effort``: "none"|"low"|"medium"|"high"(grok-4.3;旧 id 均为
  其别名),与本系统 reasoning_level 同名映射,off→none。
"""

from __future__ import annotations

from typing import Any, ClassVar

from novel_system.services.llm_providers.base import LLMRequest, ProviderRuntimeConfig
from novel_system.services.llm_providers.openai_chat_family import OpenAIChatFamilyAdapter


class XaiAdapter(OpenAIChatFamilyAdapter):
    provider_type: ClassVar[str] = "xai"
    label_zh: ClassVar[str] = "Grok / xAI"
    default_base_url: ClassVar[str] = "https://api.x.ai/v1"
    appends_v1_to_bare_host: ClassVar[bool] = True
    docs_url: ClassVar[str | None] = "https://docs.x.ai"
    max_tokens_param: ClassVar[str] = "max_completion_tokens"

    def chat_extra_payload(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        effort = "none" if request.reasoning_level == "off" else request.reasoning_level
        native_reasoning = {"effort": effort}
        return {"reasoning_effort": effort}, native_reasoning
