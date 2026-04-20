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
    ("soft_patch", False, "patch"),
    ("soft_waive", True, "pass_with_notes"),
    ("soft_block_human", False, "human_review_required"),
}


def validate_qc_report(qc_type: str, payload: dict):
    normalized_payload = _normalize_local_model_payload(qc_type, payload)
    if qc_type == "hard_qc":
        report = HardQCOutput.model_validate(normalized_payload)
        if (report.resolution_code, report.pass_flag, report.next_action) not in VALID_HARD_COMBOS:
            raise QCValidationError("illegal hard qc combo")
        return report

    if qc_type == "soft_qc":
        report = SoftQCOutput.model_validate(normalized_payload)
        if (report.resolution_code, report.pass_flag, report.next_action) not in VALID_SOFT_COMBOS:
            raise QCValidationError("illegal soft qc combo")
        if report.resolution_code == "soft_patch" and not report.rewrite_brief:
            raise QCValidationError("soft patch requires rewrite brief")
        if report.resolution_code == "soft_waive":
            if not report.carry_forward_note or report.note_scope is None or not report.carry_note_text:
                raise QCValidationError("soft waive requires carry note")
        return report

    raise QCValidationError(f"unknown qc type: {qc_type}")


def _normalize_local_model_payload(qc_type: str, payload: dict) -> dict:
    normalized = dict(payload)
    rewrite_brief = normalized.get("rewrite_brief")
    if isinstance(rewrite_brief, str):
        rewrite_brief = rewrite_brief.strip()
        normalized["rewrite_brief"] = [rewrite_brief] if rewrite_brief else []
    issues = normalized.get("issues")
    if isinstance(issues, list):
        normalized["issues"] = [_normalize_issue(issue) for issue in issues]
    flattened_style_deviation = _pop_flattened_style_deviation(normalized)
    if flattened_style_deviation and not normalized.get("style_deviations"):
        normalized["style_deviations"] = flattened_style_deviation
    style_deviations = normalized.get("style_deviations")
    if isinstance(style_deviations, dict):
        normalized["style_deviations"] = [_normalize_style_deviation(style_deviations)]
    elif isinstance(style_deviations, list):
        normalized["style_deviations"] = [_normalize_style_deviation(item) for item in style_deviations]
    _derive_pass_flag(qc_type, normalized)
    return normalized


def _derive_pass_flag(qc_type: str, payload: dict) -> None:
    resolution_code = payload.get("resolution_code")
    next_action = payload.get("next_action")
    combos = VALID_HARD_COMBOS if qc_type == "hard_qc" else VALID_SOFT_COMBOS if qc_type == "soft_qc" else set()
    for combo_resolution, combo_pass_flag, combo_next_action in combos:
        if resolution_code == combo_resolution and next_action == combo_next_action:
            payload["pass_flag"] = combo_pass_flag
            return


def _pop_flattened_style_deviation(payload: dict) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for key in list(payload):
        if not isinstance(key, str) or not key.startswith("style_deviations."):
            continue
        flattened[key.split(".", 1)[1]] = payload.pop(key)
    return flattened


def _normalize_issue(issue: object) -> object:
    if not isinstance(issue, dict):
        return issue
    issue_key = issue.get("issue_key")
    message = issue.get("message")
    alias_key = issue.get("type")
    alias_message = issue.get("description")
    normalized: dict[str, str] = {}
    if not isinstance(issue_key, str) or not issue_key.strip():
        normalized["issue_key"] = str(alias_key).strip() if alias_key is not None and str(alias_key).strip() else "local_model_issue"
    else:
        normalized["issue_key"] = issue_key.strip()
    if not isinstance(message, str) or not message.strip():
        normalized["message"] = (
            str(alias_message).strip() if alias_message is not None and str(alias_message).strip() else ""
        )
    else:
        normalized["message"] = message.strip()
    return normalized


def _normalize_style_deviation(item: object) -> object:
    if not isinstance(item, dict):
        return item
    dimension = item.get("dimension") or item.get("type") or item.get("name") or item.get("issue_key") or "style"
    patch_brief = item.get("patch_brief") or item.get("rewrite_brief") or item.get("description") or item.get("message") or ""
    evidence = item.get("evidence")
    if evidence is None and item.get("description") and item.get("description") != patch_brief:
        evidence = item.get("description")
    return {
        "dimension": str(dimension).strip() or "style",
        "severity": str(item.get("severity") or "").strip(),
        "patch_brief": str(patch_brief).strip(),
        "evidence": str(evidence).strip() if evidence is not None and str(evidence).strip() else None,
    }
