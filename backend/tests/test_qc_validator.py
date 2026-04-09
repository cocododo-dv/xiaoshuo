from __future__ import annotations

import pytest

from novel_system.services.qc_validator import QCValidationError, validate_qc_report


def test_soft_qc_waive_requires_carry_note() -> None:
    with pytest.raises(QCValidationError):
        validate_qc_report(
            "soft_qc",
            {
                "resolution_code": "soft_waive",
                "pass_flag": True,
                "next_action": "pass_with_notes",
                "issues": [],
            },
        )


def test_hard_qc_accepts_valid_combo() -> None:
    report = validate_qc_report(
        "hard_qc",
        {
            "resolution_code": "hard_pass",
            "pass_flag": True,
            "next_action": "pass",
            "issues": [],
            "rewrite_brief": [],
        },
    )

    assert report.resolution_code == "hard_pass"
