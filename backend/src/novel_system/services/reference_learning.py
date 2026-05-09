from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from novel_system.db.models import (
    LlmCall,
    ReferenceBook,
    ReferenceBookSegment,
    ReferenceFinding,
    ReferenceLearningRound,
    ReferenceLearningRun,
    ReferenceProfile,
    ReviewItem,
)
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.llm_client import LLMClient, LLMConfigurationError, LLMRequest, load_model_routing_config
from novel_system.services.prompt_builder import PromptConfigurationError, load_prompt_templates
from novel_system.services.style_profile import StyleProfileService
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.services.versioning.shared import now_iso
from novel_system.settings import get_settings

SUPPORTED_ANALYSIS_FOCUS = {"style_structure"}
SUPPORTED_CLOUD_POLICIES = {"allow_full_cloud", "segments_only", "local_only"}
PROFILE_STATUS_READY = "ready"
PROFILE_STATUS_STALE = "stale"
ROUND_FINDING_TYPES = (
    "style_rule_set",
    "style_observation",
    "narrative_pattern",
    "banned_rule_cluster",
    "calibration_candidate",
    "style_rule_set",
    "narrative_pattern",
    "style_observation",
)
DIMENSIONS = (
    "rhythm",
    "imagery",
    "chapter hook",
    "banned move",
    "calibration",
    "syntax",
    "conflict escalation",
    "dialogue ratio",
)
SEGMENT_KIND_LABELS = {
    "opening": "开篇片段",
    "dialogue": "对话片段",
    "imagery": "意象片段",
    "action": "动作片段",
    "emotion": "情绪片段",
    "structure": "结构片段",
    "closing": "结尾片段",
    "boilerplate": "站点声明片段",
    "reference": "参考片段",
}
DIMENSION_LABELS = {
    "rhythm": "节奏",
    "imagery": "意象",
    "chapter hook": "章节钩子",
    "banned move": "禁复刻点",
    "calibration": "校准",
    "syntax": "句法",
    "conflict escalation": "冲突升级",
    "dialogue ratio": "对话比例",
}
BOILERPLATE_MARKERS = (
    "txt8080",
    "八零电子书",
    "本站",
    "用户上传",
    "存储空间",
    "TXT全集电子书",
    "免费下载",
    "仅供试读",
    "请支持正版",
    "版权",
    "www.",
    "http://",
    "https://",
)
PROFILE_EVIDENCE_LABEL_RE = re.compile(
    r"\s*Evidence(?:\s+(?:pattern|risk\s+checked\s+from))?:.*$",
    flags=re.IGNORECASE | re.DOTALL,
)
PROFILE_BLOCKED_MARKERS = (
    "Evidence:",
    "Evidence pattern:",
    "Evidence risk checked from:",
    "txt8080",
    "声明：本书",
    "八零电子书",
    "用户上传",
    "本站",
    "版权",
    "路明非",
    "路鸣泽",
    "楚子航",
    "卡塞尔",
    "江南",
    "龙族",
    "绘梨衣",
    "恺撒",
    "诺玛",
    "源氏重工",
    "蛇岐八家",
    "dragon",
    "Japanese branch",
    "Soviet",
    "roller coaster",
    "deep-sea",
    "mythical peril",
    "mysterious letter",
    "rain, cold, fog",
    "frozen landscapes",
    "entertainers",
    "lonely George",
    "路明非",
    "楚子航",
    "卡塞尔",
    "龙族",
    "江南",
)
PROFILE_MAX_SAFE_STRING_CHARS = 320


