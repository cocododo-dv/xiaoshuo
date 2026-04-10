from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrderedInjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str
    ref_id: str
    digest_key: str


class BundleSnapshotHashProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    stage_allowlist_name: str
    source_version_refs: dict[str, Any]
    resolved_ref_ids: dict[str, list[str]]
    ordered_injections: list[OrderedInjection]
    inline_digests: dict[str, str]


class BundleSnapshotCoreV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    stage_allowlist_name: str
    scene_id: str
    chapter_id: str
    source_version_refs: dict[str, Any]
    resolved_ref_ids: dict[str, list[str]]
    ordered_injections: list[OrderedInjection]
    inline_digests: dict[str, str]

    def to_hash_projection(self) -> BundleSnapshotHashProjection:
        return BundleSnapshotHashProjection(
            contract_version=self.contract_version,
            stage_allowlist_name=self.stage_allowlist_name,
            source_version_refs=self.source_version_refs,
            resolved_ref_ids=self.resolved_ref_ids,
            ordered_injections=self.ordered_injections,
            inline_digests=self.inline_digests,
        )


class BundleWorksheetEnvelopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    scene_id: str
    chapter_id: str
    bundle_snapshot_hash: str | None = None
    hash_contract_version: str = "BSHASH_v1"
    hash_alg: str = "sha256"
    execution_mode: str = "P0_manual"
    created_by_action: str = "bundle_worksheet_import"
    snapshot: BundleSnapshotCoreV1

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> "BundleWorksheetEnvelopeV1":
        if self.snapshot.scene_id != self.scene_id:
            raise ValueError("snapshot.scene_id must match envelope.scene_id")
        if self.snapshot.chapter_id != self.chapter_id:
            raise ValueError("snapshot.chapter_id must match envelope.chapter_id")
        return self


class BundleHashValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    provided_hash: str | None = None
    computed_hash: str
    matches: bool


class BundleSourceRefComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    lineage_key: str
    source_ref_key: str
    digest_key: str | None = None
    source_row_id: str | None = None
    source_version: int | None = None
    source_text: str | None = None
    active_row_id: str | None = None
    active_version: int | None = None
    active_text: str | None = None
    version_status: str
    text_status: str
    target: dict[str, Any] | None = None


class InteropArtifactReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_kind: str
    scene_id: str | None = None
    chapter_id: str | None = None
    source_bundle_id: str | None = None
    file_path: str
    file_format: str
    file_checksum: str | None = None
    direction: str
    status: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class BundleWorksheetPreviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    chapter_id: str
    bundle_id: str
    execution_mode: str
    comparison_count: int
    version_status_counts: dict[str, int]
    text_status_counts: dict[str, int]


class BundleWorksheetPreviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: BundleWorksheetEnvelopeV1
    hash_validation: BundleHashValidation
    summary: BundleWorksheetPreviewSummary
    source_ref_comparisons: list[BundleSourceRefComparison]


BundleWorksheetEnvelope = BundleWorksheetEnvelopeV1
