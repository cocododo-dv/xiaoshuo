"""Provider preset catalog for the frontend "添加模型服务" picker.

A preset is a pre-filled provider configuration: pick one, get the right
``provider_type`` / ``base_url`` / ``api_mode`` and a starter model list.
Third-party relays (OpenRouter, SiliconFlow, OneAPI, …) ride the
``openai_compatible`` adapter with ``is_relay=True``.

Every ``provider_type`` referenced here must exist in the adapter registry —
asserted at import time so a missing adapter fails fast in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_system.services.llm_providers.registry import adapter_registry


@dataclass(slots=True, frozen=True)
class ProviderPreset:
    preset_id: str
    label_zh: str
    provider_type: str
    default_base_url: str
    common_models: tuple[str, ...] = ()
    default_api_mode: str = "chat"
    credential_modes: tuple[str, ...] = ("api_key",)
    docs_url: str | None = None
    is_relay: bool = False
    category: str = "international"  # cn | international | relay | local | custom
    notes_zh: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "label_zh": self.label_zh,
            "provider_type": self.provider_type,
            "default_base_url": self.default_base_url,
            "common_models": list(self.common_models),
            "default_api_mode": self.default_api_mode,
            "credential_modes": list(self.credential_modes),
            "docs_url": self.docs_url,
            "is_relay": self.is_relay,
            "category": self.category,
            "notes_zh": self.notes_zh,
            "provider_options": dict(self.provider_options),
        }


_PRESETS: tuple[ProviderPreset, ...] = (
    # ---- 国际厂商 -------------------------------------------------------
    ProviderPreset(
        preset_id="openai",
        label_zh="OpenAI",
        provider_type="openai",
        default_base_url="https://api.openai.com/v1",
        common_models=("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-4.1", "gpt-4o"),
        default_api_mode="responses",
        docs_url="https://platform.openai.com/docs/api-reference",
        category="international",
    ),
    ProviderPreset(
        preset_id="anthropic",
        label_zh="Claude / Anthropic",
        provider_type="anthropic",
        default_base_url="https://api.anthropic.com/v1",
        common_models=(
            "claude-sonnet-4-6",
            "claude-opus-4-8",
            "claude-haiku-4-5-20251001",
        ),
        docs_url="https://docs.anthropic.com",
        category="international",
    ),
    ProviderPreset(
        preset_id="gemini",
        label_zh="Gemini / Google",
        provider_type="gemini",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        common_models=("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"),
        docs_url="https://ai.google.dev/gemini-api/docs",
        category="international",
    ),
    ProviderPreset(
        preset_id="xai",
        label_zh="Grok / xAI",
        provider_type="xai",
        default_base_url="https://api.x.ai/v1",
        common_models=("grok-4.3",),
        docs_url="https://docs.x.ai",
        category="international",
        notes_zh="旧 id(grok-4 / grok-4-fast 等)均为 grok-4.3 的别名;建议「拉取模型」取现役列表。",
    ),
    # ---- 国内厂商 -------------------------------------------------------
    ProviderPreset(
        preset_id="deepseek",
        label_zh="DeepSeek",
        provider_type="deepseek",
        default_base_url="https://api.deepseek.com/v1",
        common_models=("deepseek-chat", "deepseek-reasoner"),
        docs_url="https://api-docs.deepseek.com",
        category="cn",
    ),
    ProviderPreset(
        preset_id="zhipu_glm",
        label_zh="智谱 GLM",
        provider_type="zhipu_glm",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        common_models=("glm-4.6", "glm-4.5", "glm-4.5-air"),
        docs_url="https://docs.bigmodel.cn",
        category="cn",
    ),
    ProviderPreset(
        preset_id="qwen_dashscope",
        label_zh="通义千问（阿里云百炼）",
        provider_type="qwen_dashscope",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        common_models=("qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash", "qwen-plus", "qwen-turbo"),
        docs_url="https://help.aliyun.com/zh/model-studio/",
        category="cn",
        notes_zh="百炼 OpenAI 兼容模式;JSON 输出与思考模式互斥,系统已自动处理。",
    ),
    ProviderPreset(
        preset_id="moonshot",
        label_zh="Kimi / Moonshot",
        provider_type="moonshot",
        default_base_url="https://api.moonshot.cn/v1",
        common_models=("kimi-k2.6", "kimi-k2.5", "moonshot-v1-128k", "moonshot-v1-32k"),
        docs_url="https://platform.kimi.com/docs",
        category="cn",
        notes_zh="海外账号用 https://api.moonshot.ai/v1;kimi-k2.x 温度由服务端固定。",
    ),
    ProviderPreset(
        preset_id="minimax",
        label_zh="MiniMax",
        provider_type="minimax",
        default_base_url="https://api.minimaxi.com/v1",
        common_models=("MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5"),
        docs_url="https://platform.minimaxi.com/docs",
        category="cn",
        notes_zh="海外账号用 https://api.minimax.io/v1;该端点不支持 JSON 模式参数,JSON 输出由系统兜底解析。",
    ),
    ProviderPreset(
        preset_id="doubao_ark",
        label_zh="豆包（火山方舟）",
        provider_type="doubao_ark",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        common_models=(
            "doubao-seed-2-0-pro-260215",
            "doubao-seed-2-0-lite-260428",
            "doubao-seed-1-8-251228",
            "doubao-seed-1-6-250615",
        ),
        docs_url="https://www.volcengine.com/docs/82379/1494384",
        category="cn",
        notes_zh="model 可填 Model ID 或接入点 ep-xxx;方舟不提供模型列表接口,从预设选择或手填。",
    ),
    # ---- 第三方中转(OpenAI 兼容) --------------------------------------
    ProviderPreset(
        preset_id="openrouter",
        label_zh="OpenRouter(聚合中转)",
        provider_type="openai_compatible",
        default_base_url="https://openrouter.ai/api/v1",
        default_api_mode="chat",
        docs_url="https://openrouter.ai/docs",
        is_relay=True,
        category="relay",
        notes_zh="聚合多家模型;模型名形如 anthropic/claude-sonnet-4.6,保存前先「拉取模型」。",
    ),
    ProviderPreset(
        preset_id="siliconflow",
        label_zh="SiliconFlow 硅基流动",
        provider_type="openai_compatible",
        default_base_url="https://api.siliconflow.cn/v1",
        default_api_mode="chat",
        docs_url="https://docs.siliconflow.cn",
        is_relay=True,
        category="relay",
        notes_zh="国内聚合中转;模型名形如 deepseek-ai/DeepSeek-V3。",
    ),
    ProviderPreset(
        preset_id="oneapi",
        label_zh="OneAPI / New API 自建中转",
        provider_type="openai_compatible",
        default_base_url="",
        default_api_mode="chat",
        is_relay=True,
        category="relay",
        notes_zh="填入你的中转站地址(通常以 /v1 结尾)与令牌。",
    ),
    # ---- 本地 / 自定义 --------------------------------------------------
    ProviderPreset(
        preset_id="ollama",
        label_zh="Ollama 本地",
        provider_type="ollama",
        default_base_url="http://127.0.0.1:11434",
        default_api_mode="chat",
        credential_modes=("none", "api_key"),
        docs_url="https://docs.ollama.com",
        category="local",
        notes_zh="走 Ollama 原生 API;「拉取模型」即列出本机已安装模型,无需密钥。",
    ),
    ProviderPreset(
        preset_id="custom",
        label_zh="自定义 OpenAI 兼容",
        provider_type="openai_compatible",
        default_base_url="",
        default_api_mode="chat",
        credential_modes=("none", "api_key"),
        category="custom",
        notes_zh="任意兼容 /chat/completions 的服务:LM Studio、vLLM、第三方 API 等。",
    ),
)


def provider_presets() -> tuple[ProviderPreset, ...]:
    return _PRESETS


def provider_preset_payloads() -> list[dict[str, Any]]:
    return [preset.as_dict() for preset in _PRESETS]


def get_provider_preset(preset_id: str) -> ProviderPreset | None:
    for preset in _PRESETS:
        if preset.preset_id == preset_id:
            return preset
    return None


def _assert_presets_resolvable() -> None:
    registered = adapter_registry()
    unknown = sorted({preset.provider_type for preset in _PRESETS} - set(registered))
    if unknown:
        raise RuntimeError(f"provider presets reference unregistered provider types: {unknown}")
    seen: set[str] = set()
    for preset in _PRESETS:
        if preset.preset_id in seen:
            raise RuntimeError(f"duplicate provider preset id: {preset.preset_id}")
        seen.add(preset.preset_id)


_assert_presets_resolvable()
