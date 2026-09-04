from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.contracts.bundle import (
    BundleHashValidation,
    BundleSnapshotCoreV1,
    BundleSourceRefComparison,
    BundleWorksheetEnvelopeV1,
    BundleWorksheetPreviewResult,
    BundleWorksheetPreviewSummary,
    InteropArtifactReceipt,
)
from novel_system.db.models import (
    ChapterGoal,
    FinalScene,
    InteropArtifact,
    SceneBundle,
    SceneCard,
    SceneDraft,
    VersionRegistry,
)
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json, compute_bundle_hash_projection, normalize
from novel_system.services.knowledge_registry import descriptor_for_object_type
from novel_system.services.scene_digest import scene_card_digest


_VALIDATION_ERROR_LIMIT = 32


def _validation_error_details(exc: ValidationError) -> list[dict[str, Any]]:
    """把 pydantic 校验错误压成可 JSON 序列化的最小定位信息。

    ``exc.errors()`` 默认附带 ``ctx``(model_validator 抛出的 ValueError 实例本体)和
    ``input``(整份 worksheet)。前者进了 ``DomainError.details`` 会让错误信封在
    ``json.dumps`` 时炸掉,本该是 400 的契约错误变成 500 INTERNAL_ERROR;后者只是把
    作者刚贴进来的原文原样回显。``loc``/``msg``/``type`` 已足够定位到出错字段。
    """
    items = exc.errors(include_url=False, include_context=False, include_input=False)
    # 与 api/app.py 的 RequestValidationError 处理一致：最多回 32 条，多出的只报数量，
    # 免得一份严重畸形的工作表把错误信封撑成一整页。
    errors = [
        {
            "loc": list(item.get("loc", ())),
            "msg": str(item.get("msg", "")),
            "type": str(item.get("type", "")),
        }
        for item in items[:_VALIDATION_ERROR_LIMIT]
    ]
    if len(items) > _VALIDATION_ERROR_LIMIT:
        errors.append(
            {
                "loc": [],
                "msg": f"{len(items) - _VALIDATION_ERROR_LIMIT} more validation errors omitted",
                "type": "truncated",
            }
        )
    return errors


@dataclass(frozen=True)
class _SourceRefSpec:
    source_ref_key: str
    object_type: str
    digest_key: str | None
    row_key: str | None = None
    version_key: str | None = None
    source_bucket: str = "source_version_refs"
    list_values: bool = False


SOURCE_REF_SPECS: tuple[_SourceRefSpec, ...] = (
    _SourceRefSpec("chapter_goal", "chapter_goal", "chapter_goal"),
    _SourceRefSpec("scene_card", "scene_card", "scene_card"),
    _SourceRefSpec("voice_profile_id", "voice_card", "voice_card", row_key="voice_profile_row_id", version_key="voice_profile_version"),
    _SourceRefSpec(
        "relation_profile_id",
        "relation_card",
        "relation_card",
        row_key="relation_profile_row_id",
        version_key="relation_profile_version",
    ),
    _SourceRefSpec("scene_memory_prev", "scene_summary", "scene_memory"),
    _SourceRefSpec("style_rule_set_id", "style_rule", "style_rule"),
    _SourceRefSpec("banned_cluster_id", "banned_rule_cluster", "banned_rule"),
    _SourceRefSpec("calibration_line_ids", "calibration_line", "calibration_line", list_values=True),
    _SourceRefSpec("scene_summary_id", "scene_summary", "scene_summary"),
    _SourceRefSpec("chapter_summary_id", "chapter_summary", "chapter_summary"),
    _SourceRefSpec("world_rule_ids", "world_rule", "world_rule", source_bucket="resolved_ref_ids", list_values=True),
    _SourceRefSpec("open_foreshadow_ids", "foreshadow", "foreshadow", source_bucket="resolved_ref_ids", list_values=True),
)


