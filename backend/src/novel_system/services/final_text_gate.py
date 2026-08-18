from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import SceneBundle, SceneCard, SceneRunState
from novel_system.services.character_continuity import (
    detect_character_pronoun_drift,
    detect_mechanical_required_beat_listing,
)
from novel_system.services.content_safety import ContentSafetyService
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import verify_bundle_snapshot_hash
from novel_system.services.literary_quality import (
    DIMENSION_WEIGHTS,
    QUALITY_DIMENSIONS,
    analyze_literary_quality,
    get_dimension_weights,
)
from novel_system.services.quality_classifier import blocking_issues, classify_issues
from novel_system.services.qc_constraints import contains_forbidden_term, source_field_satisfied
from novel_system.services.reference_safety import ReferenceSafetyService
from novel_system.services.scene_ownership import require_scene_project_id
from novel_system.services.source_safety import source_profile_ids_from_snapshot


FINAL_TEXT_GATE_SCHEMA_VERSION = 3
CHARACTER_SCENE_CORE_MIN = 0.80
ENDING_DRIVE_MIN = 0.78
CHOICE_PRESSURE_MIN = 0.78

_CHARACTER_SCENE_CORE_DIMENSIONS = (
    "no_choice_scene",
    "choice_pressure",
    "painless_scene",
    "conflict_too_clean",
)


