from __future__ import annotations

from novel_system.services.reference_safety import build_reference_safety_profile
from novel_system.services.source_safety import scan_source_safety


def test_reference_profile_keeps_two_and_three_character_chinese_names() -> None:
    profile = build_reference_safety_profile(
        [
            "顾舟把铜铃藏进袖口。苏晚晴将烧焦的车票压在桌角。",
            "顾舟没有回头。苏晚晴却关上了门。",
        ],
        profile_id="profile_short_names",
        book_id="book_short_names",
    )

    assert "顾舟" in profile["protected_terms"]
    assert "苏晚晴" in profile["protected_terms"]

    scan = scan_source_safety(
        "新稿里写成顾 舟递出了车票。",
        reference_safety_profiles=[profile],
    )
    assert scan["safe"] is False
    assert any(risk["matched"] == "顾舟" for risk in scan["risks"])


def test_reference_profile_extracts_long_chinese_distinctive_phrases() -> None:
    phrase = "雨水沿着倒悬的铜钟一滴滴爬回天空"
    profile = build_reference_safety_profile(
        [f"{phrase}。顾舟把最后一张车票烧成灰。"],
        profile_id="profile_cjk_phrase",
        book_id="book_cjk_phrase",
    )

    assert phrase in profile["distinctive_phrases"]
    scan = scan_source_safety(
        f"另一章仍写道：{phrase}。",
        reference_safety_profiles=[profile],
    )
    assert scan["safe"] is False
    assert any(
        risk["risk_type"] == "distinctive_phrase" and risk["matched"] == phrase
        for risk in scan["risks"]
    )


def test_common_chinese_time_word_is_not_promoted_to_a_short_name() -> None:
    profile = build_reference_safety_profile(
        ["白天在码头装货，夜里在仓库清点。"],
        profile_id="profile_common_words",
        book_id="book_common_words",
    )

    assert "白天" not in profile["protected_terms"]

