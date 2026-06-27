"""Red→green guard for BUG-002: protected-source-term scan must not be evaded
by trivial variants (intra-term whitespace/punctuation, traditional Chinese).

Source safety is a North-Star red line: a missed leak (false negative) is the
expensive failure mode. These tests pin the variant-detection contract while
also asserting clean original prose is *not* flagged (false-positive guard).
"""

from __future__ import annotations

from novel_system.services.source_safety import (
    PROTECTED_SOURCE_TERMS,
    scan_source_safety,
)


def test_direct_literal_leak_is_still_blocked() -> None:
    """Regression: the plain substring path must keep working unchanged."""
    result = scan_source_safety("第二场错误出现了龙族与楚子航。")
    assert result["safe"] is False
    # original simplified term + PROTECTED_SOURCE_TERMS iteration order preserved
    assert result["blocked_terms"] == ["龙族", "楚子航"]


def test_intra_term_whitespace_variant_is_detected() -> None:
    """BUG-002 repro: a space spliced inside the term ("屠 龙") must not evade."""
    result = scan_source_safety("反派在终章完成了屠 龙的仪式。")
    assert result["safe"] is False
    assert "屠龙" in result["blocked_terms"]


def test_intra_term_punctuation_variant_is_detected() -> None:
    """BUG-002 repro: inserted punctuation ("屠-龙", "龙·族") must not evade."""
    dash = scan_source_safety("他立誓要屠-龙。")
    assert dash["safe"] is False
    assert "屠龙" in dash["blocked_terms"]

    dot = scan_source_safety("传说里的龙·族早已覆灭。")
    assert dot["safe"] is False
    assert "龙族" in dot["blocked_terms"]


def test_traditional_chinese_variant_is_detected() -> None:
    """BUG-002 repro: traditional forms ("龍族", "屠龍", "血統") must not evade."""
    assert "龙族" in PROTECTED_SOURCE_TERMS  # the term list is simplified
    result = scan_source_safety("成稿里赫然写着龍族与屠龍，还有血統一词。")
    assert result["safe"] is False
    blocked = result["blocked_terms"]
    assert "龙族" in blocked
    assert "屠龙" in blocked
    assert "血统" in blocked


def test_clean_original_text_is_safe() -> None:
    """False-positive guard: clean original prose stays safe=True."""
    clean = (
        "少年在荒原尽头点燃篝火，雪光映着他疲惫的眼睛，"
        "远处传来狼群低沉的嚎叫，像是替谁守着一场无名的葬礼。"
    )
    result = scan_source_safety(clean)
    assert result["safe"] is True
    assert result["blocked_terms"] == []


def test_reference_profile_term_variant_is_flagged() -> None:
    """Second layer (profile-derived protected terms) is hardened too: a
    traditional + spaced variant of a CJK profile term still raises a risk."""
    profiles = [
        {
            "profile_id": "refprofile_x",
            "protected_terms": ["青铜与火"],
            "distinctive_phrases": [],
            "scene_bridges": [],
        }
    ]
    # traditional 青銅與火 with an inserted space — must still be caught
    result = scan_source_safety(
        "他举起了青 銅與火的旗帜。",
        reference_safety_profiles=profiles,
    )
    assert result["safe"] is False
    assert result["risk_count"] >= 1
    assert any(risk.get("matched") == "青铜与火" or risk.get("risk_type") == "exact_term" for risk in result["risks"])
