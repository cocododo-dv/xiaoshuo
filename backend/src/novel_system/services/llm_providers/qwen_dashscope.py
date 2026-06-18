"""通义千问 — 阿里云百炼 DashScope OpenAI 兼容模式。

文档锚点(2026-06 核验):
- base: https://dashscope.aliyuncs.com/compatible-mode/v1,Bearer 鉴权
- JSON Mode 与思考模式互斥("思考模式 Qwen 模型不能使用 JSON Mode")
- 思考开关为顶层 ``enable_thinking`` 布尔(原生 HTTP 置于请求体顶层)
"""

from __future__ import annotations

from typing import Any, ClassVar

from novel_system.services.llm_providers.base import LLMRequest, ProviderRuntimeConfig
from novel_system.services.llm_providers.openai_chat_family import OpenAIChatFamilyAdapter


class QwenDashscopeAdapter(OpenAIChatFamilyAdapter):
    provider_type: ClassVar[str] = "qwen_dashscope"
    label_zh: ClassVar[str] = "通义千问（阿里云百炼）"
    default_base_url: ClassVar[str] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    category: ClassVar[str] = "cn"
    docs_url: ClassVar[str | None] = "https://help.aliyun.com/zh/model-studio/"

    def chat_extra_payload(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        # JSON Mode 与思考互斥;qwen3.5+ 默认开思考,所以 JSON 输出时必须显式关闭。
        if request.response_format == "json_object" or request.reasoning_level in {"off", "low"}:
            native_reasoning = {"enable_thinking": False}
        else:
            native_reasoning = {"enable_thinking": True}
        return dict(native_reasoning), native_reasoning
