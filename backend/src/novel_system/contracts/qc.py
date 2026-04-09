from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class QCIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_key: str = "ok"
    message: str = ""


class HardQCOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_code: str
    pass_flag: bool
    next_action: str
    issues: list[QCIssue]
    rewrite_brief: list[str]


class SoftQCOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_code: str
    pass_flag: bool
    next_action: str
    issues: list[QCIssue]
    carry_forward_note: bool = False
    note_scope: str | None = None
    carry_note_text: str | None = None
