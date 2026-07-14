"""统一 LLM 调用入口(PR-7 抽出)。

PR-3 BaseExtractor / PR-4 ProfileSynthesizer / PR-4 PreviewService 各自实现了
相同形态的 _call_llm 方法。本 helper 把这块复用代码抽出。PR-7 新代码
(validation/semantic.py / validation/forbidden_semantic.py)直接调本 helper;
旧 3 处实现 PR-7 内**不强制迁移**(避免范围爆炸),PR-8 之后可逐步替换。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import LlmCall
from novel_system.services.llm_accounting import (
    LLMAccountingError,
    LLMAccountingRejected,
    LLMCallContext,
    execute_accounted_call,
    is_llm_control_plane_failure,
)
from novel_system.services.llm_client import LLMRequest, load_model_routing_config
from novel_system.services.prompt_builder import load_prompt_templates
from novel_system.services.style_reference.untrusted_data import (
    UntrustedPayload,
    render_untrusted_system_prompt,
    render_untrusted_user_prompt,
)

# 路由未显式配置 timeout_seconds 时 style_ref 节点的调用超时保底(秒)
DEFAULT_TIMEOUT_SECONDS = 120.0


class LLMNodeError(Exception):
    """LLM 调用 / 解析失败的统一异常。

    caller 应捕获并按业务降级(如 validation/semantic 单调用失败时
    semantic_json=[],而非阻塞 sync_only 路径)。
    """

    def __init__(
        self,
        message: str,
        *,
        node_id: str | None = None,
        llm_call_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.llm_call_id = llm_call_id
        self.error_code = error_code


def call_llm_node(
    node_id: str,
    payload: UntrustedPayload,
    llm_client: Any,
    *,
    session: Session,
    context: LLMCallContext,
) -> dict[str, Any]:
    """对指定 task_name 节点发起一次 LLM 调用,返回 structured_output 字典。

    provider / 业务失败 raise LLMNodeError；账本控制面失败保持原异常向上冒泡。
    """
    if not isinstance(payload, UntrustedPayload):
        raise LLMNodeError(
            f"node {node_id!r} requires UntrustedPayload",
            node_id=node_id,
        )
    if context.node_id != node_id:
        raise LLMAccountingRejected(
            "LLM_ACCOUNTING_CONTEXT_INVALID",
            f"accounting context node {context.node_id!r} does not match {node_id!r}",
        )

    try:
        routing = load_model_routing_config()
        # 与 llm_task_runner / segmentation.llm 同序:DB 节点路由(系统设置「模型与
        # 接入」角色槽同步的 provider/model/api_mode)优先,config/models.yaml 的
        # task 默认仅兜底。parse 层的合并是 setdefault(yaml 赢),只读 task_routing
        # 会让用户配好的路由被 yaml 占位(gpt-5/responses)遮蔽 → chat-only 中转 404。
        node_routing = getattr(routing, "node_routing", None)
        if isinstance(node_routing, dict) and node_id in node_routing:
            task_config = node_routing[node_id]
        else:
            task_config = getattr(routing, "task_routing", {})[node_id]
        template = load_prompt_templates()[node_id]
    except KeyError as exc:
        raise LLMNodeError(
            f"task routing / prompt template missing for {node_id!r}: {exc}",
            node_id=node_id,
        ) from exc

    try:
        system_prompt = render_untrusted_system_prompt(template.system_prompt)
        user_prompt = render_untrusted_user_prompt(
            template.task_prompt,
            payload,
            kind=node_id,
        )
    except Exception:  # pylint: disable=broad-except
        raise LLMNodeError(
            f"failed to render untrusted payload for node {node_id!r}",
            node_id=node_id,
        ) from None
    request = LLMRequest(
        model=task_config.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=task_config.temperature,
        max_output_tokens=task_config.max_output_tokens,
        response_format=task_config.response_format,
        provider=task_config.provider,
        # style_ref 节点吃长 prompt(20 段原文 + schema)+ 长输出,30s 全局默认在
        # 慢速中转上容易 LLM_REQUEST_TIMEOUT;路由未显式配置时按 120s 保底
        timeout_seconds=getattr(task_config, "timeout_seconds", None) or DEFAULT_TIMEOUT_SECONDS,
        node_id=node_id,
        provider_id=getattr(task_config, "provider_id", None),
        account_id=getattr(task_config, "account_id", None),
        reasoning_level=getattr(task_config, "reasoning_level", "medium"),
        api_mode=getattr(task_config, "api_mode", "responses"),
        credential_mode=getattr(task_config, "credential_mode", None),
        provider_options=getattr(task_config, "provider_options", {}),
        response_schema=template.structured_schema,
    )
    llm_call_id = f"llm_style_{uuid.uuid4().hex}"
    try:
        response = execute_accounted_call(
            session,
            llm_client,
            request,
            context,
            llm_call_id=llm_call_id,
        )
    except Exception as exc:  # pylint: disable=broad-except
        if isinstance(exc, LLMAccountingError) or is_llm_control_plane_failure(exc):
            raise
        raise LLMNodeError(
            f"accounted LLM execution failed for {node_id!r}: {exc}",
            node_id=node_id,
            llm_call_id=llm_call_id,
            error_code=str(getattr(exc, "code", exc.__class__.__name__)),
        ) from exc
    structured = getattr(response, "structured_output", None) or {}
    parent = session.get(LlmCall, response.llm_call_id or llm_call_id)
    if parent is None:
        raise LLMAccountingError(
            "LLM_ACCOUNTING_PARENT_ID_MISSING",
            f"accounted LLM parent disappeared for {node_id!r}",
        )
    parent.response_payload_summary = {
        **dict(parent.response_payload_summary or {}),
        "structured_output_present": bool(structured),
        "structured_output_keys": sorted(str(key) for key in structured),
    }
    session.commit()
    return structured
