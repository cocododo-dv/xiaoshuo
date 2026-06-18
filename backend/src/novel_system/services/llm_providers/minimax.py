"""MiniMax — OpenAI 兼容 Chat Completions(api.minimaxi.com)。

文档锚点(2026-06 核验,platform.minimaxi.com / platform.minimax.io):
- base: https://api.minimaxi.com/v1(国内)/ https://api.minimax.io/v1(海外),Bearer
- GET /v1/models 可用
- 兼容端点参数表**没有 response_format** —— JSON 输出依赖提示词约束 +
  客户端 JSON 提取兜底,因此 supports_json_response_format=False
- max_tokens 已弃用,使用 max_completion_tokens
- 思考为顶层 ``thinking: {"type": "disabled"|"adaptive"}``(M3 默认 adaptive)
"""

from __future__ import annotations

from typing import Any, ClassVar

from novel_system.services.llm_providers.base import LLMRequest, ProviderRuntimeConfig
from novel_system.services.llm_providers.openai_chat_family import OpenAIChatFamilyAdapter


class MinimaxAdapter(OpenAIChatFamilyAdapter):
    provider_type: ClassVar[str] = "minimax"
    label_zh: ClassVar[str] = "MiniMax"
    default_base_url: ClassVar[str] = "https://api.minimaxi.com/v1"
    appends_v1_to_bare_host: ClassVar[bool] = True
    category: ClassVar[str] = "cn"
    docs_url: ClassVar[str | None] = "https://platform.minimaxi.com/docs"
    supports_json_response_format: ClassVar[bool] = False
    max_tokens_param: ClassVar[str] = "max_completion_tokens"

    def chat_extra_payload(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        native_reasoning = {"type": "adaptive" if request.reasoning_level in {"medium", "high"} else "disabled"}
        return {"thinking": native_reasoning}, native_reasoning
