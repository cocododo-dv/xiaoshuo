"""禁用空泛形容词校验装饰器。

§6.7:任一 finding.statement 命中 banned_adjectives.yaml 词表 → raise
BannedAdjectiveError。BaseExtractor 在解析 LLM 响应时调用此函数,触发后
直接进入 fail 路径(下层重试不再补)。
"""

from __future__ import annotations

from novel_system.services.style_reference.config_loader import load_yaml_config
from novel_system.services.style_reference.errors import BannedAdjectiveError


def _banned_terms() -> list[str]:
    """从 `config/style_reference/banned_adjectives.yaml` 读词表;list[str]。"""
    cfg = load_yaml_config("banned_adjectives")
    items = cfg.get("items", [])
    return [str(term) for term in items]


def check_banned_adjectives(statement: str) -> list[str]:
    """返回 statement 中命中的禁用词列表(空 list 表示通过)。"""
    matched: list[str] = []
    for term in _banned_terms():
        if term and term in statement:
            matched.append(term)
    return matched


def assert_no_banned_adjective(statement: str) -> None:
    """命中即 raise BannedAdjectiveError;否则返回 None。"""
    matched = check_banned_adjectives(statement)
    if matched:
        raise BannedAdjectiveError(statement=statement, matched=matched)
