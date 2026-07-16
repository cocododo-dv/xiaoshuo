from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    StyleReferenceBook,
    StyleReferenceParagraph,
    StyleReferenceProfile,
)
from novel_system.services.errors import DomainError
from novel_system.services.source_safety import scan_source_safety


class ReferenceSafetyService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def overview(self) -> dict[str, Any]:
        profiles = self.session.execute(
            select(StyleReferenceProfile).order_by(
                StyleReferenceProfile.created_at.desc(),
                StyleReferenceProfile.profile_id.desc(),
            )
        ).scalars().all()
        items = [self.serialize_profile(profile) for profile in profiles]
        return {
            "summary": {
                "profile_count": len(items),
                "ready_profile_count": sum(
                    1 for item in items if item["status"] in {"ready", "active"}
                ),
                "profile_with_safety_count": sum(1 for item in items if item["source_safety"]["ready"]),
            },
            "items": items,
        }

    def extract_profile(self, book_id: str) -> dict[str, Any]:
        book = self.session.get(StyleReferenceBook, book_id)
        if book is None:
            raise DomainError(
                "STYLE_REFERENCE_BOOK_NOT_FOUND",
                f"style reference book {book_id} not found",
                status_code=404,
            )
        profile = self._latest_profile(book_id)
        if profile is None:
            raise DomainError(
                "STYLE_REFERENCE_PROFILE_NOT_FOUND",
                f"style reference profile for {book_id} not found",
                status_code=404,
            )
        paragraphs = self.session.execute(
            select(StyleReferenceParagraph)
            .where(StyleReferenceParagraph.book_id == book_id)
            .order_by(
                StyleReferenceParagraph.paragraph_index.asc(),
                StyleReferenceParagraph.paragraph_id.asc(),
            )
        ).scalars().all()
        source_safety = build_reference_safety_profile(
            [paragraph.text or "" for paragraph in paragraphs],
            profile_id=profile.profile_id,
            book_id=book_id,
        )
        payload = dict(profile.profile_json or {})
        payload["source_safety"] = source_safety
        profile.profile_json = payload
        self.session.flush()
        return {"book": self._serialize_book(book), "profile": self.serialize_profile(profile)}

    def scan_text(
        self,
        *,
        text: str,
        source_profile_ids: list[str] | None = None,
        object_ref: str | None = None,
    ) -> dict[str, Any]:
        result, profile_count = self._scan_with_profiles(
            text,
            source_profile_ids=source_profile_ids,
        )
        result["object_ref"] = object_ref
        result["profile_count"] = profile_count
        return result

    def scan_runtime_text(
        self,
        texts: str | Iterable[str | None],
        *,
        source_profile_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """按运行时 bundle 的画像来源执行动态扫描，保持既有 scan payload 形状。"""
        result, _ = self._scan_with_profiles(
            texts,
            source_profile_ids=source_profile_ids,
        )
        return result

    def _scan_with_profiles(
        self,
        texts: str | Iterable[str | None],
        *,
        source_profile_ids: list[str] | None,
    ) -> tuple[dict[str, Any], int]:
        profile_ids = [item for item in (source_profile_ids or []) if isinstance(item, str) and item.strip()]
        profiles = []
        if profile_ids:
            profiles = self.session.execute(
                select(StyleReferenceProfile).where(
                    StyleReferenceProfile.profile_id.in_(profile_ids)
                )
            ).scalars().all()
        safety_profiles = []
        for profile in profiles:
            source_safety = (profile.profile_json or {}).get("source_safety")
            if isinstance(source_safety, dict):
                safety_profiles.append(source_safety)
        result = scan_source_safety(
            texts,
            source_profile_ids=profile_ids,
            reference_safety_profiles=safety_profiles,
        )
        return result, len(safety_profiles)

    def _latest_profile(self, book_id: str) -> StyleReferenceProfile | None:
        return self.session.execute(
            select(StyleReferenceProfile)
            .where(StyleReferenceProfile.book_id == book_id)
            .order_by(
                StyleReferenceProfile.created_at.desc(),
                StyleReferenceProfile.profile_id.desc(),
            )
        ).scalars().first()

    @staticmethod
    def serialize_profile(profile: StyleReferenceProfile) -> dict[str, Any]:
        source_safety = (profile.profile_json or {}).get("source_safety")
        if not isinstance(source_safety, dict):
            source_safety = {"ready": False, "protected_terms": [], "distinctive_phrases": [], "scene_bridges": []}
        return {
            "profile_id": profile.profile_id,
            "book_id": profile.book_id,
            "run_id": profile.run_id,
            "title": profile.title,
            "status": profile.status,
            "profile_json": profile.profile_json or {},
            "source_safety": source_safety,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def _serialize_book(book: StyleReferenceBook) -> dict[str, Any]:
        return {
            "book_id": book.book_id,
            "title": book.title,
            "author_label": book.author_label,
            "status": book.status,
            "total_chars": book.total_chars,
        }


def build_reference_safety_profile(texts: list[str], *, profile_id: str, book_id: str) -> dict[str, Any]:
    normalized_segments = [_compact_ws(text) for text in texts if _compact_ws(text)]
    joined = "\n".join(normalized_segments)
    protected_terms = _unique(
        [
            *_proper_name_terms(joined),
            *_distinctive_compound_terms(joined),
        ],
        limit=40,
        min_cjk_chars=2,
    )
    distinctive_phrases = _distinctive_phrases(joined)
    scene_bridges = _scene_bridges(normalized_segments)
    return {
        "ready": True,
        "profile_id": profile_id,
        "book_id": book_id,
        "protected_terms": protected_terms,
        "distinctive_phrases": distinctive_phrases,
        "scene_bridges": scene_bridges,
        "summary": {
            "protected_term_count": len(protected_terms),
            "distinctive_phrase_count": len(distinctive_phrases),
            "scene_bridge_count": len(scene_bridges),
        },
    }


def _proper_name_terms(text: str) -> list[str]:
    terms = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
    interpunct_names = re.findall(
        r"[\u4e00-\u9fff]{1,6}(?:[·・][\u4e00-\u9fff]{1,6})+",
        text,
    )
    quoted_names = re.findall(
        r"[“‘「『\"]([\u4e00-\u9fff]{2,4})[”’」』\"]",
        text,
    )
    # Chinese has no word boundaries.  A short surname-led token immediately
    # followed by a speech/action particle is a conservative name signal and,
    # unlike the old arbitrary 2-6 character chunking, does not turn every
    # clause into a protected term.  The reluctant quantifier first tries a
    # two-character name and expands to three only when the context requires it.
    contextual_names = re.findall(
        rf"([{CJK_SURNAME_CHARS}][\u4e00-\u9fff]{{1,2}}?)(?={CJK_NAME_CONTEXT})",
        text,
    )
    cjk_terms = [
        term
        for term in [*interpunct_names, *quoted_names, *contextual_names]
        if term not in CJK_NAME_STOPWORDS
    ]
    return [*terms, *cjk_terms]


def _distinctive_compound_terms(text: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", text)
    compounds: list[str] = []
    for index in range(len(words) - 1):
        left = words[index]
        right = words[index + 1]
        if left.lower() in COMMON_WORDS or right.lower() in COMMON_WORDS:
            continue
        compounds.append(f"{left} {right}")
    return compounds


def _distinctive_phrases(text: str) -> list[str]:
    words = [word.lower() for word in re.findall(r"\b[a-zA-Z][a-zA-Z-]{2,}\b", text)]
    phrases: list[str] = []
    for size in (2, 3, 4):
        grams = Counter(" ".join(words[index : index + size]) for index in range(max(0, len(words) - size + 1)))
        for phrase, count in grams.most_common(40):
            if count < 1:
                continue
            if any(part in COMMON_WORDS for part in phrase.split()):
                continue
            phrases.append(phrase)
    phrases.extend(_cjk_distinctive_phrases(text))
    return _unique(phrases, limit=40)


def _cjk_distinctive_phrases(text: str) -> list[str]:
    """Extract conservative exact-match Chinese phrase candidates.

    Eight or more contiguous ideographs are long enough to avoid treating a
    common two/four-character expression as a distinctive phrase.  Long
    clauses are sampled in overlapping twelve-character windows so the output
    remains bounded and useful for exact source-safety matching.
    """
    phrases: list[str] = []
    clauses = re.split(r"[。！？!?；;：:\n]+", text)
    for clause in clauses:
        for sequence in re.findall(r"[\u4e00-\u9fff]{8,}", clause):
            if len(sequence) <= 20:
                phrases.append(sequence)
                continue
            window_size = 12
            step = 6
            for start in range(0, len(sequence) - window_size + 1, step):
                phrases.append(sequence[start : start + window_size])
                if len(phrases) >= 80:
                    return phrases
    return phrases


def _scene_bridges(segments: list[str]) -> list[dict[str, Any]]:
    bridges: list[dict[str, Any]] = []
    for index, segment in enumerate(segments[:24]):
        terms = _unique(
            [*_proper_name_terms(segment), *_distinctive_compound_terms(segment)],
            limit=8,
            min_cjk_chars=2,
        )
        phrases = _distinctive_phrases(segment)[:8]
        tokens = _unique([*terms, *phrases], limit=10, min_cjk_chars=2)
        if len(tokens) < 2:
            continue
        bridges.append(
            {
                "bridge_id": f"bridge_{index + 1:03d}",
                "tokens": tokens,
                "evidence_preview": segment[:180],
                "risk_note": "Do not reuse this combination of entity, object, setting, and action.",
            }
        )
    return bridges


def _unique(values: list[str], *, limit: int, min_cjk_chars: int = 4) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_ws(value)
        is_cjk = re.fullmatch(r"[\u4e00-\u9fff]+", text) is not None
        minimum = min_cjk_chars if is_cjk else 4
        if len(text) < minimum:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _compact_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


COMMON_WORDS = {
    "and",
    "the",
    "with",
    "through",
    "while",
    "before",
    "after",
    "into",
    "from",
    "that",
    "this",
    "itself",
    "said",
    "carried",
    "crossed",
}


CJK_SURNAME_CHARS = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华"
    "金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花"
    "方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于"
    "时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米"
    "贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强"
    "贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支"
    "柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚"
    "程嵇邢滑裴陆荣翁荀羊惠甄曲家封芮羿储靳汲邴糜松井段富巫"
    "乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉"
    "戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸"
    "籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰"
    "郦雍郤璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕"
    "连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇"
    "广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶"
    "空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)

CJK_NAME_CONTEXT = (
    r"(?:说|问|答|道|看|望|走|来|去|把|将|向|在|从|与|和|却|又|便|仍|"
    r"正|已|没|不|拿|推|抬|站|坐|笑|哭|喊|回|转|按|递|接|打开|关上)"
)

CJK_NAME_STOPWORDS = {
    "白天",
    "方向",
    "高处",
    "夏天",
    "何时",
    "平时",
}
