"""_llm_helper.call_llm_node 的路由解析顺序:DB node_routing 优先于 yaml task_routing。

回归背景:parse_model_routing_config 的合并是 setdefault(yaml task 条目赢),
call_llm_node 此前只读 task_routing——用户在系统设置「模型与接入」给「提炼整理」
角色槽配好的 provider/model/api_mode 被 yaml 占位(gpt-5/responses)遮蔽,
风格抽取对 chat-only 中转直接 404(Responses API endpoint returned 404)。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_system.services.style_reference import _llm_helper
from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node

NODE = "style_ref_extract_language"


def _cfg(**kw):
    base = dict(
        model="gpt-5",
        provider="openai_compatible",
        provider_id=None,
        temperature=0.15,
        max_output_tokens=3200,
        response_format="json_object",
        api_mode="responses",
        reasoning_level="medium",
        credential_mode=None,
        account_id=None,
        provider_options={},
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _CaptureClient:
    def __init__(self):
        self.last_request = None

    def generate(self, request):
        self.last_request = request
        return SimpleNamespace(structured_output={"ok": True})


@pytest.fixture()
def _fake_template(monkeypatch):
    template = SimpleNamespace(
        system_prompt="sys",
        task_prompt="task",
        structured_schema={"type": "object"},
    )
    monkeypatch.setattr(_llm_helper, "load_prompt_templates", lambda: {NODE: template})


def test_node_routing_wins_over_task_routing(monkeypatch, _fake_template) -> None:
    """DB 路由(chat / deepseek / provider_id)必须覆盖 yaml 默认(responses / gpt-5)。"""
    yaml_cfg = _cfg()  # yaml 占位:gpt-5 + responses
    db_cfg = _cfg(model="deepseek-v4-flash", provider_id="oneapi", api_mode="chat")
    routing = SimpleNamespace(
        task_routing={NODE: yaml_cfg},
        node_routing={NODE: db_cfg},
    )
    monkeypatch.setattr(_llm_helper, "load_model_routing_config", lambda: routing)

    client = _CaptureClient()
    out = call_llm_node(NODE, {"x": 1}, client)
    assert out == {"ok": True}
    req = client.last_request
    assert req.model == "deepseek-v4-flash"
    assert req.provider_id == "oneapi"
    assert req.api_mode == "chat"


def test_task_routing_fallback_when_no_node_route(monkeypatch, _fake_template) -> None:
    yaml_cfg = _cfg()
    routing = SimpleNamespace(task_routing={NODE: yaml_cfg}, node_routing={})
    monkeypatch.setattr(_llm_helper, "load_model_routing_config", lambda: routing)

    client = _CaptureClient()
    call_llm_node(NODE, {}, client)
    assert client.last_request.model == "gpt-5"
    assert client.last_request.api_mode == "responses"


def test_missing_everywhere_raises_node_error(monkeypatch, _fake_template) -> None:
    routing = SimpleNamespace(task_routing={}, node_routing={})
    monkeypatch.setattr(_llm_helper, "load_model_routing_config", lambda: routing)
    with pytest.raises(LLMNodeError):
        call_llm_node(NODE, {}, _CaptureClient())
