from novel_system.services.style_reference.profile_fields import (
    generation_safe_summary,
)


def test_generation_safe_summary_prefers_qualitative_profile_field() -> None:
    summary = generation_safe_summary(
        {
            "narrative_summary": "量化基线（内部）：句均约18.0字。",
            "qualitative_summary": "转折处让动作先于人物判断。",
        }
    )

    assert summary == "转折处让动作先于人物判断。"


def test_generation_safe_summary_never_falls_back_to_internal_metric_summary() -> None:
    assert generation_safe_summary(
        {"narrative_summary": "量化基线（内部）：句均约18.0字。"}
    ) == ""


def test_generation_safe_summary_rejects_exact_metric_claim_in_qualitative_field() -> None:
    assert generation_safe_summary(
        {"qualitative_summary": "叙述克制，句均约18.0字，动作先于判断。"}
    ) == ""
