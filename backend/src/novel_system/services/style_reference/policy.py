"""cloud_policy 执行单点(附录 B 数据安全契约)。

三档语义(以代码事实 CloudPolicy 枚举为准):
- ``local_only``      — 书籍内容(段落 / 引文 / 派生 finding)一律不得送往云端 LLM;
                        所有需要 LLM 的操作直接拒绝(分类降级走启发式)。
- ``segments_only``   — 仅允许按段落/片段送云,不允许整本单次发送。当前所有
                        LLM 节点(分类 / 抽取 / 合成 / 预览)都只发送段落级
                        片段或派生 statement,天然满足该档,故放行。
- ``allow_full_cloud``— 无限制。

已知非本地策略还必须有严格的 ``declared=True`` 与 ``send_rights=True`` 持久化声明；
未知/空策略一律 fail-closed。需要错误反馈的调用方执行
``ensure_cloud_llm_allowed(book, operation=...)``，只需分支判定的调用方使用
``cloud_llm_allowed(book)``。
"""

from __future__ import annotations

from typing import Any

from novel_system.services.style_reference.errors import (
    CloudPolicyBlockedError,
    CloudPolicyInvalidError,
    CloudSendRightsBlockedError,
)
from novel_system.services.style_reference.schemas import CloudPolicy


_CLOUD_POLICIES = {
    CloudPolicy.SEGMENTS_ONLY.value,
    CloudPolicy.ALLOW_FULL_CLOUD.value,
}


def cloud_llm_allowed(book: Any) -> bool:
    """仅显式非本地策略和严格发送权声明允许云端 LLM 操作。"""
    if book is None:
        return True
    policy = getattr(book, "cloud_policy", None) or ""
    if policy == CloudPolicy.LOCAL_ONLY.value:
        return False
    if policy not in _CLOUD_POLICIES:
        return False
    stats = getattr(book, "stats_json", None)
    rights = stats.get("rights_declaration") if isinstance(stats, dict) else None
    return (
        isinstance(rights, dict)
        and rights.get("declared") is True
        and rights.get("send_rights") is True
    )


def ensure_cloud_llm_allowed(book: Any, *, operation: str) -> None:
    """按本地策略、未知策略、发送权缺失三类原因拒绝云端 LLM 操作。

    book 为 None 时放行(调用方各自负责 NOT_FOUND 校验,policy 层不重复)。
    """
    if book is None:
        return
    policy = getattr(book, "cloud_policy", None) or ""
    if policy == CloudPolicy.LOCAL_ONLY.value:
        raise CloudPolicyBlockedError(
            book_id=getattr(book, "book_id", "unknown"),
            operation=operation,
        )
    if policy not in _CLOUD_POLICIES:
        raise CloudPolicyInvalidError(
            book_id=getattr(book, "book_id", "unknown"),
            operation=operation,
            cloud_policy=policy,
        )
    if not cloud_llm_allowed(book):
        raise CloudSendRightsBlockedError(
            book_id=getattr(book, "book_id", "unknown"),
            operation=operation,
            cloud_policy=policy,
        )
