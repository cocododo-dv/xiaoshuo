"""StyleReference 错误体系。

PR-1 落地完整错误层级,后续 PR 直接 raise。
设计依据:《风格参考模块重构执行手册 v1.1》§6.7 / §4.1。
"""

from __future__ import annotations


class StyleReferenceError(Exception):
    """所有 style_reference 模块异常的基类。"""


class BannedAdjectiveError(StyleReferenceError):
    """抽取器产出的 finding.statement 命中禁用空泛形容词词表。"""

    def __init__(self, statement: str, matched: list[str]) -> None:
        super().__init__(
            f"finding.statement 命中空泛形容词 {matched!r}: {statement!r}",
        )
        self.statement = statement
        self.matched = list(matched)


class EvidenceShortError(StyleReferenceError):
    """抽取器产出的某条 finding 不满足 ≥2 evidence 强约束;触发两级重试机制。"""

    def __init__(self, finding_ref: str, evidence_count: int) -> None:
        super().__init__(
            f"finding {finding_ref!r} 仅有 {evidence_count} 条 evidence (要求 ≥2)",
        )
        self.finding_ref = finding_ref
        self.evidence_count = evidence_count


class EvidenceSpanError(StyleReferenceError):
    """evidence.quote 不在所引用 paragraph_id 对应文本的指定 span 内。"""

    def __init__(self, paragraph_id: str, span: tuple[int, int], quote_excerpt: str) -> None:
        super().__init__(
            f"paragraph={paragraph_id!r} span={span!r} 与 quote={quote_excerpt[:32]!r}... 不匹配",
        )
        self.paragraph_id = paragraph_id
        self.span = span
        self.quote_excerpt = quote_excerpt


class LegacyBackupMissingError(StyleReferenceError):
    """drop 旧 reference_learning 表前要求至少存在一个 backups/style_reference_legacy_*.json。"""

    def __init__(self, backup_dir: str) -> None:
        super().__init__(
            "drop 旧 reference_learning 表前必须存在 backups/style_reference_legacy_*.json。"
            f"未在 {backup_dir!r} 找到任何 JSON 备份;请先运行 "
            "`python -m novel_system.tools.reset_style_reference --backup`",
        )
        self.backup_dir = backup_dir