class FinalTextGateService:
    """Deterministic last-mile checks over the exact text being promoted.

    Q0/Q1 findings block every archive path. Literary findings remain advisory
    for ordinary delivery, while the stronger auto-rewrite promotion contract
    also requires its real, content-derived scores to meet the configured floor.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def evaluate(
        self,
        *,
        scene_id: str,
        content: str,
        source_bundle_id: str | None = None,
        allow_author_waiver: bool = True,
        author_confirmed_final: bool = False,
        accepted_warning_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        scene = self.session.get(SceneCard, scene_id)
        if scene is not None and scene.trashed_flag:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)

        actual_content = str(content or "")
        content_hash = hashlib.sha256(actual_content.encode("utf-8")).hexdigest()
        bundle = self._resolve_bundle(scene_id, source_bundle_id)
        bundle_integrity = (
            verify_bundle_snapshot_hash(
                bundle.frozen_snapshot_json,
                expected_hash=bundle.bundle_snapshot_hash,
            )
            if bundle is not None
            else None
        )
        bundle_integrity_blockers = (
            []
            if bundle_integrity is None or bundle_integrity["valid"]
            else [f"bundle_integrity:{bundle_integrity['error_code']}"]
        )

        source_safety, source_blockers = self._source_safety(actual_content, bundle)
        content_safety = ContentSafetyService.assess(
            actual_content,
            acknowledged_codes=accepted_warning_codes or [],
        )
        continuity = self._continuity(
            scene,
            actual_content,
            bundle,
            allow_author_waiver=allow_author_waiver,
        )
        longform = self._longform_contract(
            scene,
            actual_content,
            bundle,
            bundle_integrity=bundle_integrity,
        )
        literary = self._literary(scene, actual_content)

        archive_blockers = list(
            dict.fromkeys(
                [
                    *source_blockers,
                    *content_safety["blocking_codes"],
                    *continuity["blockers"],
                    *bundle_integrity_blockers,
                    *longform["blockers"],
                ]
            )
        )
        if not actual_content.strip():
            archive_blockers.insert(0, "empty_content")

        promotion_blockers = list(archive_blockers)
        promotion_blockers.extend(literary["promotion_blockers"])
        promotion_blockers = list(dict.fromkeys(promotion_blockers))

        warnings = [
            *content_safety["warnings"],
            *continuity["warnings"],
            *longform["warnings"],
            *literary["warnings"],
        ]
        warning_codes = list(
            dict.fromkeys(
                str(item.get("issue_key") or "unknown")
                for item in warnings
                if isinstance(item, dict)
            )
        )
        safe_to_archive = not archive_blockers
        literary_warnings_unresolved = bool(literary["warnings"]) and not author_confirmed_final
        return {
            "schema_version": FINAL_TEXT_GATE_SCHEMA_VERSION,
            "content_hash": content_hash,
            "source_bundle_id": bundle.bundle_id if bundle is not None else source_bundle_id,
            "safe_to_archive": safe_to_archive,
            "literary_warnings_unresolved": literary_warnings_unresolved,
            "author_confirmed_final": bool(author_confirmed_final),
            "finality": {
                "safe_to_archive": safe_to_archive,
                "literary_warnings_unresolved": literary_warnings_unresolved,
                "author_confirmed_final": bool(author_confirmed_final),
            },
            # Backward-compatible alias retained for existing archive callers.
            "archivable": safe_to_archive,
            "auto_promotable": not promotion_blockers,
            # ``blockers`` remains a convenient alias for promotion callers.
            "blockers": promotion_blockers,
            "archive_blockers": archive_blockers,
            "promotion_blockers": promotion_blockers,
            "blocking_codes": archive_blockers,
            "promotion_blocking_codes": promotion_blockers,
            "warning_codes": warning_codes,
            "warnings": warnings,
            "source_safety": source_safety,
            "bundle_integrity": bundle_integrity,
            "content_safety": content_safety,
            "continuity": continuity,
            "longform_contract": longform,
            "literary": literary,
            "literary_quality": literary,
        }

    @staticmethod
    def raise_if_not_archivable(result: dict[str, Any], *, scene_id: str) -> None:
        blockers = result.get("archive_blockers") or []
        if not blockers:
            return
        if "empty_content" in blockers:
            raise DomainError(
                "FINAL_TEXT_EMPTY",
                "empty final text cannot be archived",
                status_code=409,
                details={"scene_id": scene_id, "final_text_gate": result},
            )
        if any(str(item).startswith("bundle_integrity:") for item in blockers):
            raise DomainError(
                "FINAL_TEXT_BUNDLE_INTEGRITY_FAILED",
                "frozen generation bundle no longer matches its recorded hash",
                status_code=409,
                details={"scene_id": scene_id, "final_text_gate": result},
            )
        if any(str(item).startswith("source_safety") for item in blockers):
            unavailable = "source_safety_unavailable" in blockers
            raise DomainError(
                "SOURCE_SAFETY_UNAVAILABLE" if unavailable else "SOURCE_SAFETY_BLOCKED",
                (
                    "source-safety scan could not complete"
                    if unavailable
                    else "source-safety scan blocked archive — text is kept and can be revised"
                ),
                status_code=409,
                details={"scene_id": scene_id, "final_text_gate": result},
            )
        if any(str(item).startswith("content_safety_review:") for item in blockers):
            raise DomainError(
                "CONTENT_SAFETY_REVIEW_REQUIRED",
                "content-risk heuristics require explicit author review before archive",
                status_code=409,
                details={"scene_id": scene_id, "final_text_gate": result},
            )
        if any(str(item).startswith("longform_contract:") for item in blockers):
            raise DomainError(
                "FINAL_TEXT_LONGFORM_CONTRACT_BLOCKED",
                "frozen chapter-contract checks block archive — satisfy or explicitly waive the constraint",
                status_code=409,
                details={"scene_id": scene_id, "final_text_gate": result},
            )
        raise DomainError(
            "FINAL_TEXT_CONTINUITY_BLOCKED",
            "verified continuity findings block archive — revise or confirm the source facts first",
            status_code=409,
            details={"scene_id": scene_id, "final_text_gate": result},
        )

    def _resolve_bundle(self, scene_id: str, source_bundle_id: str | None) -> SceneBundle | None:
        if source_bundle_id:
            bundle = self.session.get(SceneBundle, source_bundle_id)
            if bundle is not None and bundle.scene_id == scene_id:
                return bundle
        state = self.session.get(SceneRunState, scene_id)
        if state is None or not state.current_bundle_id:
            return None
        bundle = self.session.get(SceneBundle, state.current_bundle_id)
        if bundle is None or bundle.scene_id != scene_id:
            return None
        return bundle

    def _source_safety(
        self,
        content: str,
        bundle: SceneBundle | None,
    ) -> tuple[dict[str, Any], list[str]]:
        try:
            result = ReferenceSafetyService(self.session).scan_runtime_text(
                content,
                source_profile_ids=source_profile_ids_from_snapshot(
                    bundle.frozen_snapshot_json if bundle is not None else None
                ),
            )
        except Exception as exc:  # noqa: BLE001 - a safety assertion must fail closed
            return (
                {
                    "safe": False,
                    "error_code": "SOURCE_SAFETY_UNAVAILABLE",
                    "error_type": type(exc).__name__,
                },
                ["source_safety_unavailable"],
            )
        return result, ([] if result.get("safe", True) else ["source_safety"])

    def _continuity(
        self,
        scene: SceneCard | None,
        content: str,
        bundle: SceneBundle | None,
        *,
        allow_author_waiver: bool,
    ) -> dict[str, Any]:
        if scene is None:
            warning = {
                "issue_key": "continuity_validation_unavailable",
                "quality_level": "Q2",
                "blocking": False,
                "message": "Scene card is unavailable; archive continuity checks were skipped.",
            }
            return {
                "issues": [],
                "blocking_issues": [],
                "blockers": [],
                "warnings": [warning],
            }

        issues: list[dict[str, Any]] = []
        if isinstance(scene.must_include_text, str) and scene.must_include_text.strip():
            if not source_field_satisfied(scene.must_include_text, content):
                issues.append(
                    {
                        "issue_key": "missing_required_text",
                        "message": "Final text does not satisfy scene-card required text.",
                        "source": "deterministic",
                        "authority_ref": f"scene_card:{scene.scene_id}.must_include_text",
                    }
                )
        if contains_forbidden_term(scene.forbidden_text, content):
            issues.append(
                {
                    "issue_key": "forbidden_text",
                    "message": "Final text contains scene-card forbidden text.",
                    "source": "deterministic",
                    "authority_ref": f"scene_card:{scene.scene_id}.forbidden_text",
                }
            )

        snapshot = bundle.frozen_snapshot_json if bundle is not None else {}
        inline_digests = snapshot.get("inline_digests") if isinstance(snapshot, dict) else {}
        character_contract = (
            inline_digests.get("character_contract") if isinstance(inline_digests, dict) else None
        )
        for issue in detect_character_pronoun_drift(content, character_contract):
            issues.append({**issue, "source": "deterministic"})
        listing = detect_mechanical_required_beat_listing(
            content=content,
            must_include_text=scene.must_include_text,
        )
        if listing is not None:
            issues.append({**listing, "source": "deterministic"})

        event_warning: dict[str, Any] | None = None
        try:
            from novel_system.services.narrative_event_log import NarrativeEventLog

            project_id = require_scene_project_id(self.session, scene)
            report = NarrativeEventLog(self.session).check_consistency(
                content,
                project_id,
                scene.scene_id,
                character_ids=scene.onstage_chars_json or [],
            )
            for violation in report.violations:
                source = getattr(violation, "source", "keyword")
                issues.append(
                    {
                        "issue_key": (
                            "event_log_consistency_violation"
                            if source == "keyword"
                            else "event_log_consistency_llm_flag"
                        ),
                        "message": (
                            f"Event log contradiction: {violation.entity_id}.{violation.fact_key} "
                            f"expected '{violation.expected}' but text suggests '{violation.actual}'"
                        ),
                        "source": "deterministic" if source == "keyword" else "llm_advisory",
                        "details": {
                            "entity_id": violation.entity_id,
                            "fact_key": violation.fact_key,
                            "expected": violation.expected,
                            "actual": violation.actual,
                            "evidence": violation.evidence,
                            "source": source,
                        },
                    }
                )
        except Exception as exc:  # noqa: BLE001 - no deterministic evidence means no Q1 claim
            event_warning = {
                "issue_key": "continuity_validation_unavailable",
                "quality_level": "Q2",
                "blocking": False,
                "message": f"Narrative continuity validation unavailable ({type(exc).__name__}).",
            }

        classified = classify_issues(issues, scene=scene, content=content)
        blocked = blocking_issues(classified)
        warnings = [item for item in classified if not item.get("blocking")]
        waiver: dict[str, str] | None = None
        if blocked and allow_author_waiver:
            # Q1 is "author confirm or revise", not an absolute safety embargo.
            # Reuse the existing exact-content waiver contract so a previously
            # accepted soft-QC risk cannot be invalidated at the archive boundary.
            from novel_system.services.human_review_manager import HumanReviewManager

            waiver = HumanReviewManager(self.session).accepted_soft_risk_waiver(
                scene_id=scene.scene_id,
                trigger_reason="blocking_soft_qc_issue",
                source_draft_content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
            if waiver is not None:
                classified = [
                    (
                        {
                            **item,
                            "blocking": False,
                            "waived": True,
                            "waiver_event_id": waiver["event_id"],
                            "recommended_action": "author_risk_accepted",
                        }
                        if item.get("blocking")
                        else item
                    )
                    for item in classified
                ]
                warnings = [item for item in classified if not item.get("blocking")]
                blocked = []
        if event_warning is not None:
            warnings.append(event_warning)
        return {
            "issues": classified,
            "blocking_issues": blocked,
            "blockers": [f"continuity:{item.get('issue_key') or 'unknown'}" for item in blocked],
            "warnings": warnings,
            "waiver": waiver,
        }

    def _longform_contract(
        self,
        scene: SceneCard | None,
        content: str,
        bundle: SceneBundle | None,
        *,
        bundle_integrity: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Verify the machine-checkable subset of the frozen chapter contract.

        Natural-language story constraints are not reliably decidable with a
        substring heuristic.  Only constraints carrying ``check_terms`` (or an
        explicit required-text kind) can block.  Everything else is surfaced as
        human verification work, preserving honesty and avoiding false Q1 claims.
        """

        empty = {
            "available": False,
            "contract_id": None,
            "contract_status": None,
            "provenance": {"anchor_refs": [], "source_bundle_id": bundle.bundle_id if bundle else None},
            "checks": [],
            "key_hits": [],
            "waivers": [],
            "unresolved": [],
            "blockers": [],
            "warnings": [],
            "bundle_integrity": bundle_integrity,
        }
        if bundle is None:
            return empty
        snapshot = bundle.frozen_snapshot_json if isinstance(bundle.frozen_snapshot_json, dict) else {}
        inline = snapshot.get("inline_digests") if isinstance(snapshot, dict) else None
        if bundle_integrity is None or not bundle_integrity["valid"]:
            issue = {
                "issue_key": "longform_contract_bundle_integrity_failed",
                "quality_level": "Q1",
                "blocking": True,
                "message": "Frozen long-form contract no longer matches its bundle hash.",
                "details": bundle_integrity,
            }
            return {
                **empty,
                "unresolved": [issue],
                "blockers": [
                    f"longform_contract:{bundle_integrity['error_code']}"
                ],
                "bundle_integrity": bundle_integrity,
            }
        if not isinstance(inline, dict) or "chapter_contract" not in inline:
            return empty
        try:
            contract = self._json_digest(inline.get("chapter_contract"), expected=dict)
            anchors = self._json_digest(inline.get("longform_anchors", "[]"), expected=list)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            warning = {
                "issue_key": "longform_contract_validation_unavailable",
                "quality_level": "Q1",
                "blocking": True,
                "message": f"Frozen long-form contract could not be decoded ({type(exc).__name__}).",
            }
            return {
                **empty,
                "available": False,
                "unresolved": [warning],
                "blockers": ["longform_contract:validation_unavailable"],
                "warnings": [],
                "bundle_integrity": bundle_integrity,
            }

        contract_id = str(contract.get("contract_id") or "unknown")
        anchor_by_id = {
            str(item.get("anchor_id")): item
            for item in anchors
            if isinstance(item, dict) and item.get("anchor_id")
        }
        checks: list[dict[str, Any]] = []
        blockers: list[str] = []
        warnings: list[dict[str, Any]] = []
        key_hits: list[dict[str, Any]] = []
        waivers: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        normalized_content = content.casefold()
        raw_constraints = contract.get("constraints")
        constraints = raw_constraints if isinstance(raw_constraints, list) else []
        for index, item in enumerate(constraints, start=1):
            if not isinstance(item, dict):
                continue
            constraint_ref = str(item.get("constraint_id") or f"{contract_id}:{index}")
            target_scene_id = str(item.get("scene_id") or "").strip() or None
            if target_scene_id and (scene is None or target_scene_id != scene.scene_id):
                checks.append(
                    {
                        "constraint_ref": constraint_ref,
                        "status": "not_applicable",
                        "target_scene_id": target_scene_id,
                    }
                )
                continue
            text = str(item.get("text") or "").strip()
            kind = str(item.get("kind") or "constraint").strip().lower()
            enforcement = str(item.get("enforcement") or "advisory").strip().lower()
            if enforcement not in {"advisory", "blocking"}:
                enforcement = "advisory"
            match_mode = str(item.get("match_mode") or "any").strip().lower()
            if match_mode not in {"any", "all"}:
                match_mode = "any"
            terms = [
                str(value or "").strip()
                for value in (item.get("check_terms") or [])
                if str(value or "").strip()
            ] if isinstance(item.get("check_terms") or [], list) else []
            if not terms and kind in {"must_include", "required_text", "exact_text"} and text:
                terms = [text]
            anchor_id = str(item.get("anchor_id") or "").strip() or None
            anchor = anchor_by_id.get(anchor_id) if anchor_id else None
            base = {
                "constraint_ref": constraint_ref,
                "text": text,
                "kind": kind,
                "enforcement": enforcement,
                "match_mode": match_mode,
                "check_terms": terms,
                "anchor_id": anchor_id,
                "anchor_source_ref": anchor.get("source_ref") if isinstance(anchor, dict) else None,
            }
            waived = item.get("waived") is True
            waiver_reason = str(item.get("waiver_reason") or "").strip()
            waiver_actor_ref = str(item.get("waiver_actor_ref") or "").strip()
            waived_at = str(item.get("waived_at") or "").strip()
            if waived and waiver_reason and waiver_actor_ref and waived_at:
                record = {
                    **base,
                    "status": "waived",
                    "waiver_reason": waiver_reason,
                    "waiver_actor_ref": waiver_actor_ref,
                    "waived_at": waived_at,
                }
                checks.append(record)
                waivers.append(record)
                continue
            if waived:
                record = {
                    **base,
                    "status": "waiver_invalid",
                    "waiver_reason": waiver_reason or None,
                    "waiver_actor_ref": waiver_actor_ref or None,
                    "waived_at": waived_at or None,
                }
                checks.append(record)
                unresolved.append(record)
                if enforcement == "blocking":
                    blockers.append(
                        f"longform_contract:{constraint_ref}:waiver_invalid"
                    )
                else:
                    warnings.append(
                        {
                            "issue_key": "longform_contract_waiver_invalid",
                            "quality_level": "Q2",
                            "blocking": False,
                            "constraint_ref": constraint_ref,
                            "message": "Contract waiver is missing its reason, actor, or timestamp.",
                        }
                    )
                continue
            if anchor_id and anchor is None:
                record = {**base, "status": "provenance_missing"}
                checks.append(record)
                unresolved.append(record)
                if enforcement == "blocking":
                    blockers.append(f"longform_contract:{constraint_ref}:provenance_missing")
                else:
                    warnings.append(
                        {
                            "issue_key": "longform_contract_provenance_missing",
                            "quality_level": "Q2",
                            "blocking": False,
                            "constraint_ref": constraint_ref,
                            "message": "Contract constraint references an anchor absent from the frozen bundle.",
                        }
                    )
                continue
            if not terms:
                record = {**base, "status": "human_verification_required"}
                checks.append(record)
                unresolved.append(record)
                warnings.append(
                    {
                        "issue_key": "longform_contract_human_verification_required",
                        "quality_level": "Q2",
                        "blocking": False,
                        "constraint_ref": constraint_ref,
                        "message": "Natural-language chapter constraint needs author/editor verification.",
                    }
                )
                continue
            term_hits = [term for term in terms if term.casefold() in normalized_content]
            satisfied = len(term_hits) == len(terms) if match_mode == "all" else bool(term_hits)
            status = "hit" if satisfied else "missing"
            record = {**base, "status": status, "matched_terms": term_hits}
            checks.append(record)
            if satisfied:
                key_hits.append(record)
                continue
            unresolved.append(record)
            if enforcement == "blocking":
                blockers.append(f"longform_contract:{constraint_ref}:missing")
            else:
                warnings.append(
                    {
                        "issue_key": "longform_contract_advisory_miss",
                        "quality_level": "Q2",
                        "blocking": False,
                        "constraint_ref": constraint_ref,
                        "message": "Advisory chapter-contract cue was not found in the final text.",
                    }
                )

        return {
            "available": True,
            "contract_id": contract_id,
            "contract_status": contract.get("status"),
            "provenance": {
                "source_bundle_id": bundle.bundle_id,
                "anchor_refs": [
                    {
                        "anchor_id": anchor_id,
                        "status": item.get("status"),
                        "source_ref": item.get("source_ref"),
                        "updated_at": item.get("updated_at"),
                    }
                    for anchor_id, item in anchor_by_id.items()
                ],
            },
            "checks": checks,
            "key_hits": key_hits,
            "waivers": waivers,
            "unresolved": unresolved,
            "blockers": list(dict.fromkeys(blockers)),
            "warnings": warnings,
            "bundle_integrity": bundle_integrity,
        }

    @staticmethod
    def _json_digest(value: Any, *, expected: type) -> Any:
        decoded = json.loads(value) if isinstance(value, str) else value
        if not isinstance(decoded, expected):
            raise TypeError(f"expected {expected.__name__} digest")
        return decoded

    def _literary(self, scene: SceneCard | None, content: str) -> dict[str, Any]:
        try:
            signals, findings = analyze_literary_quality(content)
            weights = get_dimension_weights(scene.project_id if scene is not None else None, self.session)
            if not weights:
                weights = dict(DIMENSION_WEIGHTS)
            overall_score = round(
                sum(
                    float(signals[dimension].get("score", 1.0)) * float(weights.get(dimension, 0.0))
                    for dimension in QUALITY_DIMENSIONS
                ),
                4,
            )
            core_weight = sum(float(weights.get(dimension, 0.0)) for dimension in _CHARACTER_SCENE_CORE_DIMENSIONS)
            character_scene_core = (
                round(
                    sum(
                        float(signals[dimension].get("score", 1.0)) * float(weights.get(dimension, 0.0))
                        for dimension in _CHARACTER_SCENE_CORE_DIMENSIONS
                    )
                    / core_weight,
                    4,
                )
                if core_weight > 0
                else overall_score
            )
            scores = {
                "character_scene_core": character_scene_core,
                "ending_drive": round(float(signals["ending_drive"].get("score", 1.0)), 4),
                "choice_pressure": round(float(signals["choice_pressure"].get("score", 1.0)), 4),
            }
            promotion_blockers: list[str] = []
            if scores["character_scene_core"] < CHARACTER_SCENE_CORE_MIN:
                promotion_blockers.append("literary:character_scene_core")
            if scores["ending_drive"] < ENDING_DRIVE_MIN:
                promotion_blockers.append("literary:ending_drive")
            if scores["choice_pressure"] < CHOICE_PRESSURE_MIN:
                promotion_blockers.append("literary:choice_pressure")
            risky_dimensions = [
                dimension for dimension, signal in signals.items() if bool(signal.get("risk"))
            ]
            warnings = [
                {
                    "issue_key": f"literary:{dimension}",
                    "quality_level": "Q3",
                    "blocking": False,
                    "message": str(signals[dimension].get("evidence") or dimension),
                }
                for dimension in risky_dimensions
            ]
            return {
                "available": True,
                "overall_score": overall_score,
                "scores": scores,
                "thresholds": {
                    "character_scene_core_min": CHARACTER_SCENE_CORE_MIN,
                    "ending_drive_min": ENDING_DRIVE_MIN,
                    "choice_pressure_min": CHOICE_PRESSURE_MIN,
                },
                "signals": signals,
                "risky_dimensions": risky_dimensions,
                "findings": findings,
                "promotion_blockers": promotion_blockers,
                "warnings": warnings,
            }
        except Exception as exc:  # noqa: BLE001 - delivery survives, strong auto-promotion does not
            warning = {
                "issue_key": "literary_validation_unavailable",
                "quality_level": "Q2",
                "blocking": False,
                "message": f"Literary validation unavailable ({type(exc).__name__}).",
            }
            return {
                "available": False,
                "overall_score": None,
                "scores": {
                    "character_scene_core": 0.0,
                    "ending_drive": 0.0,
                    "choice_pressure": 0.0,
                },
                "thresholds": {
                    "character_scene_core_min": CHARACTER_SCENE_CORE_MIN,
                    "ending_drive_min": ENDING_DRIVE_MIN,
                    "choice_pressure_min": CHOICE_PRESSURE_MIN,
                },
                "signals": {},
                "risky_dimensions": [],
                "findings": [],
                "promotion_blockers": ["literary:validation_unavailable"],
                "warnings": [warning],
            }