class InteropCenterService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def preview_yaml(self, worksheet_yaml: str) -> dict[str, Any]:
        envelope, hash_validation = self._parse_yaml_to_envelope(worksheet_yaml)
        comparisons = self._build_source_ref_comparisons(envelope.snapshot)
        summary = self._build_summary(envelope, comparisons)
        preview = BundleWorksheetPreviewResult(
            envelope=envelope,
            hash_validation=hash_validation,
            summary=summary,
            source_ref_comparisons=comparisons,
        )
        return preview.model_dump(mode="json")

    def import_yaml(self, worksheet_yaml: str, *, actor_ref: str) -> dict[str, Any]:
        envelope, hash_validation = self._parse_yaml_to_envelope(worksheet_yaml)
        self._validate_import_targets(envelope)

        existing = self.session.get(SceneBundle, envelope.bundle_id)
        reused_existing_bundle = False
        if existing is not None:
            if (
                existing.bundle_snapshot_hash != envelope.bundle_snapshot_hash
                or existing.scene_id != envelope.scene_id
                or existing.chapter_id != envelope.chapter_id
            ):
                raise DomainError(
                    "INTEROP_BUNDLE_CONFLICT",
                    f"bundle {envelope.bundle_id} already exists with a different payload",
                    status_code=409,
                )
            bundle = existing
            reused_existing_bundle = True
        else:
            bundle = SceneBundle(
                bundle_id=envelope.bundle_id,
                scene_id=envelope.scene_id,
                chapter_id=envelope.chapter_id,
                execution_mode=envelope.execution_mode,
                bundle_snapshot_hash=envelope.bundle_snapshot_hash or "",
                frozen_snapshot_json=envelope.snapshot.model_dump(mode="json"),
            )
            self.session.add(bundle)
            self.session.flush()

        comparisons = self._build_source_ref_comparisons(envelope.snapshot)
        artifact = self._record_artifact(
            artifact_kind="bundle_worksheet_import",
            scene_id=envelope.scene_id,
            chapter_id=envelope.chapter_id,
            source_bundle_id=envelope.bundle_id,
            file_path=f"inline://interop-center/{uuid.uuid4().hex}.yaml",
            file_format="yaml",
            file_checksum=self._checksum(worksheet_yaml),
            direction="import",
            metadata_json={
                "actor_ref": actor_ref,
                "bundle_snapshot_hash": envelope.bundle_snapshot_hash,
                "execution_mode": envelope.execution_mode,
                "created_by_action": envelope.created_by_action,
                "hash_validation_status": hash_validation.status,
                "reused_existing_bundle": reused_existing_bundle,
            },
            auto_commit=False,
        )
        return {
            "bundle": {
                **envelope.model_dump(mode="json"),
                "reused_existing_bundle": reused_existing_bundle,
            },
            "envelope": envelope.model_dump(mode="json"),
            "hash_validation": hash_validation.model_dump(mode="json"),
            "artifact_receipt": self._artifact_receipt(artifact).model_dump(mode="json"),
            "source_ref_comparisons": [item.model_dump(mode="json") for item in comparisons],
            "actor_ref": actor_ref,
        }

    def export_bundle(self, bundle_id: str) -> dict[str, Any]:
        bundle = self.session.get(SceneBundle, bundle_id)
        if bundle is None:
            raise DomainError("INTEROP_BUNDLE_NOT_FOUND", f"bundle {bundle_id} not found", status_code=404)
        return self._bundle_payload(bundle)

    def replay_final_scene(self, row_id: str) -> dict[str, Any]:
        final = self.session.get(FinalScene, row_id)
        if final is None:
            raise DomainError("FINAL_SCENE_NOT_FOUND", f"final scene {row_id} not found", status_code=404)
        bundle = self.session.get(SceneBundle, final.source_bundle_id)
        if bundle is None:
            raise DomainError("INTEROP_BUNDLE_NOT_FOUND", f"bundle {final.source_bundle_id} not found", status_code=404)
        return self._bundle_payload(bundle)

    def replay_draft(self, row_id: str) -> dict[str, Any]:
        draft = self.session.get(SceneDraft, row_id)
        if draft is None:
            raise DomainError("SCENE_DRAFT_NOT_FOUND", f"draft {row_id} not found", status_code=404)
        bundle = self.session.get(SceneBundle, draft.source_bundle_id)
        if bundle is None:
            raise DomainError("INTEROP_BUNDLE_NOT_FOUND", f"bundle {draft.source_bundle_id} not found", status_code=404)
        return self._bundle_payload(bundle)

    def _bundle_payload(self, bundle: SceneBundle) -> dict[str, Any]:
        envelope = self._envelope_from_bundle(bundle)
        comparisons = self._build_source_ref_comparisons(envelope.snapshot)
        payload = envelope.model_dump(mode="json")
        payload["envelope"] = envelope.model_dump(mode="json")
        # Export and replay are GET endpoints.  Keep them observationally pure:
        # callers may retry, prefetch, or cache a GET and must not create a new
        # business artifact as a side effect.  The nullable key preserves the
        # response shape used by both frontends; import still returns a durable
        # artifact receipt from its POST transaction.
        payload["artifact_receipt"] = None
        payload["source_ref_comparisons"] = [item.model_dump(mode="json") for item in comparisons]
        return payload

    def _parse_yaml_to_envelope(self, worksheet_yaml: str) -> tuple[BundleWorksheetEnvelopeV1, BundleHashValidation]:
        try:
            payload = yaml.safe_load(worksheet_yaml)
        except yaml.YAMLError as exc:
            raise DomainError("BUNDLE_WORKSHEET_YAML_INVALID", "worksheet YAML could not be parsed", status_code=400) from exc

        if not isinstance(payload, dict):
            raise DomainError(
                "BUNDLE_SNAPSHOT_SCHEMA_INVALID",
                "worksheet YAML must decode to a mapping",
                status_code=400,
            )

        try:
            envelope = BundleWorksheetEnvelopeV1.model_validate(payload)
        except ValidationError as exc:
            raise DomainError(
                "BUNDLE_SNAPSHOT_SCHEMA_INVALID",
                "worksheet payload did not match the bundle worksheet contract",
                status_code=400,
                details={"errors": _validation_error_details(exc)},
            ) from exc

        computed_hash = compute_bundle_hash_projection(envelope.snapshot.to_hash_projection())
        provided_hash = envelope.bundle_snapshot_hash
        if provided_hash:
            if provided_hash != computed_hash:
                raise DomainError(
                    "BUNDLE_WORKSHEET_HASH_MISMATCH",
                    "worksheet bundle_snapshot_hash did not match the computed hash",
                    status_code=400,
                    details={"provided_hash": provided_hash, "computed_hash": computed_hash},
                )
            hash_validation = BundleHashValidation(
                status="verified",
                provided_hash=provided_hash,
                computed_hash=computed_hash,
                matches=True,
            )
        else:
            if envelope.execution_mode not in {"P0_manual", "P1_scripted"}:
                raise DomainError(
                    "BUNDLE_SNAPSHOT_SCHEMA_INVALID",
                    "hashless imports are only supported for P0_manual or P1_scripted worksheets",
                    status_code=400,
                )
            hash_validation = BundleHashValidation(
                status="computed",
                provided_hash=None,
                computed_hash=computed_hash,
                matches=True,
            )

        normalized_envelope = envelope.model_copy(update={"bundle_snapshot_hash": computed_hash})
        return normalized_envelope, hash_validation

    def _validate_import_targets(self, envelope: BundleWorksheetEnvelopeV1) -> None:
        chapter = self.session.get(ChapterGoal, envelope.chapter_id)
        if chapter is None:
            raise DomainError("INTEROP_TARGET_NOT_FOUND", f"chapter {envelope.chapter_id} not found", status_code=404)
        scene = self.session.get(SceneCard, envelope.scene_id)
        if scene is None:
            raise DomainError("INTEROP_TARGET_NOT_FOUND", f"scene {envelope.scene_id} not found", status_code=404)
        if scene.chapter_id != envelope.chapter_id:
            raise DomainError(
                "INTEROP_TARGET_NOT_FOUND",
                f"scene {envelope.scene_id} does not belong to chapter {envelope.chapter_id}",
                status_code=404,
            )

    def _envelope_from_bundle(self, bundle: SceneBundle) -> BundleWorksheetEnvelopeV1:
        try:
            snapshot = BundleSnapshotCoreV1.model_validate(bundle.frozen_snapshot_json or {})
        except ValidationError as exc:
            raise DomainError(
                "BUNDLE_SNAPSHOT_SCHEMA_INVALID",
                f"bundle {bundle.bundle_id} stored an invalid snapshot",
                status_code=409,
                details={"errors": _validation_error_details(exc)},
            ) from exc
        return BundleWorksheetEnvelopeV1(
            bundle_id=bundle.bundle_id,
            scene_id=bundle.scene_id,
            chapter_id=bundle.chapter_id,
            bundle_snapshot_hash=bundle.bundle_snapshot_hash,
            hash_contract_version=snapshot.contract_version,
            hash_alg="sha256",
            execution_mode=bundle.execution_mode,
            created_by_action=self._created_by_action(bundle),
            snapshot=snapshot,
        )

    def _created_by_action(self, bundle: SceneBundle) -> str:
        if bundle.execution_mode in {"P0_manual", "P1_scripted"}:
            return "bundle_worksheet_import"
        return "scene_workbench_run_full"

    def _record_artifact(
        self,
        *,
        artifact_kind: str,
        scene_id: str | None,
        chapter_id: str | None,
        source_bundle_id: str | None,
        file_path: str,
        file_format: str,
        file_checksum: str | None,
        direction: str,
        metadata_json: dict[str, Any],
        auto_commit: bool = True,
    ) -> InteropArtifact:
        artifact = InteropArtifact(
            artifact_id=f"interop_artifact_{uuid.uuid4().hex[:12]}",
            artifact_kind=artifact_kind,
            scene_id=scene_id,
            chapter_id=chapter_id,
            source_bundle_id=source_bundle_id,
            file_path=file_path,
            file_format=file_format,
            file_checksum=file_checksum,
            direction=direction,
            status="completed",
            metadata_json=metadata_json,
        )
        self.session.add(artifact)
        self.session.flush()
        if auto_commit:
            self.session.commit()
            self.session.refresh(artifact)
        return artifact

    def _artifact_receipt(self, artifact: InteropArtifact) -> InteropArtifactReceipt:
        return InteropArtifactReceipt.model_validate(
            {
                "artifact_id": artifact.artifact_id,
                "artifact_kind": artifact.artifact_kind,
                "scene_id": artifact.scene_id,
                "chapter_id": artifact.chapter_id,
                "source_bundle_id": artifact.source_bundle_id,
                "file_path": artifact.file_path,
                "file_format": artifact.file_format,
                "file_checksum": artifact.file_checksum,
                "direction": artifact.direction,
                "status": artifact.status,
                "metadata_json": artifact.metadata_json or {},
                "created_at": artifact.created_at,
            }
        )

    def _build_summary(
        self,
        envelope: BundleWorksheetEnvelopeV1,
        comparisons: list[BundleSourceRefComparison],
    ) -> BundleWorksheetPreviewSummary:
        version_counts = Counter(item.version_status for item in comparisons)
        text_counts = Counter(item.text_status for item in comparisons)
        return BundleWorksheetPreviewSummary(
            scene_id=envelope.scene_id,
            chapter_id=envelope.chapter_id,
            bundle_id=envelope.bundle_id,
            execution_mode=envelope.execution_mode,
            comparison_count=len(comparisons),
            version_status_counts=dict(version_counts),
            text_status_counts=dict(text_counts),
        )

    def _build_source_ref_comparisons(self, snapshot: BundleSnapshotCoreV1) -> list[BundleSourceRefComparison]:
        comparisons: list[BundleSourceRefComparison] = []
        for spec in SOURCE_REF_SPECS:
            bucket = snapshot.source_version_refs if spec.source_bucket == "source_version_refs" else snapshot.resolved_ref_ids
            raw_value = bucket.get(spec.source_ref_key)
            if raw_value in (None, "", []):
                continue

            values = raw_value if spec.list_values and isinstance(raw_value, list) else [raw_value]
            for value in values:
                lineage_key = str(value)
                source_row_id = snapshot.source_version_refs.get(spec.row_key) if spec.row_key else None
                source_version = self._coerce_int(snapshot.source_version_refs.get(spec.version_key)) if spec.version_key else None
                source_text = snapshot.inline_digests.get(spec.digest_key) if spec.digest_key else None
                active = self._lookup_active_reference(spec.object_type, lineage_key, scene_id=snapshot.scene_id)
                comparisons.append(
                    BundleSourceRefComparison(
                        object_type=spec.object_type,
                        lineage_key=lineage_key,
                        source_ref_key=spec.source_ref_key,
                        digest_key=spec.digest_key,
                        source_row_id=source_row_id,
                        source_version=source_version,
                        source_text=source_text,
                        active_row_id=active["row_id"] if active else None,
                        active_version=active["version"] if active else None,
                        active_text=active["text"] if active else None,
                        version_status=self._version_status(spec.object_type, source_row_id, source_version, active),
                        text_status=self._text_status(source_text, active["text"] if active else None),
                        target=self._target_for_comparison(spec.object_type, lineage_key, snapshot.scene_id),
                    )
                )
        return comparisons

    def _lookup_active_reference(self, object_type: str, lineage_key: str, *, scene_id: str) -> dict[str, Any] | None:
        if object_type == "chapter_goal":
            chapter = self.session.get(ChapterGoal, lineage_key)
            if chapter is None:
                return None
            return {"row_id": chapter.chapter_id, "version": None, "text": chapter.chapter_goal}

        if object_type == "scene_card":
            scene = self.session.get(SceneCard, lineage_key)
            if scene is None:
                return None
            return {"row_id": scene.scene_id, "version": None, "text": scene_card_digest(scene)}

        try:
            descriptor = descriptor_for_object_type(object_type)
        except KeyError:
            return None

        registries = self.session.execute(
            select(VersionRegistry)
            .where(
                VersionRegistry.object_type == object_type,
                VersionRegistry.lineage_key == lineage_key,
            )
            .order_by(VersionRegistry.version.desc())
        ).scalars().all()
        for registry in registries:
            row = self.session.get(descriptor.model_cls, registry.physical_row_id)
            if row is None:
                continue
            if bool(getattr(row, "active_flag", 0)):
                return {
                    "row_id": row.row_id,
                    "version": registry.version,
                    "text": getattr(row, descriptor.text_field),
                }
        return None

    def _version_status(
        self,
        object_type: str,
        source_row_id: str | None,
        source_version: int | None,
        active: dict[str, Any] | None,
    ) -> str:
        if active is None:
            return "missing_active"
        if object_type in {"chapter_goal", "scene_card"}:
            return "same"
        if source_row_id and active["row_id"] == source_row_id:
            return "same"
        if source_version is not None and active["version"] == source_version:
            return "same"
        if source_row_id is None and source_version is None:
            return "unavailable"
        return "changed"

    def _text_status(self, source_text: str | None, active_text: str | None) -> str:
        if source_text in (None, ""):
            return "unavailable"
        if active_text in (None, ""):
            return "missing_active"
        return "same" if normalize(source_text) == normalize(active_text) else "changed"

    def _target_for_comparison(self, object_type: str, lineage_key: str, scene_id: str) -> dict[str, Any] | None:
        if object_type == "chapter_goal":
            return {
                "target_type": "scene_card",
                "target_id": scene_id,
                "target_ref": f"scene_card:{scene_id}",
                "view_id": "workbench",
            }
        if object_type == "scene_card":
            return {
                "target_type": "scene_card",
                "target_id": lineage_key,
                "target_ref": f"scene_card:{lineage_key}",
                "view_id": "workbench",
            }
        return {
            "target_type": "knowledge_entry",
            "target_id": f"{object_type}:{lineage_key}",
            "target_ref": f"knowledge_entry:{object_type}:{lineage_key}",
            "view_id": "knowledge",
        }

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