class ReferenceLearningService:
    def __init__(self, session: Session, *, llm_client: Any | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self._llm_client = llm_client
        self._routing_config_cache: Any | None = None
        self._prompt_templates_cache: dict[str, Any] | None = None

    def import_path(
        self,
        *,
        file_path: str,
        title: str | None,
        author_label: str | None,
        cloud_policy: str,
        analysis_focus: str = "style_structure",
    ) -> dict[str, Any]:
        if _looks_like_url(file_path):
            raise DomainError(
                "REFERENCE_BOOK_PATH_UNSUPPORTED",
                "reference book path must be a local TXT or MD file",
                status_code=400,
            )
        path = Path(file_path).expanduser()
        if not path.exists() or not path.is_file():
            raise DomainError("REFERENCE_BOOK_NOT_FOUND", f"reference book file not found: {file_path}", status_code=404)
        return self.import_bytes(
            raw_bytes=path.read_bytes(),
            file_name=path.name,
            title=title or path.stem,
            author_label=author_label,
            source_kind="path",
            source_path=str(path),
            cloud_policy=cloud_policy,
            analysis_focus=analysis_focus,
        )

    def import_bytes(
        self,
        *,
        raw_bytes: bytes,
        file_name: str | None,
        title: str | None,
        author_label: str | None,
        source_kind: str,
        source_path: str | None = None,
        cloud_policy: str,
        analysis_focus: str = "style_structure",
    ) -> dict[str, Any]:
        _validate_policy(cloud_policy=cloud_policy, analysis_focus=analysis_focus)
        suffix = Path(file_name or "reference.txt").suffix.lower()
        if suffix and suffix not in {".txt", ".md", ".markdown"}:
            raise DomainError("REFERENCE_BOOK_FORMAT_UNSUPPORTED", "only TXT and MD reference books are supported", status_code=400)

        text = _decode_text(raw_bytes)
        normalized = _normalize_text(text)
        if not normalized:
            raise DomainError("REFERENCE_BOOK_EMPTY", "reference book text is empty", status_code=400)

        checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        book_id = f"refbook_{checksum[:12]}"
        segments = _segment_book(normalized, book_id=book_id)
        if not segments:
            raise DomainError("REFERENCE_BOOK_EMPTY", "reference book text is empty after segmentation", status_code=400)

        now = now_iso()
        stats = _segment_stats(segments, total_chars=len(normalized))
        book = self.session.get(ReferenceBook, book_id)
        if book is None:
            book = ReferenceBook(
                book_id=book_id,
                title=(title or file_name or book_id).strip(),
                author_label=_optional_text(author_label),
                source_kind=source_kind,
                source_path=source_path,
                file_name=file_name,
                cloud_policy=cloud_policy,
                analysis_focus=analysis_focus,
                text_checksum=checksum,
                status="imported",
                total_chars=len(normalized),
                total_segments=len(segments),
                stats_json=stats,
                created_at=now,
                updated_at=now,
            )
            self.session.add(book)
        else:
            book.title = (title or book.title).strip()
            book.author_label = _optional_text(author_label)
            book.source_kind = source_kind
            book.source_path = source_path
            book.file_name = file_name
            book.cloud_policy = cloud_policy
            book.analysis_focus = analysis_focus
            book.status = "imported"
            book.total_chars = len(normalized)
            book.total_segments = len(segments)
            book.stats_json = stats

        existing_segments = self.session.execute(
            select(ReferenceBookSegment).where(ReferenceBookSegment.book_id == book_id)
        ).scalars().all()
        for segment in existing_segments:
            self.session.delete(segment)
        self.session.flush()
        for segment in segments:
            self.session.add(segment)
        self.session.flush()

        return {"book_id": book.book_id, "book": self.serialize_book(book), "stats": stats}

    def list_books(self) -> dict[str, Any]:
        books = self.session.execute(select(ReferenceBook).order_by(ReferenceBook.created_at.desc())).scalars().all()
        for book in books:
            self._sync_profiles_for_book(book.book_id)
        return {"items": [self.serialize_book_with_summary(book) for book in books]}

    def detail(self, book_id: str) -> dict[str, Any]:
        book = self._book(book_id)
        self._sync_profiles_for_book(book_id)
        learning_tree_summary = self.learning_tree_summary(book_id)
        return {
            "book": self.serialize_book(book),
            "stats": dict(book.stats_json or {}),
            "coverage": self.coverage_for_book(book_id),
            "latest_run": self._latest_run_payload(book_id),
            "latest_round": self._latest_round_payload(book_id),
            "profiles": [self.serialize_profile(profile) for profile in self._profiles_for_book(book_id)],
            "learning_tree_summary": learning_tree_summary,
        }

    def learning_tree(self, book_id: str) -> dict[str, Any]:
        book = self._book(book_id)
        self._sync_profiles_for_book(book_id)
        runs = self._runs_for_book(book_id)
        profiles = self._profiles_for_book(book_id)
        run_payloads: list[dict[str, Any]] = []
        review_decisions: list[dict[str, Any]] = []
        finding_count = 0
        round_count = 0
        for run in runs:
            round_payloads = [self.serialize_round(round_row) for round_row in self._rounds_for_run(run.run_id)]
            for round_payload in round_payloads:
                findings = round_payload.get("findings") or []
                finding_count += len(findings)
                review_decisions.extend(
                    finding["review"]
                    for finding in findings
                    if isinstance(finding, dict) and isinstance(finding.get("review"), dict)
                )
            run_payload = self.serialize_run(run)
            run_payload["rounds"] = round_payloads
            run_payloads.append(run_payload)
            round_count += len(round_payloads)
        profile_payloads = [self.serialize_profile(profile) for profile in profiles]
        apply_reviews = self._apply_reviews_for_profiles(profiles)
        active_knowledge_refs = self._active_knowledge_refs_from_reviews(apply_reviews)
        summary = self._learning_tree_summary(
            runs=runs,
            round_count=round_count,
            finding_count=finding_count,
            review_decisions=review_decisions,
            profiles=profiles,
            apply_reviews=apply_reviews,
            active_knowledge_refs=active_knowledge_refs,
        )
        return {
            "book": self.serialize_book(book),
            "summary": summary,
            "runs": run_payloads,
            "review_decisions": review_decisions,
            "profiles": profile_payloads,
            "apply_reviews": apply_reviews,
            "active_knowledge_refs": active_knowledge_refs,
        }

    def learning_tree_summary(self, book_id: str) -> dict[str, Any]:
        tree = self.learning_tree(book_id)
        return dict(tree["summary"])

    def start_run(self, book_id: str, *, batch_size: int = 8) -> dict[str, Any]:
        book = self._book(book_id)
        batch = max(5, min(int(batch_size or 8), 8))
        run_id = f"refrun_{book_id}_{_short_hash(now_iso())}"
        run = ReferenceLearningRun(
            run_id=run_id,
            book_id=book_id,
            status="running",
            batch_size=batch,
            coverage_json=self.coverage_for_book(book_id),
        )
        book.status = "learning"
        self.session.add(run)
        self.session.flush()
        return {"run": self.serialize_run(run)}

    def advance_run(self, book_id: str, run_id: str) -> dict[str, Any]:
        self._book(book_id)
        run = self._run(book_id, run_id)
        self._sync_findings(run_id)

        pending_round = self._pending_round(run_id)
        if pending_round is not None:
            run.status = "waiting_review"
            run.coverage_json = self.coverage_for_run(run_id)
            return {"run": self.serialize_run(run), "round": self.serialize_round(pending_round)}

        coverage = self.coverage_for_run(run_id)
        profile: ReferenceProfile | None = None
        if coverage.get("ready"):
            profile = self._ensure_profile(book_id, run, coverage)
            run.profile_id = profile.profile_id
            coverage = self.coverage_for_run(run_id)

        if _coverage_complete(coverage):
            profile = profile or self._ensure_profile(book_id, run, coverage)
            run.status = "completed"
            run.profile_id = profile.profile_id
            run.coverage_json = coverage
            self._book(book_id).status = "completed"
            self.session.flush()
            return {"run": self.serialize_run(run), "profile": self.serialize_profile(profile)}

        round_payload = self._create_round(book_id, run)
        if "profile" in round_payload:
            run.status = "completed"
            if round_payload["profile"].get("profile_id"):
                run.profile_id = round_payload["profile"]["profile_id"]
            run.coverage_json = self.coverage_for_run(run_id)
            self._book(book_id).status = "completed"
            self.session.flush()
            return {"run": self.serialize_run(run), "profile": round_payload["profile"]}
        run.status = "waiting_review"
        run.coverage_json = self.coverage_for_run(run_id)
        self.session.flush()
        return {"run": self.serialize_run(run), "round": round_payload}

    def apply_profile(self, book_id: str, profile_id: str, *, scope: str, scope_ref_id: str | None) -> dict[str, Any]:
        self._book(book_id)
        self._sync_profiles_for_book(book_id)
        profile = self.session.get(ReferenceProfile, profile_id)
        if profile is None or profile.book_id != book_id:
            raise DomainError("REFERENCE_PROFILE_NOT_FOUND", f"profile {profile_id} not found", status_code=404)
        safety_summary = _profile_safety_summary(profile.profile_json, stripped_count=_profile_stripped_count(profile))
        approved_finding_ids = [finding.finding_id for finding in self._approved_findings(profile.run_id)]
        if profile.status != PROFILE_STATUS_READY or not safety_summary["safe"] or profile.source_finding_ids_json != approved_finding_ids:
            profile.status = PROFILE_STATUS_STALE
            profile.coverage_json = {
                **dict(profile.coverage_json or {}),
                "profile_stale": True,
                "safety_summary": safety_summary,
            }
            self.session.flush()
            raise DomainError(
                "REFERENCE_PROFILE_STALE",
                "reference profile is stale or unsafe; regenerate it before applying",
                status_code=409,
                details={
                    "profile_id": profile.profile_id,
                    "status": profile.status,
                    "safety_summary": safety_summary,
                },
            )
        if scope not in {"global", "chapter", "scene"}:
            raise DomainError("REFERENCE_PROFILE_SCOPE_INVALID", "scope must be global, chapter, or scene", status_code=400)
        resolved_scope_ref = "global" if scope == "global" else _required_text(scope_ref_id, field="scope_ref_id")
        profile_payload = dict(profile.profile_json or {})
        application_guidance = _reference_application_guidance(profile_payload, scope=scope, scope_ref_id=resolved_scope_ref)
        review_specs = self._profile_review_specs(
            profile,
            profile_payload,
            scope=scope,
            scope_ref_id=resolved_scope_ref,
            application_guidance=application_guidance,
        )
        reviews: list[ReviewItem] = []
        for spec in review_specs:
            review = self._upsert_review(**spec)
            reviews.append(review)
        self.session.flush()
        return {
            "profile_id": profile.profile_id,
            "book_id": book_id,
            "applied": False,
            "application_guidance": application_guidance,
            "application_status": self._application_status_for_reviews(reviews),
            "reviews": [self.serialize_review(review) for review in reviews],
        }

    def segment_excerpt(self, book_id: str, segment_id: str, *, max_chars: int = 800) -> dict[str, Any]:
        self._book(book_id)
        segment = self.session.get(ReferenceBookSegment, segment_id)
        if segment is None or segment.book_id != book_id:
            raise DomainError("REFERENCE_SEGMENT_NOT_FOUND", f"reference segment {segment_id} not found", status_code=404)
        if _is_non_evidence_segment(segment):
            raise DomainError(
                "REFERENCE_SEGMENT_EXCERPT_UNAVAILABLE",
                "source excerpt is not available for boilerplate or copyright-noise segments",
                status_code=404,
            )
        limit = max(1, min(int(max_chars or 800), 800))
        return {
            "segment_id": segment.segment_id,
            "display_label": _segment_display_label(segment),
            "excerpt": _preview(segment.text, limit=limit),
            "max_chars": limit,
            "source_visibility": "review_only",
            "safety_note": "仅供审核，不进入生成链路；不会写入画像、bundle 或模型 prompt。",
        }

    def _create_round(self, book_id: str, run: ReferenceLearningRun) -> dict[str, Any]:
        segments = self._select_segments(book_id, run)
        if not segments:
            profile = self._ensure_profile(book_id, run, self.coverage_for_run(run.run_id))
            run.status = "completed"
            run.profile_id = profile.profile_id
            return {"profile": self.serialize_profile(profile)}

        round_index = run.round_count + 1
        round_id = f"refround_{run.run_id}_{round_index}"
        existing_round = self.session.get(ReferenceLearningRound, round_id)
        if existing_round is not None:
            return self.serialize_round(existing_round)
        round_row = ReferenceLearningRound(
            round_id=round_id,
            book_id=book_id,
            run_id=run.run_id,
            round_index=round_index,
            status="waiting_review",
            segment_ids_json=[segment.segment_id for segment in segments],
        )
        self.session.add(round_row)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            existing_round = self.session.get(ReferenceLearningRound, round_id)
            if existing_round is None:
                raise
            return self.serialize_round(existing_round)

        finding_ids: list[str] = []
        for index, segment in enumerate(segments):
            finding, review = self._create_finding(book_id, run, round_row, segment, index)
            finding_ids.append(finding.finding_id)
            segment.selected_count += 1
            self.session.add(review)
            self.session.add(finding)
        round_row.finding_ids_json = finding_ids
        run.round_count = round_index
        self.session.flush()
        return self.serialize_round(round_row)

    def _create_finding(
        self,
        book_id: str,
        run: ReferenceLearningRun,
        round_row: ReferenceLearningRound,
        segment: ReferenceBookSegment,
        index: int,
    ) -> tuple[ReferenceFinding, ReviewItem]:
        book = self._book(book_id)
        llm_finding = self._extract_finding_with_llm(book, run, round_row, segment, index)
        finding_type = llm_finding.get("finding_type") or ROUND_FINDING_TYPES[index % len(ROUND_FINDING_TYPES)]
        dimension = llm_finding.get("dimension") or DIMENSIONS[index % len(DIMENSIONS)]
        finding_id = f"reffind_{round_row.round_id}_{index + 1}"
        review_id = f"review_{finding_id}"
        raw_summary = llm_finding.get("summary") or _finding_summary(
            finding_type=finding_type,
            dimension=dimension,
            segment=segment,
        )
        summary, summary_notes = _sanitize_reference_finding_text(raw_summary)
        summary = _localize_reference_finding_summary(
            summary,
            finding_type=finding_type,
            dimension=dimension,
            segment=segment,
            book=book,
        )
        raw_payload_extra = llm_finding.get("payload_extra")
        if not isinstance(raw_payload_extra, dict):
            raw_payload_extra = {}
        payload_extra, payload_notes = _sanitize_reference_finding_payload_extra(raw_payload_extra)
        safety_notes = _merge_reference_safety_notes(summary_notes, payload_notes)
        payload = {
            "lineage_key": f"{_safe_key(book_id)}_{round_row.round_index}_{index + 1}_{finding_type}",
            "text": summary,
            "scope": "global",
            "scope_ref_id": "global",
            "source": "reference_book_learning",
            "reference_book_id": book_id,
            "reference_segment_id": segment.segment_id,
            "dimension": dimension,
            **payload_extra,
            "safety_notes": safety_notes,
        }
        review = self._upsert_review(
            review_id=review_id,
            item_type=finding_type,
            candidate_text=summary,
            candidate_payload_json=payload,
            active_on_approve=0,
        )
        finding = ReferenceFinding(
            finding_id=finding_id,
            book_id=book_id,
            run_id=run.run_id,
            round_id=round_row.round_id,
            segment_id=segment.segment_id,
            review_id=review_id,
            finding_type=finding_type,
            dimension=dimension,
            summary=summary,
            evidence_preview=_preview(segment.text),
            candidate_payload_json=payload,
            status="pending",
        )
        return finding, review

    def _upsert_review(
        self,
        *,
        review_id: str,
        item_type: str,
        candidate_text: str,
        candidate_payload_json: dict[str, Any],
        active_on_approve: int,
    ) -> ReviewItem:
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            review = ReviewItem(
                review_id=review_id,
                item_type=item_type,
                status="pending",
                candidate_text=candidate_text,
                candidate_payload_json=candidate_payload_json,
                active_on_approve=active_on_approve,
            )
            self.session.add(review)
        else:
            review.item_type = item_type
            review.status = "pending"
            review.candidate_text = candidate_text
            review.candidate_payload_json = candidate_payload_json
            review.active_on_approve = active_on_approve
            review.materialize_status = "pending"
            review.approved_item_row_id = None
            review.approved_item_id = None
        return review

    def _profile_review_specs(
        self,
        profile: ReferenceProfile,
        profile_payload: dict[str, Any],
        *,
        scope: str,
        scope_ref_id: str,
        application_guidance: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        style_profile = profile_payload.get("style_profile") if isinstance(profile_payload.get("style_profile"), dict) else {}
        style_text = StyleProfileService.render_profile_yaml(style_profile)
        narrative_patterns = profile_payload.get("narrative_patterns")
        narrative_text = "\n".join(str(item) for item in narrative_patterns if str(item).strip()) if isinstance(narrative_patterns, list) else ""
        narrative_text = narrative_text or "Use chapter hook escalation, delayed explanation, and consequence-first scene turns."
        prefix = _safe_key(profile.profile_id)
        application_guidance = application_guidance or _reference_application_guidance(profile_payload, scope=scope, scope_ref_id=scope_ref_id)
        return [
            {
                "review_id": f"review_apply_{prefix}_style_{scope}_{_safe_key(scope_ref_id)}",
                "item_type": "style_rule_set",
                "candidate_text": style_text,
                "candidate_payload_json": {
                    "lineage_key": f"REF_STYLE_{prefix}_{scope}_{_safe_key(scope_ref_id)}",
                    "text": style_text,
                    "scope": scope,
                    "scope_ref_id": scope_ref_id,
                    "source": "reference_profile_apply",
                    "reference_profile_id": profile.profile_id,
                    "style_profile": style_profile,
                    "application_guidance": application_guidance,
                },
                "active_on_approve": 0,
            },
            {
                "review_id": f"review_apply_{prefix}_narrative_{scope}_{_safe_key(scope_ref_id)}",
                "item_type": "narrative_pattern",
                "candidate_text": narrative_text,
                "candidate_payload_json": {
                    "lineage_key": f"REF_NARRATIVE_{prefix}_{scope}_{_safe_key(scope_ref_id)}",
                    "text": narrative_text,
                    "scope": scope,
                    "scope_ref_id": scope_ref_id,
                    "source": "reference_profile_apply",
                    "reference_profile_id": profile.profile_id,
                    "application_guidance": application_guidance,
                },
                "active_on_approve": 0,
            },
        ]

    def _ensure_profile(self, book_id: str, run: ReferenceLearningRun, coverage: dict[str, Any]) -> ReferenceProfile:
        self._sync_profiles_for_run(run.run_id)

        findings = self._approved_findings(run.run_id)
        approved_finding_ids = [finding.finding_id for finding in findings]
        existing_profiles = self.session.execute(
            select(ReferenceProfile).where(ReferenceProfile.run_id == run.run_id).order_by(ReferenceProfile.created_at.desc())
        ).scalars().all()
        for existing in existing_profiles:
            safety_summary = _profile_safety_summary(existing.profile_json, stripped_count=_profile_stripped_count(existing))
            if (
                existing.status == PROFILE_STATUS_READY
                and existing.source_finding_ids_json == approved_finding_ids
                and safety_summary["safe"]
            ):
                existing.coverage_json = {
                    **coverage,
                    "profile_ready": True,
                    "profile_stale": False,
                    "safety_summary": safety_summary,
                }
                self.session.flush()
                return existing
            if existing.status == PROFILE_STATUS_READY:
                existing.status = PROFILE_STATUS_STALE
                existing.coverage_json = {
                    **coverage,
                    "profile_ready": False,
                    "profile_stale": True,
                    "safety_summary": safety_summary,
                }

        source_texts = [
            _sanitize_reference_profile_text(finding.summary)[0]
            for finding in findings
            if finding.finding_type in {"style_rule_set", "style_observation"}
        ]
        banned = [
            _sanitize_reference_profile_text(finding.summary)[0]
            for finding in findings
            if finding.finding_type == "banned_rule_cluster"
        ]
        calibration = [
            _sanitize_reference_profile_text(finding.summary)[0]
            for finding in findings
            if finding.finding_type == "calibration_candidate"
        ]
        style_profile = StyleProfileService.build_profile_from_texts(
            sample_texts=source_texts,
            banned_moves=banned,
            calibration_lines=calibration,
        ) or StyleProfileService.build_profile_from_texts(sample_texts=["Use compact pressure beats and tactile imagery."])
        narrative_patterns = [
            _sanitize_reference_profile_text(finding.summary)[0]
            for finding in findings
            if finding.finding_type == "narrative_pattern"
        ] or ["Use chapter hook escalation and delayed explanation before emotional release."]
        book = self._book(book_id)
        llm_profile = self._synthesize_profile_with_llm(book, run, findings, coverage)
        if llm_profile is not None:
            style_profile = llm_profile["style_profile"]
            narrative_patterns = llm_profile["narrative_patterns"]
        profile_payload, safety_summary = _sanitize_reference_profile_payload(
            {
                "style_profile": style_profile,
                "narrative_patterns": narrative_patterns,
                "source": "reference_book_learning",
                "reference_book_id": book_id,
            }
        )
        profile_payload = _enrich_reference_profile_payload(
            profile_payload,
            locale_hint_text="\n".join([book.title, *(finding.summary for finding in findings)]),
            stripped_count=safety_summary["stripped_count"],
        )
        safety_summary = _profile_safety_summary(profile_payload, stripped_count=safety_summary["stripped_count"])
        profile_id = f"refprofile_{book_id}_{_short_hash(f'{run.run_id}:{canonical_json(approved_finding_ids)}')}"
        profile = self.session.get(ReferenceProfile, profile_id)
        if profile is None:
            profile = ReferenceProfile(
                profile_id=profile_id,
                book_id=book_id,
                run_id=run.run_id,
                title=f"{book.title} reference profile",
                status=PROFILE_STATUS_READY,
            )
            self.session.add(profile)
        profile.book_id = book_id
        profile.run_id = run.run_id
        profile.title = f"{book.title} reference profile"
        profile.status = PROFILE_STATUS_READY if safety_summary["safe"] else PROFILE_STATUS_STALE
        profile.profile_json = profile_payload
        profile.coverage_json = {
            **coverage,
            "profile_ready": profile.status == PROFILE_STATUS_READY,
            "profile_stale": profile.status == PROFILE_STATUS_STALE,
            "safety_summary": safety_summary,
        }
        profile.source_finding_ids_json = approved_finding_ids
        self.session.flush()
        return profile

    def _select_segments(self, book_id: str, run: ReferenceLearningRun) -> list[ReferenceBookSegment]:
        attempted_segment_ids = self._attempted_segment_ids_for_book(book_id)
        segments = [
            segment
            for segment in self.session.execute(
                select(ReferenceBookSegment)
                .where(ReferenceBookSegment.book_id == book_id)
                .order_by(ReferenceBookSegment.selected_count.asc(), ReferenceBookSegment.segment_index.asc())
            ).scalars().all()
            if segment.segment_id not in attempted_segment_ids
        ]
        if not segments:
            return []
        analysis_segments = _analysis_worthy_segments(segments)
        if not analysis_segments:
            return []
        ranked_segments = self._rank_segments_with_llm(self._book(book_id), run, analysis_segments)
        if ranked_segments:
            return ranked_segments[: run.batch_size]
        chosen: list[ReferenceBookSegment] = []
        wanted_kinds = ["opening", "dialogue", "imagery", "action", "emotion", "structure", "closing"]
        for kind in wanted_kinds:
            match = next((segment for segment in analysis_segments if segment.segment_kind == kind and segment not in chosen), None)
            if match is not None:
                chosen.append(match)
            if len(chosen) >= run.batch_size:
                return chosen
        for segment in analysis_segments:
            if segment not in chosen:
                chosen.append(segment)
            if len(chosen) >= run.batch_size:
                break
        return chosen

    def _attempted_segment_ids_for_book(self, book_id: str) -> set[str]:
        attempted: set[str] = set()
        rounds = self.session.execute(
            select(ReferenceLearningRound).where(ReferenceLearningRound.book_id == book_id)
        ).scalars().all()
        for round_row in rounds:
            for segment_id in round_row.segment_ids_json or []:
                if segment_id:
                    attempted.add(str(segment_id))
        findings = self.session.execute(
            select(ReferenceFinding).where(ReferenceFinding.book_id == book_id)
        ).scalars().all()
        for finding in findings:
            if finding.segment_id:
                attempted.add(finding.segment_id)
        return attempted

    def _rank_segments_with_llm(
        self,
        book: ReferenceBook,
        run: ReferenceLearningRun,
        segments: list[ReferenceBookSegment],
    ) -> list[ReferenceBookSegment]:
        if not self._llm_allowed(book):
            return []
        payload = {
            "book": {
                "book_id": book.book_id,
                "title": book.title,
                "cloud_policy": book.cloud_policy,
                "analysis_focus": book.analysis_focus,
            },
            "locale_hint": _reference_locale_hint(book=book, segments=segments),
            "batch_size": run.batch_size,
            "segments": [
                {
                    "segment_id": segment.segment_id,
                    "segment_index": segment.segment_index,
                    "segment_kind": segment.segment_kind,
                    "chapter_hint": segment.chapter_hint,
                    "preview": _preview(segment.text, limit=180),
                }
                for segment in segments
            ],
        }
        output = self._call_llm_node("reference_sample_ranker", payload, book=book)
        selections = output.get("selections") if isinstance(output, dict) else None
        if not isinstance(selections, list):
            return []
        by_id = {segment.segment_id: segment for segment in segments}
        chosen: list[ReferenceBookSegment] = []
        for selection in selections:
            if not isinstance(selection, dict):
                continue
            segment_id = selection.get("segment_id")
            segment = by_id.get(segment_id)
            if segment is not None and segment not in chosen:
                chosen.append(segment)
            if len(chosen) >= run.batch_size:
                break
        for segment in segments:
            if len(chosen) >= run.batch_size:
                break
            if segment not in chosen:
                chosen.append(segment)
        return chosen

    def _extract_finding_with_llm(
        self,
        book: ReferenceBook,
        run: ReferenceLearningRun,
        round_row: ReferenceLearningRound,
        segment: ReferenceBookSegment,
        index: int,
    ) -> dict[str, Any]:
        if not self._llm_allowed(book):
            return {}
        fallback_type = ROUND_FINDING_TYPES[index % len(ROUND_FINDING_TYPES)]
        fallback_dimension = DIMENSIONS[index % len(DIMENSIONS)]
        payload = {
            "book": {
                "book_id": book.book_id,
                "title": book.title,
                "cloud_policy": book.cloud_policy,
                "analysis_focus": book.analysis_focus,
            },
            "locale_hint": _reference_locale_hint(book=book, segment=segment),
            "run_id": run.run_id,
            "round_index": round_row.round_index,
            "preferred_item_type": fallback_type,
            "preferred_dimension": fallback_dimension,
            "segment": {
                "segment_id": segment.segment_id,
                "segment_index": segment.segment_index,
                "segment_kind": segment.segment_kind,
                "chapter_hint": segment.chapter_hint,
                "text": segment.text,
            },
            "safety_rule": (
                "Return abstract craft guidance only. Do not copy source long sentences, named entities, "
                "settings, characters, or identifiable scene bridges."
            ),
        }
        output = self._call_llm_node("reference_style_structure_extract", payload, book=book, segment=segment)
        if not isinstance(output, dict):
            return {}
        finding_type = output.get("item_type")
        if finding_type not in set(ROUND_FINDING_TYPES):
            finding_type = fallback_type
        summary = output.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return {}
        dimension = output.get("dimension")
        if not isinstance(dimension, str) or not dimension.strip():
            dimension = fallback_dimension
        return {
            "finding_type": finding_type,
            "dimension": dimension.strip(),
            "summary": summary.strip(),
            "payload_extra": {
                "llm_node_id": "reference_style_structure_extract",
                "transferable_rule": output.get("transferable_rule"),
                "banned_replication_rule": output.get("banned_replication_rule"),
                "confidence": output.get("confidence"),
            },
        }

    def _synthesize_profile_with_llm(
        self,
        book: ReferenceBook,
        run: ReferenceLearningRun,
        findings: list[ReferenceFinding],
        coverage: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not findings or not self._llm_allowed(book):
            return None
        payload = {
            "book": {
                "book_id": book.book_id,
                "title": book.title,
                "cloud_policy": book.cloud_policy,
                "analysis_focus": book.analysis_focus,
            },
            "locale_hint": _detect_locale("\n".join([book.title, *(finding.summary for finding in findings)])),
            "run_id": run.run_id,
            "coverage": coverage,
            "approved_findings": [
                {
                    "finding_id": finding.finding_id,
                    "finding_type": finding.finding_type,
                    "dimension": finding.dimension,
                    "summary": _sanitize_reference_profile_text(finding.summary)[0],
                }
                for finding in findings
            ],
            "safety_rule": (
                "Synthesize only transferable style features, narrative patterns, calibration guidance, "
                "and forbidden replication rules."
            ),
        }
        output = self._call_llm_node("reference_profile_synthesize", payload, book=book)
        if not isinstance(output, dict):
            return None
        style_features = _string_list(output.get("style_features"))
        narrative_patterns = _string_list(output.get("narrative_patterns"))
        banned_rules = _string_list(output.get("banned_replication_rules"))
        calibration = _string_list(output.get("calibration_guidance"))
        if not style_features and not narrative_patterns:
            return None
        style_profile = StyleProfileService.build_profile_from_texts(
            sample_texts=style_features,
            banned_moves=banned_rules,
            calibration_lines=calibration,
        ) or StyleProfileService.build_profile_from_texts(sample_texts=["Use compact pressure beats and tactile imagery."])
        return {
            "title": str(output.get("profile_title") or f"{book.title} reference profile").strip(),
            "style_profile": style_profile,
            "narrative_patterns": narrative_patterns or ["Use chapter hook escalation and delayed explanation before emotional release."],
        }

    def _llm_allowed(self, book: ReferenceBook) -> bool:
        if book.cloud_policy == "local_only":
            return False
        return self._llm_client is not None or bool(self.settings.llm_enabled)

    def _client(self) -> Any:
        if self._llm_client is not None:
            return self._llm_client
        return LLMClient(
            provider=self.settings.llm_provider,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            timeout_seconds=self.settings.llm_timeout_seconds,
            provider_configs=load_llm_provider_runtime_configs(),
        )

    def _call_llm_node(
        self,
        node_id: str,
        payload: dict[str, Any],
        *,
        book: ReferenceBook,
        segment: ReferenceBookSegment | None = None,
    ) -> dict[str, Any]:
        live_mode = bool(self.settings.llm_enabled)
        try:
            task_config = self._task_config(node_id)
            template = self._template(node_id)
        except (KeyError, LLMConfigurationError, PromptConfigurationError) as exc:
            if live_mode:
                raise DomainError(
                    "REFERENCE_LLM_ROUTE_OR_PROMPT_MISSING",
                    f"reference learning LLM node is not configured: {node_id}",
                    status_code=409,
                    details={
                        "node_id": node_id,
                        "error_code": getattr(exc, "code", exc.__class__.__name__),
                        "next_action": "configure_reference_learning_node_route_and_prompt_then_retry",
                    },
                ) from exc
            return {}
        user_prompt = _reference_user_prompt(template.task_prompt, payload)
        prompt_hash = _prompt_hash(
            node_id=node_id,
            template_version=template.version,
            system_prompt=template.system_prompt,
            user_prompt=user_prompt,
            structured_schema=template.structured_schema,
        )
        llm_call_id = f"llm_call_reference_{node_id}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        request = LLMRequest(
            model=task_config.model,
            messages=[
                {"role": "system", "content": template.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=task_config.temperature,
            max_output_tokens=task_config.max_output_tokens,
            response_format=task_config.response_format,
            provider=task_config.provider,
            node_id=node_id,
            provider_id=getattr(task_config, "provider_id", None),
            account_id=getattr(task_config, "account_id", None),
            reasoning_level=getattr(task_config, "reasoning_level", "medium"),
            api_mode=getattr(task_config, "api_mode", "responses"),
            credential_mode=getattr(task_config, "credential_mode", None),
            provider_options=getattr(task_config, "provider_options", {}),
            response_schema=template.structured_schema,
        )
        request_summary = {
            "template_name": node_id,
            "template_version": template.version,
            "payload": _sanitize_llm_payload(payload),
            "response_format": request.response_format,
            "provider": request.provider,
            "provider_id": request.provider_id,
            "account_id": request.account_id,
            "reasoning_level": request.reasoning_level,
            "credential_mode": request.credential_mode,
            "cloud_policy": book.cloud_policy,
            "segment_id": segment.segment_id if segment is not None else None,
        }
        try:
            response = self._client().generate(request)
        except Exception as exc:
            self.session.add(
                LlmCall(
                    llm_call_id=llm_call_id,
                    provider=getattr(task_config, "provider", None),
                    provider_id=getattr(task_config, "provider_id", None),
                    account_id=getattr(task_config, "account_id", None),
                    model=getattr(task_config, "model", None),
                    node_id=node_id,
                    reasoning_level=getattr(task_config, "reasoning_level", None),
                    native_reasoning_json=None,
                    credential_mode=getattr(task_config, "credential_mode", None),
                    prompt_hash=prompt_hash,
                    step=node_id,
                    scene_id=None,
                    chapter_id=None,
                    request_payload_summary=request_summary,
                    response_payload_summary={"error_code": getattr(exc, "code", exc.__class__.__name__), "message": str(exc)},
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                    finish_reason=None,
                    error_code=getattr(exc, "code", exc.__class__.__name__),
                )
            )
            self.session.flush()
            if live_mode:
                raise DomainError(
                    "REFERENCE_LLM_CALL_FAILED",
                    str(exc),
                    status_code=409,
                    details={
                        "llm_call_id": llm_call_id,
                        "node_id": node_id,
                        "error_code": getattr(exc, "code", exc.__class__.__name__),
                        "next_action": "check_provider_route_model_and_retry",
                        "response_summary": {
                            "message": str(exc),
                            "retryable": bool(getattr(exc, "retryable", False)),
                        },
                    },
                ) from exc
            return {}
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                provider=response.provider,
                provider_id=request.provider_id,
                account_id=request.account_id,
                model=response.model,
                node_id=node_id,
                reasoning_level=request.reasoning_level,
                native_reasoning_json=response.native_reasoning,
                credential_mode=request.credential_mode,
                prompt_hash=prompt_hash,
                step=node_id,
                scene_id=None,
                chapter_id=None,
                request_payload_summary=request_summary,
                response_payload_summary={
                    "request_id": response.request_id,
                    "response_format": response.response_format,
                    "structured_output": response.structured_output,
                },
                prompt_tokens=response.usage.get("input_tokens", 0),
                completion_tokens=response.usage.get("output_tokens", 0),
                total_tokens=response.usage.get("total_tokens", 0),
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                finish_reason=response.finish_reason,
                error_code=None,
            )
        )
        self.session.flush()
        return response.structured_output or {}

    def _routing_config(self) -> Any:
        if self._routing_config_cache is None:
            self._routing_config_cache = load_model_routing_config()
        return self._routing_config_cache

    def _task_config(self, node_id: str) -> Any:
        routing = self._routing_config()
        node_routing = getattr(routing, "node_routing", None)
        if isinstance(node_routing, dict) and node_id in node_routing:
            return node_routing[node_id]
        task_routing = getattr(routing, "task_routing", {})
        if node_id in task_routing:
            return task_routing[node_id]
        raise KeyError(node_id)

    def _template(self, node_id: str) -> Any:
        if self._prompt_templates_cache is None:
            self._prompt_templates_cache = load_prompt_templates()
        return self._prompt_templates_cache[node_id]

    def _sync_findings(self, run_id: str) -> None:
        findings = self.session.execute(select(ReferenceFinding).where(ReferenceFinding.run_id == run_id)).scalars().all()
        for finding in findings:
            review = self.session.get(ReviewItem, finding.review_id)
            if review is None:
                continue
            finding.status = review.status
        for round_row in self.session.execute(
            select(ReferenceLearningRound).where(ReferenceLearningRound.run_id == run_id)
        ).scalars().all():
            round_findings = [finding for finding in findings if finding.round_id == round_row.round_id]
            if round_findings and all(finding.status != "pending" for finding in round_findings):
                round_row.status = "completed"
        self.session.flush()

    def _approved_findings(self, run_id: str) -> list[ReferenceFinding]:
        return self.session.execute(
            select(ReferenceFinding)
            .where(ReferenceFinding.run_id == run_id, ReferenceFinding.status == "approved")
            .order_by(ReferenceFinding.created_at.asc(), ReferenceFinding.finding_id.asc())
        ).scalars().all()

    def _sync_profiles_for_book(self, book_id: str) -> None:
        run_ids = [
            run.run_id
            for run in self.session.execute(select(ReferenceLearningRun).where(ReferenceLearningRun.book_id == book_id)).scalars().all()
        ]
        for run_id in run_ids:
            self._sync_profiles_for_run(run_id)

    def _sync_profiles_for_run(self, run_id: str) -> None:
        self._sync_findings(run_id)
        approved_finding_ids = [finding.finding_id for finding in self._approved_findings(run_id)]
        profiles = self.session.execute(
            select(ReferenceProfile).where(ReferenceProfile.run_id == run_id).order_by(ReferenceProfile.created_at.desc())
        ).scalars().all()
        for profile in profiles:
            safety_summary = _profile_safety_summary(profile.profile_json, stripped_count=_profile_stripped_count(profile))
            is_current = profile.source_finding_ids_json == approved_finding_ids
            if profile.status == PROFILE_STATUS_READY and (not is_current or not safety_summary["safe"]):
                profile.status = PROFILE_STATUS_STALE
            profile.coverage_json = {
                **dict(profile.coverage_json or {}),
                "profile_ready": profile.status == PROFILE_STATUS_READY,
                "profile_stale": profile.status == PROFILE_STATUS_STALE,
                "safety_summary": safety_summary,
            }
        self.session.flush()

    def _pending_round(self, run_id: str) -> ReferenceLearningRound | None:
        rounds = self.session.execute(
            select(ReferenceLearningRound)
            .where(ReferenceLearningRound.run_id == run_id)
            .order_by(ReferenceLearningRound.round_index.desc())
        ).scalars().all()
        for round_row in rounds:
            if round_row.status == "waiting_review":
                return round_row
            findings = self.session.execute(
                select(ReferenceFinding).where(ReferenceFinding.round_id == round_row.round_id)
            ).scalars().all()
            if findings and any(finding.status == "pending" for finding in findings):
                return round_row
        return None

    def coverage_for_book(self, book_id: str) -> dict[str, Any]:
        runs = self.session.execute(
            select(ReferenceLearningRun).where(ReferenceLearningRun.book_id == book_id).order_by(ReferenceLearningRun.created_at.desc())
        ).scalars().all()
        return self.coverage_for_run(runs[0].run_id) if runs else self._empty_coverage_for_book(book_id)

    def coverage_for_run(self, run_id: str) -> dict[str, Any]:
        self._sync_findings(run_id)
        run = self.session.get(ReferenceLearningRun, run_id)
        findings = self.session.execute(select(ReferenceFinding).where(ReferenceFinding.run_id == run_id)).scalars().all()
        approved = [finding for finding in findings if finding.status == "approved"]
        rejected = [finding for finding in findings if finding.status == "rejected"]
        pending = [finding for finding in findings if finding.status == "pending"]
        dimensions = sorted({finding.dimension for finding in approved})
        finding_types = sorted({finding.finding_type for finding in approved})
        approved_finding_ids = [finding.finding_id for finding in sorted(approved, key=lambda item: (item.created_at, item.finding_id))]
        profiles = self.session.execute(select(ReferenceProfile).where(ReferenceProfile.run_id == run_id)).scalars().all()
        profile_stale = any(
            profile.status == PROFILE_STATUS_STALE
            or profile.source_finding_ids_json != approved_finding_ids
            or not _profile_safety_summary(profile.profile_json, stripped_count=_profile_stripped_count(profile))["safe"]
            for profile in profiles
        )
        profile_ready = any(
            profile.status == PROFILE_STATUS_READY
            and profile.source_finding_ids_json == approved_finding_ids
            and _profile_safety_summary(profile.profile_json, stripped_count=_profile_stripped_count(profile))["safe"]
            for profile in profiles
        )
        progress = self._segment_progress_for_book(run.book_id if run else "", findings)
        dimension_coverage_score = min(1.0, len(dimensions) / 4)
        ready = len(approved) >= 4 and "narrative_pattern" in finding_types and "style_rule_set" in finding_types
        learning_complete = progress["eligible_segments"] > 0 and progress["remaining_segments"] == 0 and len(pending) == 0
        return {
            "approved_findings": len(approved),
            "rejected_findings": len(rejected),
            "pending_findings": len(pending),
            "covered_dimensions": dimensions,
            "covered_finding_types": finding_types,
            "coverage_score": dimension_coverage_score,
            "dimension_coverage_score": dimension_coverage_score,
            "sample_coverage_score": progress["sample_coverage_score"],
            "sampled_segments": progress["sampled_segments"],
            "eligible_segments": progress["eligible_segments"],
            "remaining_segments": progress["remaining_segments"],
            "learning_complete": learning_complete,
            "ready": ready,
            "profile_ready": profile_ready,
            "profile_stale": profile_stale,
            "next_round_available": progress["remaining_segments"] > 0 and len(pending) == 0,
        }

    def _empty_coverage_for_book(self, book_id: str) -> dict[str, Any]:
        progress = self._segment_progress_for_book(book_id, [])
        return {
            **_empty_coverage(),
            "sample_coverage_score": progress["sample_coverage_score"],
            "sampled_segments": progress["sampled_segments"],
            "eligible_segments": progress["eligible_segments"],
            "remaining_segments": progress["remaining_segments"],
            "learning_complete": progress["eligible_segments"] > 0 and progress["remaining_segments"] == 0,
            "next_round_available": progress["remaining_segments"] > 0,
        }

    def _segment_progress_for_book(self, book_id: str, findings: list[ReferenceFinding]) -> dict[str, Any]:
        if not book_id:
            return {
                "sampled_segments": 0,
                "eligible_segments": 0,
                "remaining_segments": 0,
                "sample_coverage_score": 0.0,
            }
        segments = self.session.execute(
            select(ReferenceBookSegment)
            .where(ReferenceBookSegment.book_id == book_id)
            .order_by(ReferenceBookSegment.segment_index.asc())
        ).scalars().all()
        eligible_ids = {
            segment.segment_id
            for segment in segments
            if not _is_non_evidence_segment(segment)
        }
        sampled_ids = self._attempted_segment_ids_for_book(book_id) & eligible_ids
        eligible_count = len(eligible_ids)
        sampled_count = len(sampled_ids)
        remaining = max(0, eligible_count - sampled_count)
        return {
            "sampled_segments": sampled_count,
            "eligible_segments": eligible_count,
            "remaining_segments": remaining,
            "sample_coverage_score": (sampled_count / eligible_count) if eligible_count else 0.0,
        }

    def serialize_book_with_summary(self, book: ReferenceBook) -> dict[str, Any]:
        profiles = self._profiles_for_book(book.book_id)
        profile_status = _book_profile_status(profiles)
        return {
            **self.serialize_book(book),
            "coverage": self.coverage_for_book(book.book_id),
            "latest_run": self._latest_run_payload(book.book_id),
            "profile_count": len(profiles),
            "profile_status": profile_status,
            "profile_stale": profile_status == PROFILE_STATUS_STALE,
        }

    @staticmethod
    def serialize_book(book: ReferenceBook) -> dict[str, Any]:
        return {
            "book_id": book.book_id,
            "title": book.title,
            "author_label": book.author_label,
            "source_kind": book.source_kind,
            "source_path": book.source_path,
            "file_name": book.file_name,
            "cloud_policy": book.cloud_policy,
            "analysis_focus": book.analysis_focus,
            "status": book.status,
            "total_chars": book.total_chars,
            "total_segments": book.total_segments,
            "created_at": book.created_at,
            "updated_at": book.updated_at,
        }

    def serialize_run(self, run: ReferenceLearningRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "book_id": run.book_id,
            "status": run.status,
            "batch_size": run.batch_size,
            "round_count": run.round_count,
            "profile_id": run.profile_id,
            "coverage": self.coverage_for_run(run.run_id),
        }

    def serialize_round(self, round_row: ReferenceLearningRound) -> dict[str, Any]:
        findings = self.session.execute(
            select(ReferenceFinding)
            .where(ReferenceFinding.round_id == round_row.round_id)
            .order_by(ReferenceFinding.created_at.asc(), ReferenceFinding.finding_id.asc())
        ).scalars().all()
        return {
            "round_id": round_row.round_id,
            "book_id": round_row.book_id,
            "run_id": round_row.run_id,
            "round_index": round_row.round_index,
            "status": round_row.status,
            "findings": [self.serialize_finding(finding) for finding in findings],
        }

    def serialize_finding(self, finding: ReferenceFinding) -> dict[str, Any]:
        segment = self.session.get(ReferenceBookSegment, finding.segment_id)
        review = self.session.get(ReviewItem, finding.review_id)
        display_summary, _ = _sanitize_reference_finding_text(finding.summary)
        display_summary = _localize_reference_finding_summary(
            display_summary,
            finding_type=finding.finding_type,
            dimension=finding.dimension,
            segment=segment,
        )
        return {
            "finding_id": finding.finding_id,
            "finding_type": finding.finding_type,
            "dimension": finding.dimension,
            "summary": display_summary,
            "evidence_preview": None,
            "source_excerpt_hidden": True,
            "status": finding.status,
            "source_segment": {
                "segment_id": segment.segment_id if segment else finding.segment_id,
                "segment_kind": segment.segment_kind if segment else None,
                "display_label": _segment_display_label(segment),
                "chapter_hint": None,
                "preview": None,
            },
            "model_trace": self._model_trace_for_finding(finding),
            "review": self.serialize_review(review) if review else None,
        }

    @staticmethod
    def serialize_review(review: ReviewItem) -> dict[str, Any]:
        payload = review.candidate_payload_json if isinstance(review.candidate_payload_json, dict) else {}
        candidate_text = review.candidate_text
        candidate_payload_json = review.candidate_payload_json
        if _is_reference_review_payload(payload):
            candidate_text, text_notes = _sanitize_reference_finding_text(review.candidate_text)
            payload_without_notes = {key: value for key, value in payload.items() if key != "safety_notes"}
            safe_payload, payload_notes = _sanitize_reference_finding_payload_extra(payload_without_notes)
            existing_notes = payload.get("safety_notes") if isinstance(payload.get("safety_notes"), dict) else {}
            safe_payload["safety_notes"] = _merge_reference_safety_notes(
                _coerce_reference_safety_notes(existing_notes),
                text_notes,
                payload_notes,
            )
            candidate_payload_json = safe_payload
        return {
            "review_id": review.review_id,
            "item_type": review.item_type,
            "target_collection": review.target_collection,
            "status": review.status,
            "candidate_text": candidate_text,
            "candidate_payload_json": candidate_payload_json,
            "active_on_approve": review.active_on_approve,
            "materialize_status": review.materialize_status,
            "approved_item_row_id": review.approved_item_row_id,
        }

    def serialize_profile(self, profile: ReferenceProfile) -> dict[str, Any]:
        safety_summary = _profile_safety_summary(profile.profile_json, stripped_count=_profile_stripped_count(profile))
        display_profile_json, display_safety_summary = _sanitize_reference_profile_payload(dict(profile.profile_json or {}))
        coverage = dict(profile.coverage_json or {})
        coverage["safety_summary"] = safety_summary
        coverage.setdefault("profile_stale", profile.status == PROFILE_STATUS_STALE)
        return {
            "profile_id": profile.profile_id,
            "book_id": profile.book_id,
            "run_id": profile.run_id,
            "title": profile.title,
            "status": profile.status,
            "profile_json": profile.profile_json,
            "display_profile_json": display_profile_json,
            "preview_items": _profile_preview_items(display_profile_json),
            "coverage": coverage,
            "safety_summary": safety_summary,
            "display_safety_summary": display_safety_summary,
            "source_finding_ids": profile.source_finding_ids_json,
            "application_status": self._profile_application_status(profile),
            "writer_review_summary": _reference_writer_review_summary(display_profile_json),
            "model_trace": self._model_trace_for_profile(profile),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    def _profile_application_status(self, profile: ReferenceProfile) -> dict[str, Any]:
        prefix = f"review_apply_{_safe_key(profile.profile_id)}_"
        reviews = [
            review
            for review in self.session.execute(
                select(ReviewItem)
                .where(ReviewItem.review_id.like("review_apply_%"))
                .order_by(ReviewItem.created_at.asc(), ReviewItem.review_id.asc())
            ).scalars().all()
            if review.review_id.startswith(prefix)
        ]
        return self._application_status_for_reviews(reviews)

    def _application_status_for_reviews(self, reviews: list[ReviewItem]) -> dict[str, Any]:
        ordered_reviews = sorted(reviews, key=lambda item: (item.created_at or "", item.review_id))
        payloads = [
            review.candidate_payload_json
            for review in ordered_reviews
            if isinstance(review.candidate_payload_json, dict)
        ]
        scopes = sorted({str(payload.get("scope")) for payload in payloads if payload.get("scope")})
        scope_refs = sorted({str(payload.get("scope_ref_id")) for payload in payloads if payload.get("scope_ref_id")})
        return {
            "total": len(ordered_reviews),
            "pending": sum(1 for review in ordered_reviews if review.status == "pending"),
            "approved": sum(1 for review in ordered_reviews if review.status == "approved"),
            "rejected": sum(1 for review in ordered_reviews if review.status == "rejected"),
            "review_ids": [review.review_id for review in ordered_reviews],
            "scope": scopes[0] if len(scopes) == 1 else "multiple" if scopes else None,
            "scope_ref_id": scope_refs[0] if len(scope_refs) == 1 else "multiple" if scope_refs else None,
        }

    def _model_trace_for_finding(self, finding: ReferenceFinding) -> dict[str, Any]:
        payload = finding.candidate_payload_json if isinstance(finding.candidate_payload_json, dict) else {}
        quality_score = payload.get("confidence")
        if not isinstance(quality_score, (int, float)):
            quality_score = None
        return self._reference_model_trace(
            book_id=finding.book_id,
            run_id=finding.run_id,
            segment_id=finding.segment_id,
            default_node_id=str(payload.get("llm_node_id") or "reference_style_structure_extract"),
            quality_score=quality_score,
        )

    def _model_trace_for_profile(self, profile: ReferenceProfile) -> dict[str, Any]:
        profile_json = profile.profile_json if isinstance(profile.profile_json, dict) else {}
        quality_score = profile_json.get("quality_score")
        if not isinstance(quality_score, (int, float)):
            quality_score = None
        return self._reference_model_trace(
            book_id=profile.book_id,
            run_id=profile.run_id,
            default_node_id="reference_profile_synthesize",
            quality_score=quality_score,
        )

    def _reference_model_trace(
        self,
        *,
        book_id: str,
        run_id: str | None = None,
        segment_id: str | None = None,
        default_node_id: str,
        quality_score: float | None = None,
    ) -> dict[str, Any]:
        rows = self.session.execute(
            select(LlmCall)
            .where(LlmCall.node_id.like("reference_%"))
            .order_by(LlmCall.created_at.asc(), LlmCall.llm_call_id.asc())
        ).scalars().all()
        calls = [
            row
            for row in rows
            if _llm_call_matches_reference(row, book_id=book_id, run_id=run_id, segment_id=segment_id)
        ]
        if not calls:
            return {
                "provider": "local",
                "model": "local-heuristic",
                "node_id": default_node_id,
                "node_ids": [default_node_id],
                "success_count": 0,
                "failure_count": 0,
                "quality_score": quality_score,
                "mode": "local_heuristic",
            }
        latest = next((row for row in reversed(calls) if not row.error_code), calls[-1])
        node_ids = sorted({str(row.node_id) for row in calls if row.node_id})
        return {
            "provider": latest.provider or "unknown",
            "model": latest.model or "unknown",
            "node_id": latest.node_id or default_node_id,
            "node_ids": node_ids or [default_node_id],
            "success_count": sum(1 for row in calls if not row.error_code),
            "failure_count": sum(1 for row in calls if row.error_code),
            "quality_score": quality_score,
            "mode": "llm",
        }

    def _book(self, book_id: str) -> ReferenceBook:
        book = self.session.get(ReferenceBook, book_id)
        if book is None:
            raise DomainError("REFERENCE_BOOK_NOT_FOUND", f"reference book {book_id} not found", status_code=404)
        return book

    def _run(self, book_id: str, run_id: str) -> ReferenceLearningRun:
        run = self.session.get(ReferenceLearningRun, run_id)
        if run is None or run.book_id != book_id:
            raise DomainError("REFERENCE_RUN_NOT_FOUND", f"reference run {run_id} not found", status_code=404)
        return run

    def _runs_for_book(self, book_id: str) -> list[ReferenceLearningRun]:
        return self.session.execute(
            select(ReferenceLearningRun)
            .where(ReferenceLearningRun.book_id == book_id)
            .order_by(ReferenceLearningRun.created_at.asc(), ReferenceLearningRun.run_id.asc())
        ).scalars().all()

    def _rounds_for_run(self, run_id: str) -> list[ReferenceLearningRound]:
        return self.session.execute(
            select(ReferenceLearningRound)
            .where(ReferenceLearningRound.run_id == run_id)
            .order_by(ReferenceLearningRound.round_index.asc(), ReferenceLearningRound.created_at.asc())
        ).scalars().all()

    def _apply_reviews_for_profiles(self, profiles: list[ReferenceProfile]) -> list[dict[str, Any]]:
        reviews: list[ReviewItem] = []
        for profile in sorted(profiles, key=lambda item: (item.created_at or "", item.profile_id)):
            prefix = f"review_apply_{_safe_key(profile.profile_id)}_"
            rows = self.session.execute(
                select(ReviewItem)
                .where(ReviewItem.review_id.like(f"{prefix}%"))
                .order_by(ReviewItem.created_at.asc(), ReviewItem.review_id.asc())
            ).scalars().all()
            reviews.extend(rows)
        return [self.serialize_review(review) for review in reviews]

    @staticmethod
    def _active_knowledge_refs_from_reviews(apply_reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for review in apply_reviews:
            if review.get("status") != "approved":
                continue
            approved_ref = review.get("approved_item_id") or review.get("approved_item_row_id")
            if not approved_ref:
                continue
            refs.append(
                {
                    "review_id": review.get("review_id"),
                    "item_type": review.get("item_type"),
                    "target_collection": review.get("target_collection"),
                    "approved_item_id": review.get("approved_item_id"),
                    "approved_item_row_id": review.get("approved_item_row_id"),
                }
            )
        return refs

    @staticmethod
    def _learning_tree_summary(
        *,
        runs: list[ReferenceLearningRun],
        round_count: int,
        finding_count: int,
        review_decisions: list[dict[str, Any]],
        profiles: list[ReferenceProfile],
        apply_reviews: list[dict[str, Any]],
        active_knowledge_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        review_statuses = [str(review.get("status") or "unknown") for review in review_decisions]
        return {
            "run_count": len(runs),
            "round_count": round_count,
            "finding_count": finding_count,
            "pending_findings": review_statuses.count("pending"),
            "approved_findings": review_statuses.count("approved"),
            "rejected_findings": review_statuses.count("rejected"),
            "profile_count": len(profiles),
            "apply_review_count": len(apply_reviews),
            "active_knowledge_ref_count": len(active_knowledge_refs),
        }

    def _latest_run_payload(self, book_id: str) -> dict[str, Any] | None:
        run = self.session.execute(
            select(ReferenceLearningRun).where(ReferenceLearningRun.book_id == book_id).order_by(ReferenceLearningRun.created_at.desc())
        ).scalars().first()
        return self.serialize_run(run) if run else None

    def _latest_round_payload(self, book_id: str) -> dict[str, Any] | None:
        round_row = self.session.execute(
            select(ReferenceLearningRound)
            .where(ReferenceLearningRound.book_id == book_id)
            .order_by(ReferenceLearningRound.created_at.desc(), ReferenceLearningRound.round_index.desc())
        ).scalars().first()
        return self.serialize_round(round_row) if round_row else None

    def _profiles_for_book(self, book_id: str) -> list[ReferenceProfile]:
        return self.session.execute(
            select(ReferenceProfile).where(ReferenceProfile.book_id == book_id).order_by(ReferenceProfile.created_at.desc())
        ).scalars().all()


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DomainError("REFERENCE_BOOK_ENCODING_UNSUPPORTED", "reference book must be UTF-8 or GB18030 text", status_code=400)


def _sanitize_reference_profile_payload(profile_json: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    stats = {"stripped_count": 0}
    sanitized = _sanitize_reference_profile_value(profile_json, stats)
    if not isinstance(sanitized, dict):
        sanitized = {}
    return sanitized, _profile_safety_summary(sanitized, stripped_count=stats["stripped_count"])


def _enrich_reference_profile_payload(
    profile_json: dict[str, Any],
    *,
    locale_hint_text: str = "",
    stripped_count: int = 0,
) -> dict[str, Any]:
    enriched = dict(profile_json or {})
    literary_profile = enriched.get("literary_profile") if isinstance(enriched.get("literary_profile"), dict) else {}
    literary_profile = {
        "scene_shapes": _string_list(literary_profile.get("scene_shapes"))
        or _string_list(enriched.get("narrative_patterns"))
        or ["encounter, investigation, reveal, betrayal, chase, or forced choice as abstract scene shapes"],
        "dialogue_strategies": _string_list(literary_profile.get("dialogue_strategies"))
        or ["short pressure beats, misdirection, withheld answer, counter-question, or meaningful silence"],
        "emotional_curves": _string_list(literary_profile.get("emotional_curves"))
        or ["move from ordinary to abnormal, suspicion to confirmation, or retreat to choice"],
        "image_usage": _string_list(literary_profile.get("image_usage"))
        or ["let a concrete object return with changed meaning instead of repeating decoration"],
        "banned_replication_rules": _string_list(literary_profile.get("banned_replication_rules"))
        or _string_list(enriched.get("banned_replication_rules"))
        or ["do not reuse source names, settings, signature plot bridges, protected scenes, or recognizable sentence shapes"],
    }
    enriched["literary_profile"] = literary_profile
    locale = enriched.get("locale") if isinstance(enriched.get("locale"), str) else _detect_locale(
        "\n".join([locale_hint_text, *(_profile_strings(enriched))])
    )
    repetition_score = _profile_repetition_score(_profile_strings(enriched))
    source_term_audit = {
        "safe": not _blocked_profile_markers(json.dumps(enriched, ensure_ascii=False, sort_keys=True)),
        "blocked_markers": _blocked_profile_markers(json.dumps(enriched, ensure_ascii=False, sort_keys=True)),
    }
    safety_findings: list[str] = []
    if source_term_audit["blocked_markers"]:
        safety_findings.append("source_terms_blocked")
    else:
        safety_findings.append("source_terms_clear")
    if repetition_score > 0.35:
        safety_findings.append("repetition_high")
    if stripped_count:
        safety_findings.append("source_text_sanitized")
    quality_score = max(
        0.0,
        min(
            1.0,
            1.0
            - (0.45 if source_term_audit["blocked_markers"] else 0.0)
            - min(0.35, repetition_score * 0.5)
            - (0.15 if not _has_profile_dimensions(enriched) else 0.0),
        ),
    )
    craft_metrics = {
        "style_feature_count": len(_string_list(enriched.get("style_features")))
        + len(_string_list(literary_profile.get("dialogue_strategies")))
        + len(_string_list(literary_profile.get("image_usage"))),
        "narrative_pattern_count": len(_string_list(enriched.get("narrative_patterns")))
        + len(_string_list(literary_profile.get("scene_shapes"))),
        "calibration_count": len(_string_list(enriched.get("calibration_guidance"))),
        "banned_rule_count": len(_string_list(literary_profile.get("banned_replication_rules"))),
    }
    anti_copy_rules = (
        _string_list(literary_profile.get("banned_replication_rules"))
        or _string_list(enriched.get("banned_replication_rules"))
        or ["do not reuse source names, settings, signature plot bridges, protected scenes, or recognizable sentence shapes"]
    )
    applicability = {
        "safe_to_apply": not source_term_audit["blocked_markers"],
        "applicable_techniques": [
            *[f"scene_shape: {item}" for item in _string_list(literary_profile.get("scene_shapes"))[:2]],
            *[f"dialogue_strategy: {item}" for item in _string_list(literary_profile.get("dialogue_strategies"))[:2]],
            *[f"image_usage: {item}" for item in _string_list(literary_profile.get("image_usage"))[:2]],
        ][:6],
        "inapplicable_techniques": [
            "source-specific names, settings, bridge events, signature scenes, and recognizable syntax are not applicable",
        ],
    }
    if not applicability["applicable_techniques"]:
        applicability["applicable_techniques"] = ["use reviewed abstract craft guidance only"]
    enriched.update(
        {
            "locale": locale,
            "quality_score": round(quality_score, 3),
            "source_term_audit": source_term_audit,
            "repetition_score": round(repetition_score, 3),
            "safety_findings": safety_findings,
            "craft_metrics": craft_metrics,
            "applicability": applicability,
            "anti_copy_rules": anti_copy_rules[:8],
            "evidence_safety_summary": _profile_safety_summary(enriched, stripped_count=stripped_count),
        }
    )
    return enriched


def _reference_application_guidance(profile_json: dict[str, Any], *, scope: str, scope_ref_id: str) -> dict[str, Any]:
    profile_payload = dict(profile_json or {})
    literary_profile = profile_payload.get("literary_profile") if isinstance(profile_payload.get("literary_profile"), dict) else {}
    scene_shapes = _string_list(literary_profile.get("scene_shapes"))
    dialogue_strategies = _string_list(literary_profile.get("dialogue_strategies"))
    emotional_curves = _string_list(literary_profile.get("emotional_curves"))
    image_usage = _string_list(literary_profile.get("image_usage"))
    banned_rules = (
        _string_list(literary_profile.get("banned_replication_rules"))
        or _string_list(profile_payload.get("banned_replication_rules"))
        or ["strip source names, settings, signature plot bridges, protected scenes, and recognizable sentence shapes"]
    )
    applicable: list[str] = []
    for label, values in (
        ("scene_shape", scene_shapes),
        ("dialogue_strategy", dialogue_strategies),
        ("emotional_curve", emotional_curves),
        ("image_usage", image_usage),
    ):
        if values:
            applicable.append(f"{label}: {values[0]}")
    if not applicable:
        applicable.append("use only abstract craft guidance that has passed review")
    return {
        "scope": scope,
        "scope_ref_id": scope_ref_id,
        "applicable_techniques": applicable[:6],
        "inapplicable_techniques": [
            "source-specific names, settings, bridge events, signature scenes, and recognizable syntax are not applicable",
        ],
        "safe_to_apply": not _blocked_profile_markers(json.dumps(profile_payload, ensure_ascii=False, sort_keys=True)),
        "safety_reason": "applies reviewed abstract techniques only; source-identifying material remains blocked",
        "banned_replication_rules": banned_rules[:8],
    }


def _detect_locale(text: str) -> str:
    return "zh" if re.search(r"[\u4e00-\u9fff]", text or "") else "en"


def _profile_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            if key in {"source_term_audit", "safety_findings"}:
                continue
            strings.extend(_profile_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_profile_strings(item))
        return strings
    if isinstance(value, str) and value.strip():
        return [re.sub(r"\s+", " ", value).strip()]
    return []


def _profile_repetition_score(strings: list[str]) -> float:
    normalized = [item.lower() for item in strings if item.strip()]
    if not normalized:
        return 1.0
    counts = Counter(normalized)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    return repeated / max(1, len(normalized))


def _has_profile_dimensions(profile_json: dict[str, Any]) -> bool:
    style_profile = profile_json.get("style_profile")
    if isinstance(style_profile, dict):
        features = style_profile.get("features")
        if isinstance(features, dict):
            return any(
                isinstance(payload, dict) and bool(payload.get("guidance"))
                for payload in features.values()
            )
    return bool(profile_json.get("narrative_patterns"))


def _sanitize_reference_profile_value(value: Any, stats: dict[str, int]) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_reference_profile_value(item, stats) for key, item in value.items()}
    if isinstance(value, list):
        sanitized_items = [_sanitize_reference_profile_value(item, stats) for item in value]
        return [item for item in sanitized_items if not (isinstance(item, str) and not item.strip())]
    if isinstance(value, str):
        sanitized, stripped_count = _sanitize_reference_profile_text(value)
        stats["stripped_count"] += stripped_count
        return sanitized
    return value


def _sanitize_reference_profile_text(value: str) -> tuple[str, int]:
    original = re.sub(r"\s+", " ", str(value or "")).strip()
    if not original:
        return "", 0
    stripped_count = 0
    without_evidence = PROFILE_EVIDENCE_LABEL_RE.sub("", original).strip()
    if without_evidence != original:
        stripped_count += 1
    cleaned = without_evidence or original
    if _blocked_profile_markers(cleaned) or len(cleaned) > PROFILE_MAX_SAFE_STRING_CHARS:
        cleaned = _abstract_profile_fallback(original)
        stripped_count += 1
    if _blocked_profile_markers(cleaned) or len(cleaned) > PROFILE_MAX_SAFE_STRING_CHARS:
        cleaned = "将参考内容转化为抽象写作技法，避免保留可识别源文本。"
        stripped_count += 1
    return cleaned, stripped_count


def _profile_safety_summary(profile_json: Any, *, stripped_count: int = 0) -> dict[str, Any]:
    serialized = json.dumps(profile_json or {}, ensure_ascii=False, sort_keys=True)
    blocked_markers = _blocked_profile_markers(serialized)
    return {
        "safe": not blocked_markers,
        "stripped_count": stripped_count,
        "blocked_markers": blocked_markers,
    }


def _blocked_profile_markers(text: str) -> list[str]:
    compact = str(text or "")
    compact_lower = compact.lower()
    blocked: list[str] = []
    for marker in PROFILE_BLOCKED_MARKERS:
        marker_lower = marker.lower()
        if marker in compact or marker_lower in compact_lower:
            blocked.append(marker)
    return sorted(set(blocked))


def _sanitize_reference_finding_text(value: str) -> tuple[str, dict[str, Any]]:
    original = re.sub(r"\s+", " ", str(value or "")).strip()
    if not original:
        return "", _reference_safety_notes(stripped_count=0, blocked_marker_labels=[])

    stripped_count = 0
    marker_labels = _reference_finding_marker_labels(original)
    without_evidence = PROFILE_EVIDENCE_LABEL_RE.sub("", original).strip()
    if without_evidence != original:
        stripped_count += 1
    cleaned = without_evidence or original

    if _blocked_profile_markers(cleaned) or len(cleaned) > PROFILE_MAX_SAFE_STRING_CHARS:
        cleaned = _abstract_profile_fallback(original)
        stripped_count += 1
    if _blocked_profile_markers(cleaned) or len(cleaned) > PROFILE_MAX_SAFE_STRING_CHARS:
        cleaned = "将参考内容转化为抽象写作技法，避免保留可识别源文本。"
        stripped_count += 1

    return cleaned, _reference_safety_notes(
        stripped_count=stripped_count,
        blocked_marker_labels=marker_labels,
    )


def _sanitize_reference_finding_payload_extra(value: Any) -> tuple[Any, dict[str, Any]]:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        notes = _reference_safety_notes(stripped_count=0, blocked_marker_labels=[])
        for key, item in value.items():
            sanitized_item, item_notes = _sanitize_reference_finding_payload_extra(item)
            sanitized[key] = sanitized_item
            notes = _merge_reference_safety_notes(notes, item_notes)
        return sanitized, notes

    if isinstance(value, list):
        sanitized_items: list[Any] = []
        notes = _reference_safety_notes(stripped_count=0, blocked_marker_labels=[])
        for item in value:
            sanitized_item, item_notes = _sanitize_reference_finding_payload_extra(item)
            sanitized_items.append(sanitized_item)
            notes = _merge_reference_safety_notes(notes, item_notes)
        return sanitized_items, notes

    if isinstance(value, str):
        return _sanitize_reference_finding_text(value)

    return value, _reference_safety_notes(stripped_count=0, blocked_marker_labels=[])


def _reference_finding_marker_labels(text: str) -> list[str]:
    raw = str(text or "")
    lowered = raw.lower()
    labels: list[str] = []
    if PROFILE_EVIDENCE_LABEL_RE.search(raw):
        labels.append("evidence_label")
    if any(marker in lowered for marker in ("txt8080", "www.", "http://", "https://")):
        labels.append("source_boilerplate")
    if _blocked_profile_markers(raw):
        labels.append("source_named_entity")
    return sorted(set(labels))


def _reference_safety_notes(*, stripped_count: int, blocked_marker_labels: list[str]) -> dict[str, Any]:
    return {
        "source_excerpt_hidden": True,
        "stripped_count": int(stripped_count),
        "blocked_markers": sorted(set(blocked_marker_labels)),
    }


def _coerce_reference_safety_notes(value: dict[str, Any]) -> dict[str, Any]:
    stripped_count = int(value.get("stripped_count") or 0)
    marker_labels = ["source_named_entity"] if value.get("blocked_markers") else []
    return _reference_safety_notes(
        stripped_count=stripped_count,
        blocked_marker_labels=marker_labels,
    )


def _merge_reference_safety_notes(*notes: dict[str, Any]) -> dict[str, Any]:
    stripped_count = 0
    marker_labels: list[str] = []
    for note in notes:
        stripped_count += int(note.get("stripped_count") or 0)
        marker_labels.extend(str(item) for item in (note.get("blocked_markers") or []) if item)
    return _reference_safety_notes(
        stripped_count=stripped_count,
        blocked_marker_labels=marker_labels,
    )


def _segment_display_label(segment: ReferenceBookSegment | None) -> str:
    if segment is None:
        return SEGMENT_KIND_LABELS["reference"]
    segment_kind = str(segment.segment_kind or "reference").strip().lower().replace(" ", "_")
    return SEGMENT_KIND_LABELS.get(segment_kind, SEGMENT_KIND_LABELS["reference"])


def _dimension_display_label(dimension: str) -> str:
    normalized = str(dimension or "").strip().lower().replace("_", " ")
    if not normalized:
        return "技法"
    if normalized in DIMENSION_LABELS:
        return DIMENSION_LABELS[normalized]
    for key, label in DIMENSION_LABELS.items():
        if key in normalized:
            return label
    return str(dimension or "").strip()


def _reference_locale_hint(
    *,
    book: ReferenceBook | None = None,
    segment: ReferenceBookSegment | None = None,
    segments: list[ReferenceBookSegment] | None = None,
) -> str:
    values: list[str] = []
    if book is not None:
        values.extend([book.title or "", book.author_label or ""])
    if segment is not None:
        values.extend([segment.chapter_hint or "", segment.text or ""])
    for item in segments or []:
        values.extend([item.chapter_hint or "", item.text or ""])
    return _detect_locale("\n".join(values))


def _chinese_reference_finding_summary(
    *,
    finding_type: str,
    dimension: str,
    segment: ReferenceBookSegment | None,
) -> str:
    segment_label = _segment_display_label(segment)
    dimension_label = _dimension_display_label(dimension)
    if finding_type == "narrative_pattern":
        return f"从{segment_label}提炼{dimension_label}结构：先抛出具体现象，延后解释，再让可见后果推动场景转向。"
    if finding_type == "banned_rule_cluster":
        return "禁止复刻参考书中的专名、设定、人物关系、原句和可识别桥段，只保留抽象写作边界。"
    if finding_type == "calibration_candidate":
        return f"把{segment_label}仅作为{dimension_label}校准：学习压力节拍、触感意象和情绪释放，不复用源文措辞。"
    if finding_type == "style_observation":
        return f"从{segment_label}抽象{dimension_label}观察：用具体现象和感官后果承载信息，减少直接说明。"
    return f"将{segment_label}转化为{dimension_label}文笔规则：先用短促压力节拍推进，再用较长情绪句释放。"


def _localize_reference_finding_summary(
    summary: str,
    *,
    finding_type: str,
    dimension: str,
    segment: ReferenceBookSegment | None,
    book: ReferenceBook | None = None,
) -> str:
    if _reference_locale_hint(book=book, segment=segment) != "zh":
        return summary
    if _detect_locale(summary) == "zh":
        return summary
    return _chinese_reference_finding_summary(
        finding_type=finding_type,
        dimension=dimension,
        segment=segment,
    )


def _is_reference_review_payload(payload: dict[str, Any]) -> bool:
    return payload.get("source") in {"reference_book_learning", "reference_profile_apply"}


def _abstract_profile_fallback(text: str) -> str:
    lowered = text.lower()
    if "do not copy" in lowered or "forbidden" in lowered or "banned" in lowered:
        return "不要复制受保护表达、专名、设定、标志性句子或可识别桥段。"
    if "calibrat" in lowered:
        return "校准为抽象写作技法：压缩压力节拍、触感意象与情绪释放，不复用源文本措辞。"
    if "hook" in lowered or "anomaly" in lowered or "consequence" in lowered or "narrative" in lowered:
        return "用具体现象开场，延迟解释，再通过可见后果推动场景转折。"
    if "imagery" in lowered or "sensory" in lowered or "tactile" in lowered:
        return "使用感官反差与触感意象，但避开源文本措辞。"
    if "pressure" in lowered or "rhythm" in lowered or "syntax" in lowered:
        return "先用紧凑压力节拍推进，再用更长的情绪释放句收束。"
    return "将参考内容转化为抽象写作技法，避免保留可识别源文本。"


def _profile_preview_items(profile_json: dict[str, Any]) -> list[str]:
    style_profile = profile_json.get("style_profile") if isinstance(profile_json.get("style_profile"), dict) else {}
    features = style_profile.get("features") if isinstance(style_profile.get("features"), dict) else {}
    preview_items: list[str] = []
    for key in sorted(features):
        feature = features.get(key)
        if not isinstance(feature, dict):
            continue
        guidance = feature.get("guidance")
        items = guidance if isinstance(guidance, list) else [guidance] if guidance else []
        for item in items:
            text = str(item or "").strip()
            if text:
                preview_items.append(f"{key}: {text}")
            if len(preview_items) >= 3:
                break
        if len(preview_items) >= 3:
            break
    narrative_patterns = profile_json.get("narrative_patterns")
    if isinstance(narrative_patterns, list):
        for item in narrative_patterns:
            text = str(item or "").strip()
            if text:
                preview_items.append(f"narrative: {text}")
            if len(preview_items) >= 4:
                break
    return preview_items[:4]


def _reference_writer_review_summary(profile_json: dict[str, Any]) -> dict[str, Any]:
    preview_items = _profile_preview_items(profile_json)
    banned = profile_json.get("banned_replication_rules")
    if not isinstance(banned, list):
        banned = profile_json.get("banned_moves")
    if not isinstance(banned, list):
        banned = []
    narrative_patterns = profile_json.get("narrative_patterns")
    suitable_scenes = narrative_patterns if isinstance(narrative_patterns, list) else []
    return {
        "status": "ready" if preview_items else "not_ready",
        "transferable_techniques": [str(item) for item in preview_items[:5]],
        "forbidden_replication": [str(item) for item in banned[:5]],
        "suitable_scenes": [str(item) for item in suitable_scenes[:5]],
    }


def _profile_stripped_count(profile: ReferenceProfile) -> int:
    safety_summary = dict(dict(profile.coverage_json or {}).get("safety_summary") or {})
    value = safety_summary.get("stripped_count", 0)
    return int(value) if isinstance(value, (int, float)) else 0


def _book_profile_status(profiles: list[ReferenceProfile]) -> str:
    if any(profile.status == PROFILE_STATUS_READY for profile in profiles):
        return PROFILE_STATUS_READY
    if any(profile.status == PROFILE_STATUS_STALE for profile in profiles):
        return PROFILE_STATUS_STALE
    return "none"


def _normalize_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _segment_book(text: str, *, book_id: str) -> list[ReferenceBookSegment]:
    segments: list[ReferenceBookSegment] = []
    chapter_hint: str | None = None
    offset = 0
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    for part in paragraphs:
        start = text.find(part, offset)
        if start < 0:
            start = offset
        end = start + len(part)
        offset = end
        heading = _chapter_heading(part)
        if heading:
            chapter_hint = heading[:80]
            continue
        for chunk in _split_long_segment(part):
            chunk_start = text.find(chunk, start)
            if chunk_start < 0:
                chunk_start = start
            chunk_end = chunk_start + len(chunk)
            index = len(segments) + 1
            segments.append(
                ReferenceBookSegment(
                    segment_id=f"refseg_{_safe_key(book_id)}_{index:04d}",
                    book_id=book_id,
                    segment_index=index,
                    chapter_hint=chapter_hint,
                    segment_kind="body",
                    start_offset=chunk_start,
                    end_offset=chunk_end,
                    text=chunk,
                )
            )
    for index, segment in enumerate(segments):
        segment.segment_kind = _segment_kind(segment.text, index=index, total=len(segments))
    analysis_indexes = [index for index, segment in enumerate(segments) if segment.segment_kind != "boilerplate"]
    if analysis_indexes:
        first_index = analysis_indexes[0]
        last_index = analysis_indexes[-1]
        segments[first_index].segment_kind = "opening"
        if last_index != first_index:
            segments[last_index].segment_kind = "closing"
    return segments


def _chapter_heading(text: str) -> str | None:
    if re.match(r"^#{1,6}\s+\S+", text):
        return re.sub(r"^#{1,6}\s+", "", text).strip()
    if re.match(r"^第[一二三四五六七八九十百千万0-9]+[章节卷部]\b", text):
        return text.strip()
    return None


def _split_long_segment(text: str, *, max_chars: int = 900) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        chunks.append(text[cursor : cursor + max_chars].strip())
        cursor += max_chars
    return [chunk for chunk in chunks if chunk]


def _analysis_worthy_segments(segments: list[ReferenceBookSegment]) -> list[ReferenceBookSegment]:
    return [
        segment
        for segment in segments
        if not _is_non_evidence_segment(segment)
    ]


def _is_non_evidence_segment(segment: ReferenceBookSegment) -> bool:
    return segment.segment_kind == "boilerplate" or _is_boilerplate_segment(segment.text) or _is_front_matter_segment(segment.text)


def _is_front_matter_segment(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    raw = str(text or "").strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    lower = compact.lower()
    if not compact:
        return True
    if any(marker in compact for marker in ("内容简介", "內容簡介", "内容提要", "內容提要", "作品简介", "作品簡介")):
        return True
    if any(marker in compact for marker in ("目录", "目錄")) and len(compact) <= 260:
        return True
    if (
        any(marker in compact for marker in ("合集", "合辑", "合輯"))
        and any(marker in compact for marker in ("包含", "收录", "收錄"))
        and any(marker in compact for marker in ("著", "作者", "目录", "目錄"))
    ):
        return True
    title_mark_count = compact.count("《") + compact.count("》") + compact.count("〈") + compact.count("〉")
    if title_mark_count >= 3 and any(marker in compact for marker in ("著", "作者", "目录", "目錄")):
        return True
    if len(compact) <= 120 and len(lines) <= 3 and any(line.endswith(("著", "作者")) for line in lines):
        return True
    has_cjk = any("一" <= char <= "鿿" for char in raw)
    looks_like_numbered_scene = re.match(r"scene\d+[:：]", lower) is not None
    if not has_cjk and len(compact) <= 160 and len(lines) <= 4 and not looks_like_numbered_scene:
        return True
    if len(compact) > 260:
        return False
    if "合集" in compact and "包含" in compact and "著" in compact:
        return True
    return title_mark_count >= 3 and ("作者" in compact or "著" in compact or "目录" in compact or "目錄" in compact)

def _is_boilerplate_segment(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    if not compact:
        return True
    if any(marker in compact for marker in ("txt8080", "http://", "https://", "www.")):
        return True
    marker_hits = sum(1 for marker in BOILERPLATE_MARKERS if marker.lower() in compact)
    return marker_hits >= 2


def _segment_kind(text: str, *, index: int, total: int) -> str:
    if _is_boilerplate_segment(text):
        return "boilerplate"
    if index == 0:
        return "opening"
    if index == total - 1:
        return "closing"
    if "“" in text or '"' in text:
        return "dialogue"
    if any(word in text for word in ("跑", "穿过", "脚步", "响起", "钥匙", "门外", "停住")):
        return "action"
    if any(word in text for word in ("雨", "灯", "月光", "风", "雪", "窗", "鳞", "水面", "灰")):
        return "imagery"
    if any(word in text for word in ("明白", "后悔", "选择", "判决", "誓言")):
        return "emotion"
    return "structure"


def _segment_stats(segments: list[ReferenceBookSegment], *, total_chars: int) -> dict[str, Any]:
    kinds = Counter(segment.segment_kind for segment in segments)
    chapters = sorted({segment.chapter_hint for segment in segments if segment.chapter_hint})
    return {
        "total_chars": total_chars,
        "total_segments": len(segments),
        "chapter_count": len(chapters),
        "segment_kinds": dict(kinds),
    }


def _finding_summary(*, finding_type: str, dimension: str, segment: ReferenceBookSegment) -> str:
    if _reference_locale_hint(segment=segment) == "zh":
        return _chinese_reference_finding_summary(
            finding_type=finding_type,
            dimension=dimension,
            segment=segment,
        )
    if finding_type == "narrative_pattern":
        return (
            f"Use chapter hook escalation: open with a concrete anomaly, delay explanation, "
            f"then turn the scene through visible consequence."
        )
    if finding_type == "banned_rule_cluster":
        return (
            "Do not copy protected expression, names, organizations, signature lines, or scene-specific twists "
            "from the reference text."
        )
    if finding_type == "calibration_candidate":
        return "Calibrate toward compact pressure, tactile imagery, and emotional release without reusing source wording."
    if finding_type == "style_observation":
        return f"Style observation for {dimension}: compress exposition behind gesture and sensory detail."
    return f"Style rule for {dimension}: use short pressure beats before a longer emotional release sentence."


def _preview(text: str, *, limit: int = 120) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else f"{compact[:limit - 1]}..."


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _reference_user_prompt(task_prompt: str, payload: dict[str, Any]) -> str:
    locale_hint = str(payload.get("locale_hint") or "").strip().lower()
    parts = [task_prompt]
    if locale_hint == "zh":
        parts.extend(
            [
                "",
                (
                    "Language rule: all user-facing string fields in the returned JSON must be written in Chinese (中文). "
                    "Keep JSON keys exactly as required by the schema, and do not include source excerpts."
                ),
            ]
        )
    parts.extend(
        [
            "",
            "Input JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            "",
            "Return JSON that matches the structured schema exactly.",
        ]
    )
    return "\n".join(parts)


def _prompt_hash(
    *,
    node_id: str,
    template_version: str,
    system_prompt: str,
    user_prompt: str,
    structured_schema: dict[str, Any],
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "template_name": node_id,
                "template_version": template_version,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "structured_schema": structured_schema,
            }
        ).encode("utf-8")
    ).hexdigest()


def _sanitize_llm_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key == "text" and isinstance(item, str):
                sanitized[key] = _preview(item, limit=180)
            elif key in {"segments", "approved_findings"} and isinstance(item, list):
                sanitized[key] = [_sanitize_llm_payload(entry) for entry in item[:12]]
            else:
                sanitized[key] = _sanitize_llm_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_llm_payload(item) for item in value]
    return value


def _llm_call_matches_reference(
    call: LlmCall,
    *,
    book_id: str,
    run_id: str | None,
    segment_id: str | None,
) -> bool:
    summary = call.request_payload_summary if isinstance(call.request_payload_summary, dict) else {}
    payload = summary.get("payload") if isinstance(summary.get("payload"), dict) else {}
    book_payload = payload.get("book") if isinstance(payload.get("book"), dict) else {}
    if book_id and book_payload.get("book_id") != book_id:
        return False
    payload_run_id = payload.get("run_id")
    if run_id and payload_run_id and payload_run_id != run_id:
        return False
    if segment_id:
        payload_segment = payload.get("segment") if isinstance(payload.get("segment"), dict) else {}
        return summary.get("segment_id") == segment_id or payload_segment.get("segment_id") == segment_id
    return True


def _coverage_complete(coverage: dict[str, Any]) -> bool:
    return bool(coverage.get("learning_complete"))


def _empty_coverage() -> dict[str, Any]:
    return {
        "approved_findings": 0,
        "rejected_findings": 0,
        "pending_findings": 0,
        "covered_dimensions": [],
        "covered_finding_types": [],
        "coverage_score": 0.0,
        "dimension_coverage_score": 0.0,
        "sample_coverage_score": 0.0,
        "sampled_segments": 0,
        "eligible_segments": 0,
        "remaining_segments": 0,
        "learning_complete": False,
        "ready": False,
        "profile_ready": False,
        "profile_stale": False,
        "next_round_available": False,
    }


def _validate_policy(*, cloud_policy: str, analysis_focus: str) -> None:
    if cloud_policy not in SUPPORTED_CLOUD_POLICIES:
        raise DomainError("REFERENCE_BOOK_CLOUD_POLICY_INVALID", "unsupported cloud policy", status_code=400)
    if analysis_focus not in SUPPORTED_ANALYSIS_FOCUS:
        raise DomainError("REFERENCE_BOOK_ANALYSIS_FOCUS_INVALID", "unsupported analysis focus", status_code=400)


def _required_text(value: str | None, *, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise DomainError("REFERENCE_PROFILE_APPLY_INVALID", f"missing {field}", status_code=400)


def _optional_text(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _looks_like_url(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value.strip()))


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "ref"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
