from __future__ import annotations

from typing import Annotated

from pydantic import Field

from novel_system.api.request_types import BoundedJsonObject, StrictRequestModel


LongformReference = Annotated[str, Field(max_length=512)]
LongformTerm = Annotated[str, Field(max_length=2000)]


class _LongformAnchorFieldsRequest(StrictRequestModel):
    text: str | None = Field(default=None, max_length=100_000)
    kind: str | None = Field(default=None, max_length=64)
    source_ref: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=200_000)


class LongformAnchorCreateRequest(_LongformAnchorFieldsRequest):
    pass


class LongformAnchorUpdateRequest(_LongformAnchorFieldsRequest):
    status: str | None = Field(default=None, max_length=64)


class LongformConstraintRequest(StrictRequestModel):
    constraint_id: str | None = Field(default=None, max_length=512)
    text: str | None = Field(default=None, max_length=100_000)
    anchor_id: str | None = Field(default=None, max_length=512)
    scene_id: str | None = Field(default=None, max_length=512)
    kind: str | None = Field(default=None, max_length=128)
    enforcement: str | None = Field(default=None, max_length=64)
    check_terms: list[LongformTerm] | None = Field(default=None, max_length=1000)
    match_mode: str | None = Field(default=None, max_length=32)
    waived: bool | None = None
    waiver_reason: str | None = Field(default=None, max_length=100_000)
    # The UI edits the array returned by GET and may round-trip these two
    # server-owned fields.  They are accepted for wire compatibility, while
    # the service always recalculates both from the authenticated actor/time.
    waiver_actor_ref: str | None = Field(default=None, max_length=512)
    waived_at: str | None = Field(default=None, max_length=128)


class LongformContractUpdateRequest(StrictRequestModel):
    constraints: list[LongformConstraintRequest] | None = Field(
        default=None,
        max_length=10_000,
    )


class LongformContractTransitionRequest(StrictRequestModel):
    status: str | None = Field(default=None, max_length=64)
    force: bool | None = None


class LongformAuditFindingCreateRequest(StrictRequestModel):
    finding_id: str | None = Field(default=None, max_length=512)
    text: str | None = Field(default=None, max_length=100_000)
    kind: str | None = Field(default=None, max_length=64)
    severity: str | None = Field(default=None, max_length=64)
    evidence: str | None = Field(default=None, max_length=200_000)
    meta: BoundedJsonObject | None = None


class LongformAuditFindingAdjudicateRequest(StrictRequestModel):
    decision: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=100_000)
