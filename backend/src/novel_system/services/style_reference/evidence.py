"""Evidence span / quote 校验。

§6.7 校验装饰器:任一 evidence.quote 不在段落 paragraph_id 对应文本中
→ raise EvidenceSpanError。`anchor_kind=counter_example` 的合成 evidence
允许 paragraph_id=None,跳过校验。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novel_system.services.style_reference.errors import EvidenceSpanError
from novel_system.services.style_reference.schemas import AnchorKind

if TYPE_CHECKING:
    from novel_system.services.style_reference.schemas import (
        ExtractionEvidenceInput,
        ExtractionFindingInput,
    )


def validate_evidence_spans(
    finding: ExtractionFindingInput,
    paragraph_lookup: dict[str, str],
) -> None:
    """对 finding 内每条 evidence 校验 quote 是否包含在对应段落文本内。

    `paragraph_lookup`: {paragraph_id: paragraph_text}。
    校验失败抛 `EvidenceSpanError`(StyleReferenceError 子类)。
    """
    for evidence in finding.evidence:
        if evidence.anchor_kind in (
            AnchorKind.COUNTER_EXAMPLE,
            AnchorKind.AUTHOR_AVOIDANCE,
        ):
            continue
        if evidence.paragraph_id is None:
            continue
        text = paragraph_lookup.get(evidence.paragraph_id)
        if text is None:
            raise EvidenceSpanError(
                paragraph_id=evidence.paragraph_id,
                span=evidence.span or (0, 0),
                quote_excerpt=evidence.quote,
            )
        if evidence.quote not in text:
            raise EvidenceSpanError(
                paragraph_id=evidence.paragraph_id,
                span=evidence.span or (0, 0),
                quote_excerpt=evidence.quote,
            )
