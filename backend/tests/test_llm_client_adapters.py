"""新增原生 adapter 的请求/响应 golden 测试(httpx.MockTransport)。

每家断言:请求 payload 形状(含 thinking/JSON 模式差异)+ 响应解析 +
usage 归一化。现有 6 家的 golden 锁在 test_llm_client.py,此处不重复。
"""

from __future__ import annotations

import json

import httpx
import pytest

from novel_system.services.llm_client import LLMClient, LLMRequest


def _make_client(provider: str, handler, *, base_url: str = "https://example.test/v1", api_key: str | None = "test-key") -> LLMClient:
    return LLMClient(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )


def _chat_request(**overrides) -> LLMRequest:
    defaults = dict(
        model="test-model",
        messages=[
            {"role": "system", "content": "Return only JSON."},
            {"role": "user", "content": "写一个候选"},
        ],
        temperature=0.3,
        max_output_tokens=256,
        response_format="json_object",
        api_mode="chat",
        reasoning_level="medium",
    )
    defaults.update(overrides)
    return LLMRequest(**defaults)


def _openai_chat_body(model: str = "test-model") -> dict:
    return {
        "id": "chatcmpl-1",
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def test_qwen_dashscope_disables_thinking_for_json_mode() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_openai_chat_body("qwen3.7-max"))

    response = _make_client("qwen_dashscope", handler).generate(_chat_request(model="qwen3.7-max"))

    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["authorization"] == "Bearer test-key"
    # JSON 模式与思考互斥 → 显式关闭思考
    assert captured["payload"]["enable_thinking"] is False
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["max_tokens"] == 256
    assert response.structured_output == {"ok": True}
    assert response.finish_reason == "stop"
    assert response.usage == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}


def test_qwen_dashscope_enables_thinking_for_text_mode_with_medium_reasoning() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        body = _openai_chat_body("qwen3.7-max")
        body["choices"][0]["message"]["content"] = "正文片段"
        return httpx.Response(200, json=body)

    response = _make_client("qwen_dashscope", handler).generate(
        _chat_request(model="qwen3.7-max", response_format="text")
    )

    assert captured["payload"]["enable_thinking"] is True
    assert "response_format" not in captured["payload"]
    assert response.text == "正文片段"
    assert response.native_reasoning == {"enable_thinking": True}


def test_moonshot_sends_thinking_enabled_only_for_medium_and_high() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_openai_chat_body("kimi-k2.6"))

    client = _make_client("moonshot", handler)
    client.generate(_chat_request(model="kimi-k2.6", reasoning_level="high"))
    assert captured["payload"]["thinking"] == {"type": "enabled"}

    client.generate(_chat_request(model="kimi-k2.6", reasoning_level="low"))
    # 从不发送 disabled(kimi-k2.7-code 收到 disabled 会报错)
    assert "thinking" not in captured["payload"]


def test_minimax_omits_response_format_and_uses_max_completion_tokens() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_openai_chat_body("MiniMax-M3"))

    response = _make_client("minimax", handler).generate(_chat_request(model="MiniMax-M3"))

    # 兼容端点参数表没有 response_format → 不发送,JSON 由客户端解析兜底
    assert "response_format" not in captured["payload"]
    assert "max_tokens" not in captured["payload"]
    assert captured["payload"]["max_completion_tokens"] == 256
    assert captured["payload"]["thinking"] == {"type": "adaptive"}
    assert response.structured_output == {"ok": True}


def test_minimax_disables_thinking_for_low_reasoning() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_openai_chat_body("MiniMax-M3"))

    _make_client("minimax", handler).generate(_chat_request(model="MiniMax-M3", reasoning_level="off"))
    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_doubao_ark_thinking_toggle_and_json_mode() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_openai_chat_body("doubao-seed-2-0-pro-260215"))

    client = LLMClient(
        provider="doubao_ark",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="ark-key",
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    response = client.generate(_chat_request(model="doubao-seed-2-0-pro-260215", reasoning_level="high"))

    assert captured["url"] == "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert response.structured_output == {"ok": True}

    client.generate(_chat_request(model="doubao-seed-2-0-pro-260215", reasoning_level="off"))
    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_xai_maps_reasoning_levels_to_reasoning_effort() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_openai_chat_body("grok-4.3"))

    client = _make_client("xai", handler)
    client.generate(_chat_request(model="grok-4.3", reasoning_level="high"))
    assert captured["payload"]["reasoning_effort"] == "high"
    assert captured["payload"]["max_completion_tokens"] == 256

    client.generate(_chat_request(model="grok-4.3", reasoning_level="off"))
    assert captured["payload"]["reasoning_effort"] == "none"


