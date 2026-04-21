from __future__ import annotations

import json

from novel_system.services.character_continuity import (
    build_character_contract_digest,
    detect_character_pronoun_drift,
    detect_mechanical_required_beat_listing,
)


def test_build_character_contract_digest_extracts_chinese_voice_metadata() -> None:
    digest = build_character_contract_digest(
        pov_character_id="LIN_CEN",
        onstage_character_ids=["LIN_CEN", "XU_WANG"],
        voice_profile_content="角色名：林岑\n代词：她\n角色职责：档案修复师\n别名：小林",
        relation_profile_content="林岑与许望互相信任，但在公开真相的时机上有分歧。",
    )

    payload = json.loads(digest)

    assert payload["contract_version"] == "CHARACTER_CONTRACT_v1"
    assert payload["characters"][0] == {
        "character_id": "LIN_CEN",
        "display_name": "林岑",
        "pronouns": ["她"],
        "role": "档案修复师",
        "aliases": ["小林"],
    }
    assert payload["relationship_stance"] == "林岑与许望互相信任，但在公开真相的时机上有分歧。"


def test_build_character_contract_digest_dedupes_pov_display_name() -> None:
    digest = build_character_contract_digest(
        pov_character_id="CHAR_LINCEN",
        onstage_character_ids=["林岑", "许望", "幸存者阿砚"],
        voice_profile_content="角色名：林岑\n代词：她\n角色职责：档案修复师\n别名：小林",
        relation_profile_content=None,
    )

    payload = json.loads(digest)

    assert [character["display_name"] for character in payload["characters"]] == ["林岑", "许望", "幸存者阿砚"]
    assert payload["characters"][0]["pronouns"] == ["她"]


def test_detect_character_pronoun_drift_flags_wrong_chinese_pronoun_near_name() -> None:
    digest = build_character_contract_digest(
        pov_character_id="LIN_CEN",
        onstage_character_ids=["LIN_CEN", "XU_WANG"],
        voice_profile_content="角色名：林岑\n代词：她\n角色职责：档案修复师",
        relation_profile_content=None,
    )

    issues = detect_character_pronoun_drift(
        "林岑把盐钟残片放在灯下。他确认刻痕被人改过，声音仍然很稳。",
        digest,
    )

    assert issues == [
        {
            "issue_key": "character_pronoun_drift",
            "message": "林岑 expects pronoun 她 but nearby text uses 他.",
            "character_id": "LIN_CEN",
            "display_name": "林岑",
            "expected_pronoun": "她",
            "found_pronoun": "他",
        }
    ]


def test_detect_character_pronoun_drift_stops_when_other_character_is_named_first() -> None:
    digest = build_character_contract_digest(
        pov_character_id="CHAR_LINCEN",
        onstage_character_ids=["林岑", "许望", "幸存者阿砚"],
        voice_profile_content="角色名：林岑\n代词：她\n角色职责：档案修复师",
        relation_profile_content=None,
    )

    issues = detect_character_pronoun_drift(
        (
            "林岑的指尖划过纸页边缘，语气冷硬：“公开真相会让更多人暴露。"
            "我们得先转移幸存者。”\n\n"
            "“阿砚的声音。”许望皱眉，“他还在被追踪。”"
        ),
        digest,
    )

    assert issues == []


def test_detect_mechanical_required_beat_listing_flags_tail_loaded_checklist() -> None:
    issue = detect_mechanical_required_beat_listing(
        content=(
            "林岑先听见雾堤下的回声，随后把证据封进纸袋。\n\n"
            "最后需要包含：盐钟残片、潮汐记录、幸存者名单。"
        ),
        must_include_text="盐钟残片；潮汐记录；幸存者名单",
    )

    assert issue == {
        "issue_key": "mechanical_required_beat_listing",
        "message": "Required beats appear as a tail-loaded checklist instead of being woven into scene action.",
        "matched_terms": ["盐钟残片", "潮汐记录", "幸存者名单"],
    }
