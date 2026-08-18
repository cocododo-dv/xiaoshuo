from __future__ import annotations

from pydantic import Field

from novel_system.api.request_types import BoundedJsonObject, StrictRequestModel


class _CatalogChapterNarrativeRequest(StrictRequestModel):
    title: str | None = Field(default=None, max_length=500)
    act: str | None = Field(default=None, max_length=128)
    tension: float | int | None = None
    pov: str | None = Field(default=None, max_length=500)
    time_label: str | None = Field(default=None, max_length=1000)
    place: str | None = Field(default=None, max_length=2000)
    entry: str | None = Field(default=None, max_length=20_000)
    exit: str | None = Field(default=None, max_length=20_000)
    align: bool | None = None
    promise: str | None = Field(default=None, max_length=20_000)
    drama: BoundedJsonObject | None = None
    threads: list[BoundedJsonObject] | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=100_000)


class CatalogChapterCreateRequest(_CatalogChapterNarrativeRequest):
    state: str | None = Field(default=None, max_length=64)
    words_target: int | None = Field(default=None, ge=0, le=2_147_483_647)
    current: bool | None = None
    with_scene: bool | None = None
    scene_title: str | None = Field(default=None, max_length=500)


class CatalogChapterUpdateRequest(_CatalogChapterNarrativeRequest):
    state: str | None = Field(default=None, max_length=64)
    words_target: int | None = Field(default=None, ge=0, le=2_147_483_647)
    current: bool | None = None


class CatalogSceneBriefRequest(StrictRequestModel):
    goal: str | None = Field(default=None, max_length=20_000)
    conflict: str | None = Field(default=None, max_length=20_000)
    setback: str | None = Field(default=None, max_length=20_000)
    reaction: str | None = Field(default=None, max_length=20_000)
    dilemma: str | None = Field(default=None, max_length=20_000)
    decision: str | None = Field(default=None, max_length=20_000)


class _CatalogSceneFieldsRequest(StrictRequestModel):
    title: str | None = Field(default=None, max_length=500)
    kind: str | None = Field(default=None, max_length=64)
    state: str | None = Field(default=None, max_length=64)
    goal: str | None = Field(default=None, max_length=20_000)
    conflict: str | None = Field(default=None, max_length=20_000)
    setback: str | None = Field(default=None, max_length=20_000)
    reaction: str | None = Field(default=None, max_length=20_000)
    dilemma: str | None = Field(default=None, max_length=20_000)
    decision: str | None = Field(default=None, max_length=20_000)
    brief: CatalogSceneBriefRequest | None = None
    exit_change: str | None = Field(default=None, max_length=20_000)
    hook: str | None = Field(default=None, max_length=20_000)


class CatalogSceneCreateRequest(_CatalogSceneFieldsRequest):
    at: int | None = Field(default=None, ge=0, le=2_147_483_647)
    pov_character_id: str | None = Field(default=None, max_length=255)
    pov_character_name: str | None = Field(default=None, max_length=500)


class CatalogSceneUpdateRequest(_CatalogSceneFieldsRequest):
    pov_character_id: str | None = Field(default=None, max_length=255)
    pov_character_name: str | None = Field(default=None, max_length=500)


class CatalogSceneMoveRequest(StrictRequestModel):
    # Omission remains CATALOG_MOVE_INVALID in the domain service.
    to: int | None = Field(default=None, ge=0, le=2_147_483_647)


class CatalogImportRequest(StrictRequestModel):
    chapters: list[BoundedJsonObject] | None = Field(default=None, max_length=10_000)
