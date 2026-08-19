"""内容克制风格签名的纯函数回归测试。"""

from __future__ import annotations

import pytest

from novel_system.services.style_reference import rag
from novel_system.services.style_reference.rag_evaluation import (
    load_rag_ab_manifest,
)
from novel_system.services.style_reference.style_signature import (
    STYLE_SIGNATURE_VERSION,
    extract_style_signature,
    parse_style_signature,
    query_view_for_granularity,
    style_signature_similarity,
)


@pytest.mark.parametrize(
    "case",
    load_rag_ab_manifest()["cases"],
    ids=lambda case: case["case_id"],
)
def test_same_style_different_topic_beats_same_topic_wrong_style(case):
    target = rag.content_restrained_style_score(
        case["query"],
        case["style_target"]["text"],
        granularity=case["granularity"],
    )
    distractor = rag.content_restrained_style_score(
        case["query"],
        case["content_distractor"]["text"],
        granularity=case["granularity"],
    )

    assert target["style_score"] > distractor["style_score"]
    assert target["final_score"] > distractor["final_score"]


def test_search_code_round_trip_contains_no_source_prose():
    source = "潮声缓缓漫过旧堤；他没有回头，只把衣领拢紧。"
    signature = extract_style_signature(source, granularity="paragraph")
    encoded = signature.search_text()
    restored = parse_style_signature(signature.to_json())

    assert signature.version == STYLE_SIGNATURE_VERSION
    assert source not in encoded
    assert encoded
    assert all("\ue000" <= char <= "\uf8ff" for char in encoded)
    assert restored is not None
    assert style_signature_similarity(signature, restored) > 0.999999


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("", None),
        ("not-json", None),
        ({"version": "legacy"}, None),
        ({"version": STYLE_SIGNATURE_VERSION, "features": {}}, None),
    ],
)
def test_parse_rejects_incomplete_or_legacy_signature(payload, expected):
    assert parse_style_signature(payload) is expected


def test_query_view_uses_most_recent_unit_for_each_granularity():
    text = "第一句。第二句！\n\n最后一段很短。"

    assert query_view_for_granularity(text, "sentence") == "最后一段很短。"
    assert query_view_for_granularity(text, "paragraph") == "最后一段很短。"
    assert query_view_for_granularity(text, "scene", scene_chars=5) == "一段很短。"


@pytest.mark.parametrize("granularity", ["sentence", "paragraph", "scene"])
def test_content_overlap_is_negative_only_and_score_is_bounded(granularity):
    config = rag.load_rag_config()
    no_overlap = rag._apply_content_penalty(
        0.95,
        0.0,
        granularity=granularity,
        config=config,
    )
    high_overlap = rag._apply_content_penalty(
        0.95,
        0.95,
        granularity=granularity,
        config=config,
    )

    assert 0.0 <= high_overlap <= no_overlap <= 1.0


def test_cross_granularity_signatures_never_match():
    text = "他本欲离去，然而灯犹未灭。"
    sentence = extract_style_signature(text, granularity="sentence")
    paragraph = extract_style_signature(text, granularity="paragraph")

    assert style_signature_similarity(sentence, paragraph) == 0.0
