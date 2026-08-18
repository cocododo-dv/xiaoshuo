from __future__ import annotations

from pydantic import Field

from novel_system.api.request_types import BoundedJsonObject, StrictRequestModel


class ChapterPlanCandidatesRequest(StrictRequestModel):
    direction_hint: str | None = Field(default=None, max_length=300)


class ChapterPlanFillRequest(StrictRequestModel):
    # Keep domain vocabulary validation in the service for CHAPTER_PLAN_MODE_INVALID.
    mode: str | None = Field(default=None, max_length=32)
    candidate: BoundedJsonObject | None = None


class ChapterPlanApplyRequest(StrictRequestModel):
    # The patch document is versioned and sanitized against the live catalog;
    # only its command envelope is closed here.
    patch: BoundedJsonObject | None = None
