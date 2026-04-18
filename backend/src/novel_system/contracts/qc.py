from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class StyleDimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: float = Field(ge=0, le=1)
    evidence: str = ""


class StyleDeviation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    severity: str = ""
    patch_brief: str = ""
    evidence: str | None = None


class SoftQCOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_code: str
    pass_flag: bool
    next_action: str
    issues: list[QCIssue]
    rewrite_brief: list[str] = Field(default_factory=list)
    carry_forward_note: bool = False
    note_scope: str | None = None
    carry_note_text: str | None = None
    style_score: float | None = Field(default=None, ge=0, le=1)
    style_dimensions: list[StyleDimensionScore] = Field(default_factory=list)
    style_deviations: list[StyleDeviation] = Field(default_factory=list)
