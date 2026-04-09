from __future__ import annotations

from novel_system.contracts.qc import HardQCOutput, SoftQCOutput


class QCValidationError(ValueError):
    pass


VALID_HARD_COMBOS = {
    ("hard_pass", True, "pass"),
    ("hard_fail_partial", False, "partial_rewrite"),
    ("hard_fail_full", False, "full_rewrite"),
    ("hard_block_human", False, "human_review_required"),
}

VALID_SOFT_COMBOS = {
    ("soft_pass", True, "pass"),
    ("soft_waive", True, "pass_with_notes"),
    ("soft_fail_partial", False, "partial_rewrite"),
    ("soft_block_human", False, "human_review_required"),
}


def validate_qc_report(qc_type: str, payload: dict):
    if qc_type == "hard_qc":
        report = HardQCOutput.model_validate(payload)
        if (report.resolution_code, report.pass_flag, report.next_action) not in VALID_HARD_COMBOS:
            raise QCValidationError("illegal hard qc combo")
        return report

    if qc_type == "soft_qc":
        report = SoftQCOutput.model_validate(payload)
        if (report.resolution_code, report.pass_flag, report.next_action) not in VALID_SOFT_COMBOS:
            raise QCValidationError("illegal soft qc combo")
        if report.resolution_code == "soft_waive":
            if not report.carry_forward_note or report.note_scope is None or not report.carry_note_text:
                raise QCValidationError("soft waive requires carry note")
        return report

    raise QCValidationError(f"unknown qc type: {qc_type}")
