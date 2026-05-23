"""Style Reference v1.1 文本工具(纯函数)。

本文件的函数全部从仓库内已验证的实现拷贝而来,**不通过 import 旧模块复用**
(全局纪律 C:新模块不依赖旧模块);旧模块在整体下线时一并删除。

拷贝来源:
- `decode_text`             ← `services/reference_learning.py:1638-1644` `_decode_text`
- `normalize_text`          ← `services/reference_learning.py:2123-2124` `_normalize_text`
- `compute_text_checksum`   ← `services/reference_learning.py:199` 内联实现
- `split_paragraphs`        ← `services/reference_learning.py:2131` 内联 + offset 追踪
- `split_sentences`         ← `services/literary_quality.py:1701-1702` `_sentences`(扩 `…`)
- `extract_dialogue_spans`  ← `services/literary_quality.py:1694-1698` `_dialogue_spans`
- `compact_ws`              ← `services/literary_quality.py:1748-1749` `_compact_ws`

新模块的 book_id 命名为 `sr_book_{sha256[:12]}`(旧模块用 `refbook_{sha256[:12]}`)。
"""

from __future__ import annotations

import hashlib
import re

from novel_system.services.errors import DomainError


def decode_text(raw: bytes) -> str:
    """按 UTF-8 → GB18030 顺序尝试解码;均失败 raise DomainError。"""
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DomainError(
        "STYLE_REFERENCE_BOOK_ENCODING_UNSUPPORTED",
        "reference book must be UTF-8 or GB18030 text",
        status_code=400,
    )


def normalize_text(text: str) -> str:
    """统一换行(CRLF / CR → LF)+ 合并 3+ 换行为双换行 + strip 首尾。

    剥除 ASCII 控制字符(\\x00-\\x08, \\x0b, \\x0c, \\x0e-\\x1f)以避免污染抽样池;
    保留 \\n / \\t。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compute_text_checksum(normalized_text: str) -> str:
    """对清洗后文本计算 SHA256 hexdigest。

    用作 book_id 前缀(`sr_book_{checksum[:12]}`)与去重键。
    """
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def split_paragraphs(text: str) -> list[tuple[int, int, str]]:
    """按空行(`\\n\\s*\\n`)切段,返回 (start_offset, end_offset, body) 三元组列表。

    offset 是相对原文(已清洗)的字符位置,end_offset 不含尾字符。
    body 已 strip 首尾空白,但不剥内部换行。
    """
    paragraphs: list[tuple[int, int, str]] = []
    offset = 0
    for part in re.split(r"\n\s*\n", text):
        stripped = part.strip()
        if not stripped:
            offset += len(part) + 2  # 跨过空行分隔(近似)
            continue
        start = text.find(stripped, offset)
        if start < 0:
            start = offset
        end = start + len(stripped)
        paragraphs.append((start, end, stripped))
        offset = end
    return paragraphs


def split_sentences(text: str) -> list[str]:
    """中文 + 英文分句:按 `。！？.!?…` 切分,strip 后去空。

    引号内不切分由上游 `extract_dialogue_spans` 单独处理。
    """
    return [part.strip() for part in re.split(r"[。！？.!?…]+", text) if part.strip()]


def extract_dialogue_spans(text: str) -> list[str]:
    """提取引号内对话内容:英文双引号 / 中文弯引号 / 日式直引号。

    返回每段引号内的连续文本(已 compact_ws),用于 dialogue_ratio 等指标。
    """
    spans: list[str] = []
    spans.extend(re.findall(r'"([^"]+)"', text, flags=re.DOTALL))
    spans.extend(re.findall(r"“([^”]+)”", text, flags=re.DOTALL))
    spans.extend(re.findall(r"「([^」]+)」", text, flags=re.DOTALL))
    return [compact_ws(span) for span in spans if span.strip()]


def compact_ws(text: str) -> str:
    """压缩所有连续空白(空格 / 制表 / 换行)为单个空格 + strip。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()
