"""cloud_policy 执行单点(附录 B 数据安全契约)。

三档语义(以代码事实 CloudPolicy 枚举为准):
- ``local_only``      — 书籍内容(段落 / 引文 / 派生 finding)一律不得送往云端 LLM;
                        所有需要 LLM 的操作直接拒绝(分类降级走启发式)。
- ``segments_only``   — 仅允许按段落/片段送云,不允许整本单次发送。当前所有
                        LLM 节点(分类 / 抽取 / 合成 / 预览)都只发送段落级
                        片段或派生 statement,天然满足该档,故放行。
- ``allow_full_cloud``— 无限制。

所有把书籍内容送往云端 LLM 的调用方(RunOrchestrator / IngestService.reclassify /
ProfileSynthesizer / PreviewService / validation 语义路)在调用前必须执行
``ensure_cloud_llm_allowed(book, operation=...)``。
"""

from __future__ import annotations

from typing import Any

from novel_system.services.style_reference.errors import CloudPolicyBlockedError
from novel_system.services.style_reference.schemas import CloudPolicy


def cloud_llm_allowed(book: Any) -> bool:
    """book 的 cloud_policy 是否允许云端 LLM 操作(local_only → False)。"""
    policy = (getattr(book, "cloud_policy", None) or "").strip()
    return policy != CloudPolicy.LOCAL_ONLY.value


def ensure_cloud_llm_allowed(book: Any, *, operation: str) -> None:
    """local_only 的书禁止云端 LLM 操作;否则放行。

    book 为 None 时放行(调用方各自负责 NOT_FOUND 校验,policy 层不重复)。
    """
    if book is None:
        return
    if not cloud_llm_allowed(book):
        raise CloudPolicyBlockedError(
            book_id=getattr(book, "book_id", "unknown"),
            operation=operation,
        )