def test_ollama_native_chat_request_and_usage() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "model": "qwen3:14b",
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 21,
                "eval_count": 9,
            },
        )

    client = LLMClient(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        api_key=None,
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    response = client.generate(_chat_request(model="qwen3:14b", credential_mode="none"))

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert "authorization" not in captured["headers"]
    payload = captured["payload"]
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["options"] == {"temperature": 0.3, "num_predict": 256}
    assert payload["think"] is True
    assert response.text == '{"ok": true}'
    assert response.structured_output == {"ok": True}
    assert response.finish_reason == "stop"
    assert response.usage == {"input_tokens": 21, "output_tokens": 9, "total_tokens": 30}


def test_ollama_passes_inline_json_schema_as_format() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": "qwen3:14b",
                "message": {"role": "assistant", "content": '{"title": "x"}'},
                "done": True,
                "done_reason": "stop",
            },
        )

    client = LLMClient(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        api_key=None,
        timeout_seconds=10,
        transport=httpx.MockTransport(handler),
    )
    schema = {"name": "draft", "schema": {"type": "object", "properties": {"title": {"type": "string"}}}}
    client.generate(_chat_request(model="qwen3:14b", credential_mode="none", response_schema=schema, reasoning_level="off"))

    assert captured["payload"]["format"] == schema["schema"]
    assert "think" not in captured["payload"]


@pytest.mark.parametrize(
    "provider",
    ["qwen_dashscope", "moonshot", "minimax", "doubao_ark", "xai"],
)
def test_chat_family_adapters_parse_missing_text_as_retryable_error(provider: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "x", "model": "m", "choices": []})

    client = _make_client(provider, handler)
    from novel_system.services.llm_client import LLMResponseError

    with pytest.raises(LLMResponseError) as excinfo:
        client.generate(_chat_request())
    assert excinfo.value.code == "LLM_RESPONSE_MISSING_TEXT"


# ---- 重试退避(限流/瞬时故障不再立即三连击) -------------------------------


def _flaky_handler(fail_statuses: list[int], success_body: dict):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = calls["n"]
        calls["n"] += 1
        if index < len(fail_statuses):
            status = fail_statuses[index]
            headers = {"Retry-After": "7"} if status == 429 else {}
            return httpx.Response(status, json={"error": {"message": "busy"}}, headers=headers)
        return httpx.Response(200, json=success_body)

    return handler


def _capture_backoff(monkeypatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr("novel_system.services.llm_client.time.sleep", sleeps.append)
    monkeypatch.setattr("novel_system.services.llm_client.random.random", lambda: 0.5)  # 抖动系数=1.0
    return sleeps


def test_retry_backoff_sleeps_exponentially_between_attempts(monkeypatch) -> None:
    sleeps = _capture_backoff(monkeypatch)
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="k",
        timeout_seconds=10,
        retry_backoff_seconds=1.0,
        transport=httpx.MockTransport(_flaky_handler([500, 503], _openai_chat_body())),
    )

    response = client.generate(_chat_request(reasoning_level="off"))

    assert response.structured_output == {"ok": True}
    assert sleeps == [1.0, 2.0]


def test_retry_backoff_honors_retry_after_header_on_429(monkeypatch) -> None:
    sleeps = _capture_backoff(monkeypatch)
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="k",
        timeout_seconds=10,
        retry_backoff_seconds=1.0,
        transport=httpx.MockTransport(_flaky_handler([429], _openai_chat_body())),
    )

    client.generate(_chat_request(reasoning_level="off"))

    assert sleeps == [7.0]  # Retry-After: 7 覆盖 1.0*2^0


def test_retry_backoff_disabled_by_default(monkeypatch) -> None:
    sleeps = _capture_backoff(monkeypatch)
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="k",
        timeout_seconds=10,
        transport=httpx.MockTransport(_flaky_handler([500, 503], _openai_chat_body())),
    )

    client.generate(_chat_request(reasoning_level="off"))

    assert sleeps == []  # 默认 0 = 不退避,既有测试节奏不受影响
