"""共享的 Style Profile 字段边界。"""

from __future__ import annotations

import re
from typing import Any, Mapping


REFERENCE_BASIS_VERSION = "reference_derived_style_basis_v1"
_EXACT_METRIC_SUMMARY_RE = re.compile(
    r"(?:句均|段均|每千字|短句(?:比例|占比)|长句(?:比例|占比)|"
    r"标点(?:密度|数量)?|分号(?:密度|数量)?|问号(?:密度|数量)?)"
    r"[^；。\n]{0,20}\d"
)


def generation_safe_summary(profile_json: Mapping[str, Any] | None) -> str:
    """返回可进入生成/评论 LLM 的定性概述，绝不回退到内部量化摘要。"""

    payload = profile_json if isinstance(profile_json, Mapping) else {}
    qualitative = str(payload.get("qualitative_summary") or "").strip()
    if qualitative:
        return "" if _EXACT_METRIC_SUMMARY_RE.search(qualitative) else qualitative
    narrative = str(payload.get("narrative_summary") or "").strip()
    if narrative.startswith(("量化基线（", "量化基线(")):
        return ""
    return narrative
