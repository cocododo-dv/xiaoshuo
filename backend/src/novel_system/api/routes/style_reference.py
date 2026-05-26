"""Style Reference v1.1 — Phase 1 路由清单(PR-4)+ PR-7 validate / reports。

参见 plans/style-reference-v1-1-fancy-shannon.md §"路由清单"。
prefix: /api/v2/style-reference。
PR-4 18 端点 + PR-7 3 端点(validate / reports get / reports list)= 21 端点。
不含 inject(PR-8)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import (
    ReviewItem,
    StyleReferenceBannedTerm,
    StyleReferenceEvidence,
    StyleReferenceExtraction,
    StyleReferenceFinding,
    StyleReferenceInjectionBinding,
    StyleReferenceParagraph,
    StyleReferenceProfile,
    StyleReferenceQuote,
    StyleReferenceRun,
    StyleReferenceValidationReport,
)
from novel_system.services.errors import DomainError
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.materialization import MaterializationService
from novel_system.services.style_reference.preview import PreviewService
from novel_system.services.style_reference.profile_synthesizer import ProfileSynthesizer
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.run_orchestrator import RunOrchestrator
from novel_system.services.style_reference.schemas import (
    BindingScope,
    InjectionStrategy,
    RunStatus,
    TaskType,
    ValidateRequest,
    ValidationMode,
    ValidationTargetKind,
)
from novel_system.services.style_reference.validation import ValidationOrchestrator

router = APIRouter(tags=["style_reference"])

PATH_PREFIX = "/api/v2/style-reference"


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class ImportPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_path: str
    title: str
    author_label: str | None = None
    cloud_policy: str


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layers: list[str] | None = None


class FindingReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str  # approved / rejected / pending
    comment: str | None = None


class ApplyProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    scope_ref_id: str | None = None
    task_type: str = "scene_generation"
    strategy: str = "A"


class ValidateGeneratedRequest(BaseModel):
    """`POST /profiles/{id}/validate` body(profile_id 在 path,不在 body)。"""

    model_config = ConfigDict(extra="forbid")
    generated_text: str
    target_kind: str = "manual"
    target_ref_id: str | None = None
    mode: str = "async_full"
    task_context: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_book(book) -> dict[str, Any]:
    return {
        "book_id": book.book_id,
        "title": book.title,
        "author_label": book.author_label,
        "source_kind": book.source_kind,
        "source_path": book.source_path,
        "cloud_policy": book.cloud_policy,
        "text_checksum": book.text_checksum,
        "total_chars": book.total_chars,
        "status": book.status,
        "stats_json": book.stats_json or {},
        "created_at": book.created_at,
        "updated_at": book.updated_at,
    }


def _serialize_run(run) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "book_id": run.book_id,
        "status": run.status,
        "phase": run.phase,
        "coverage_json": run.coverage_json or {},
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _serialize_finding(finding) -> dict[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "book_id": finding.book_id,
        "run_id": finding.run_id,
        "extraction_id": finding.extraction_id,
        "sub_dimension": finding.sub_dimension,
        "finding_kind": finding.finding_kind,
        "statement": finding.statement,
        "confidence": finding.confidence,
        "status": finding.status,
        "review_id": finding.review_id,
    }


def _serialize_profile(profile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "book_id": profile.book_id,
        "run_id": profile.run_id,
        "title": profile.title,
        "status": profile.status,
        "profile_json": profile.profile_json or {},
        "coverage_json": profile.coverage_json or {},
        "version_tag": profile.version_tag,
        "source_finding_ids_json": profile.source_finding_ids_json or [],
    }


def _serialize_binding(binding) -> dict[str, Any]:
    return {
        "binding_id": binding.binding_id,
        "profile_id": binding.profile_id,
        "scope": binding.scope,
        "scope_ref_id": binding.scope_ref_id,
        "task_type": binding.task_type,
        "strategy": binding.strategy,
        "status": binding.status,
        "config_json": binding.config_json or {},
    }


def _actor(request: Request) -> str:
    return getattr(request.state, "operator_ref", None) or "operator"


def _req_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _idempotency_key(request: Request) -> str | None:
    return request.headers.get("X-Idempotency-Key")


def _with_idem(
    session: Session,
    request: Request,
    *,
    method: str,
    path_template: str,
    payload: dict[str, Any],
    action,
):
    result, status = execute_with_idempotency(
        session,
        idempotency_key=_idempotency_key(request),
        method=method,
        path_template=path_template,
        payload=payload,
        action=action,
        actor_ref=_actor(request),
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=_req_id(request), headers=headers)


def _get_llm_client_and_enabled():
    """从仓库 settings + LLMClient 构造 client(若 LLM_ENABLED=true)。

    实际生产路由调用方应使用 PR-7 之后的统一 LLM client 工厂;PR-4 简化为
    每路由根据 settings 构造。
    """
    from novel_system.services.llm_client import LLMClient
    from novel_system.services.system_config import load_llm_provider_runtime_configs
    from novel_system.settings import get_settings

    settings = get_settings()
    if not settings.llm_enabled:
        return None, False
    client = LLMClient(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        provider_configs=load_llm_provider_runtime_configs(),
    )
    return client, True


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------


@router.post(f"{PATH_PREFIX}/books/import-path")
def import_book_path(
    payload: ImportPathRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")

    def _do() -> dict[str, Any]:
        service = IngestService(session, llm_enabled=False)
        result = service.ingest_path(
            file_path=body["file_path"],
            title=body["title"],
            author_label=body.get("author_label"),
            cloud_policy=body["cloud_policy"],
        )
        return {
            "book": _serialize_book(result.book),
            "paragraphs_count": result.paragraphs_count,
            "safety": result.safety_payload,
        }

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/books/import-path",
        payload=body,
        action=_do,
    )


@router.post(f"{PATH_PREFIX}/books/import-upload")
async def import_book_upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    author_label: str | None = Form(default=None),
    cloud_policy: str = Form(...),
    session: Session = Depends(get_session),
):
    raw_bytes = await file.read()
    payload: dict[str, Any] = {
        "file_name": file.filename,
        "title": title,
        "author_label": author_label,
        "cloud_policy": cloud_policy,
    }

    def _do() -> dict[str, Any]:
        service = IngestService(session, llm_enabled=False)
        result = service.ingest_upload(
            raw_bytes=raw_bytes,
            file_name=payload["file_name"],
            title=payload["title"],
            author_label=payload.get("author_label"),
            cloud_policy=payload["cloud_policy"],
        )
        return {
            "book": _serialize_book(result.book),
            "paragraphs_count": result.paragraphs_count,
            "safety": result.safety_payload,
        }

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/books/import-upload",
        payload=payload,
        action=_do,
    )


@router.get(f"{PATH_PREFIX}/books")
def list_books(
    request: Request,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    books = repo.list_books(status=status)
    return ok(
        {"books": [_serialize_book(b) for b in books]},
        req_id=_req_id(request),
    )


@router.get(f"{PATH_PREFIX}/books/{{book_id}}")
def get_book(
    book_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    book = repo.get_book(book_id)
    if book is None:
        raise DomainError(
            "STYLE_REFERENCE_BOOK_NOT_FOUND",
            f"book {book_id!r} not found",
            status_code=404,
        )
    return ok({"book": _serialize_book(book)}, req_id=_req_id(request))


@router.delete(f"{PATH_PREFIX}/books/{{book_id}}")
def delete_book(
    book_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    def _do() -> dict[str, Any]:
        repo = StyleReferenceRepository(session)
        book = repo.get_book(book_id)
        if book is None:
            raise DomainError(
                "STYLE_REFERENCE_BOOK_NOT_FOUND",
                f"book {book_id!r} not found",
                status_code=404,
            )
        # FK 反向 cascade(无 ON DELETE CASCADE,显式删)
        # 顺序:reports → bindings → banned_terms → profiles → evidences → findings →
        # extractions → quotes → runs → paragraphs → book
        profile_ids = [p.profile_id for p in repo.list_profiles(book_id=book_id)]
        for pid in profile_ids:
            session.execute(
                delete(StyleReferenceValidationReport).where(
                    StyleReferenceValidationReport.profile_id == pid
                )
            )
            session.execute(
                delete(StyleReferenceInjectionBinding).where(
                    StyleReferenceInjectionBinding.profile_id == pid
                )
            )
            session.execute(
                delete(StyleReferenceBannedTerm).where(
                    StyleReferenceBannedTerm.profile_id == pid
                )
            )
        session.execute(
            delete(StyleReferenceProfile).where(
                StyleReferenceProfile.book_id == book_id
            )
        )
        finding_ids = [
            f.finding_id for f in repo.list_findings(book_id=book_id)
        ]
        if finding_ids:
            session.execute(
                delete(StyleReferenceEvidence).where(
                    StyleReferenceEvidence.finding_id.in_(finding_ids)
                )
            )
        session.execute(
            delete(StyleReferenceFinding).where(
                StyleReferenceFinding.book_id == book_id
            )
        )
        session.execute(
            delete(StyleReferenceExtraction).where(
                StyleReferenceExtraction.book_id == book_id
            )
        )
        session.execute(
            delete(StyleReferenceQuote).where(StyleReferenceQuote.book_id == book_id)
        )
        session.execute(
            delete(StyleReferenceRun).where(StyleReferenceRun.book_id == book_id)
        )
        session.execute(
            delete(StyleReferenceParagraph).where(
                StyleReferenceParagraph.book_id == book_id
            )
        )
        repo.delete_book(book_id)
        return {"book_id": book_id, "deleted": True}

    return _with_idem(
        session,
        request,
        method="DELETE",
        path_template=f"{PATH_PREFIX}/books/{{book_id}}",
        payload={"book_id": book_id},
        action=_do,
    )


@router.post(f"{PATH_PREFIX}/books/{{book_id}}/reclassify")
def reclassify_book(
    book_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """重跑段落分类器。PR-4 占位:实际重跑逻辑等同 ingest 的 segmentation 调度。"""

    def _do() -> dict[str, Any]:
        repo = StyleReferenceRepository(session)
        book = repo.get_book(book_id)
        if book is None:
            raise DomainError(
                "STYLE_REFERENCE_BOOK_NOT_FOUND",
                f"book {book_id!r} not found",
                status_code=404,
            )
        return {"book_id": book_id, "status": "reclassify_pending", "note": "PR-5+ 实装"}

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/books/{{book_id}}/reclassify",
        payload={"book_id": book_id},
        action=_do,
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post(f"{PATH_PREFIX}/books/{{book_id}}/runs")
def start_run(
    book_id: str,
    payload: StartRunRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")

    def _do() -> dict[str, Any]:
        client, enabled = _get_llm_client_and_enabled()
        layers_raw = body.get("layers") or ["language", "narrative"]
        try:
            layers = [Layer(layer) for layer in layers_raw]
        except ValueError as exc:
            raise DomainError(
                "STYLE_REFERENCE_LAYER_INVALID",
                f"invalid layer: {exc}",
                status_code=400,
            ) from exc
        orch = RunOrchestrator(session, llm_client=client, llm_enabled=enabled)
        result = orch.start_extract_run(book_id, layers=layers)
        return {
            "run_id": result.run_id,
            "book_id": result.book_id,
            "status": result.status,
            "layers": result.layers,
            "sub_dim_results": [
                {
                    "sub_dimension": r.sub_dimension.value,
                    "findings_count": len(r.findings),
                    "extractions_created": r.extractions_created,
                }
                for r in result.sub_dim_results
            ],
        }

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/books/{{book_id}}/runs",
        payload={"book_id": book_id, **body},
        action=_do,
    )


@router.get(f"{PATH_PREFIX}/runs/{{run_id}}")
def get_run(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    run = repo.get_run(run_id)
    if run is None:
        raise DomainError(
            "STYLE_REFERENCE_RUN_NOT_FOUND",
            f"run {run_id!r} not found",
            status_code=404,
        )
    return ok({"run": _serialize_run(run)}, req_id=_req_id(request))


@router.post(f"{PATH_PREFIX}/runs/{{run_id}}/cancel")
def cancel_run(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    def _do() -> dict[str, Any]:
        repo = StyleReferenceRepository(session)
        updated = repo.update_run(run_id, status=RunStatus.CANCELLED.value)
        if updated is None:
            raise DomainError(
                "STYLE_REFERENCE_RUN_NOT_FOUND",
                f"run {run_id!r} not found",
                status_code=404,
            )
        return {"run_id": run_id, "status": updated.status}

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/runs/{{run_id}}/cancel",
        payload={"run_id": run_id},
        action=_do,
    )


@router.get(f"{PATH_PREFIX}/runs/{{run_id}}/findings")
def list_run_findings(
    run_id: str,
    request: Request,
    sub_dimension: str | None = None,
    finding_kind: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    findings = repo.list_findings(
        run_id=run_id,
        sub_dimension=sub_dimension,
        finding_kind=finding_kind,
        status=status,
    )
    return ok(
        {"findings": [_serialize_finding(f) for f in findings]},
        req_id=_req_id(request),
    )


# ---------------------------------------------------------------------------
# Findings review
# ---------------------------------------------------------------------------


@router.post(f"{PATH_PREFIX}/findings/{{finding_id}}/review")
def review_finding(
    finding_id: str,
    payload: FindingReviewRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")

    def _do() -> dict[str, Any]:
        repo = StyleReferenceRepository(session)
        finding = repo.get_finding(finding_id)
        if finding is None:
            raise DomainError(
                "STYLE_REFERENCE_FINDING_NOT_FOUND",
                f"finding {finding_id!r} not found",
                status_code=404,
            )
        decision = body["decision"]
        if decision not in ("approved", "rejected", "pending"):
            raise DomainError(
                "STYLE_REFERENCE_REVIEW_DECISION_INVALID",
                f"decision {decision!r} not allowed",
                status_code=400,
            )
        # 创建或 update ReviewItem(prefix `review_style_ref_finding_`)
        review_id = f"review_style_ref_finding_{finding_id[-12:]}"
        existing = session.get(ReviewItem, review_id)
        if existing is None:
            review = ReviewItem(
                review_id=review_id,
                item_type=(
                    "banned_rule_cluster"
                    if finding.finding_kind == "forbidden_pattern"
                    else "style_observation"
                ),
                status=decision,
                candidate_text=finding.statement,
                candidate_payload_json={
                    "source": "style_reference_finding_review",
                    "finding_id": finding_id,
                    "sub_dimension": finding.sub_dimension,
                    "finding_kind": finding.finding_kind,
                    "comment": body.get("comment"),
                },
                active_on_approve=0,
            )
            session.add(review)
        else:
            existing.status = decision
            existing.candidate_payload_json = {
                **(existing.candidate_payload_json or {}),
                "comment": body.get("comment"),
            }
        # 反向更新 finding.review_id + status
        repo.update_finding(finding_id, review_id=review_id, status=decision)
        session.flush()
        return {"finding_id": finding_id, "review_id": review_id, "decision": decision}

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/findings/{{finding_id}}/review",
        payload={"finding_id": finding_id, **body},
        action=_do,
    )


# ---------------------------------------------------------------------------
# Synthesize
# ---------------------------------------------------------------------------


@router.post(f"{PATH_PREFIX}/runs/{{run_id}}/synthesize")
def synthesize_profile(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    def _do() -> dict[str, Any]:
        repo = StyleReferenceRepository(session)
        run = repo.get_run(run_id)
        if run is None:
            raise DomainError(
                "STYLE_REFERENCE_RUN_NOT_FOUND",
                f"run {run_id!r} not found",
                status_code=404,
            )
        client, enabled = _get_llm_client_and_enabled()
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=enabled)
        profile = synth.synthesize(run.book_id, run_id)
        return {"profile": _serialize_profile(profile)}

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/runs/{{run_id}}/synthesize",
        payload={"run_id": run_id},
        action=_do,
    )


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@router.get(f"{PATH_PREFIX}/profiles")
def list_profiles(
    request: Request,
    book_id: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    profiles = repo.list_profiles(book_id=book_id, status=status)
    return ok(
        {"profiles": [_serialize_profile(p) for p in profiles]},
        req_id=_req_id(request),
    )


@router.get(f"{PATH_PREFIX}/profiles/{{profile_id}}")
def get_profile(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    profile = repo.get_profile(profile_id)
    if profile is None:
        raise DomainError(
            "STYLE_REFERENCE_PROFILE_NOT_FOUND",
            f"profile {profile_id!r} not found",
            status_code=404,
        )
    return ok({"profile": _serialize_profile(profile)}, req_id=_req_id(request))


@router.post(f"{PATH_PREFIX}/profiles/{{profile_id}}/preview")
def preview_profile(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    def _do() -> dict[str, Any]:
        client, enabled = _get_llm_client_and_enabled()
        svc = PreviewService(session, llm_client=client, llm_enabled=enabled)
        results = svc.generate(profile_id)
        return {
            "profile_id": profile_id,
            "samples": [r.model_dump() for r in results],
        }

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/profiles/{{profile_id}}/preview",
        payload={"profile_id": profile_id},
        action=_do,
    )


@router.post(f"{PATH_PREFIX}/profiles/{{profile_id}}/apply")
def apply_profile(
    profile_id: str,
    payload: ApplyProfileRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")

    def _do() -> dict[str, Any]:
        try:
            scope = BindingScope(body["scope"])
            task_type = TaskType(body.get("task_type") or "scene_generation")
            strategy = InjectionStrategy(body.get("strategy") or "A")
        except ValueError as exc:
            raise DomainError(
                "STYLE_REFERENCE_APPLY_PARAM_INVALID",
                str(exc),
                status_code=400,
            ) from exc
        svc = MaterializationService(session)
        result = svc.apply_profile(
            profile_id,
            scope=scope,
            scope_ref_id=body.get("scope_ref_id"),
            task_type=task_type,
            strategy=strategy,
        )
        return {
            "profile_id": result.profile_id,
            "binding_id": result.binding_id,
            "review_ids": result.review_ids,
            "item_type_counts": result.item_type_counts,
        }

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/profiles/{{profile_id}}/apply",
        payload={"profile_id": profile_id, **body},
        action=_do,
    )


@router.get(f"{PATH_PREFIX}/profiles/{{profile_id}}/bindings")
def list_bindings(
    profile_id: str,
    request: Request,
    task_type: str | None = None,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    bindings = repo.list_bindings(profile_id=profile_id, task_type=task_type)
    return ok(
        {"bindings": [_serialize_binding(b) for b in bindings]},
        req_id=_req_id(request),
    )


@router.delete(f"{PATH_PREFIX}/bindings/{{binding_id}}")
def delete_binding(
    binding_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    def _do() -> dict[str, Any]:
        repo = StyleReferenceRepository(session)
        rowcount = repo.delete_binding(binding_id)
        if rowcount == 0:
            raise DomainError(
                "STYLE_REFERENCE_BINDING_NOT_FOUND",
                f"binding {binding_id!r} not found",
                status_code=404,
            )
        return {"binding_id": binding_id, "deleted": True}

    return _with_idem(
        session,
        request,
        method="DELETE",
        path_template=f"{PATH_PREFIX}/bindings/{{binding_id}}",
        payload={"binding_id": binding_id},
        action=_do,
    )


# ---------------------------------------------------------------------------
# PR-7 — Validation endpoints
# ---------------------------------------------------------------------------


def _serialize_validation_report(report) -> dict[str, Any]:
    return {
        "report_id": report.report_id,
        "profile_id": report.profile_id,
        "target_kind": report.target_kind,
        "target_ref_id": report.target_ref_id,
        "verdict": report.verdict,
        "quantitative_json": report.quantitative_json or [],
        "semantic_json": report.semantic_json or [],
        "plagiarism_json": report.plagiarism_json or {},
        "forbidden_hits_json": report.forbidden_hits_json or [],
        "mode_executed": report.mode_executed,
        "created_at": report.created_at,
    }


@router.post(f"{PATH_PREFIX}/profiles/{{profile_id}}/validate")
def validate_profile_generated(
    profile_id: str,
    payload: ValidateGeneratedRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    """PR-7 §7 — sync_only / async_full 双路径 validation。"""
    body = payload.model_dump(mode="json")

    def _do() -> dict[str, Any]:
        try:
            target_kind = ValidationTargetKind(body.get("target_kind") or "manual")
            mode = ValidationMode(body.get("mode") or "async_full")
        except ValueError as exc:
            raise DomainError(
                "STYLE_REFERENCE_VALIDATE_PARAM_INVALID",
                str(exc),
                status_code=400,
            ) from exc

        req = ValidateRequest(
            generated_text=body["generated_text"],
            target_kind=target_kind,
            target_ref_id=body.get("target_ref_id"),
            mode=mode,
            task_context=body.get("task_context"),
        )
        client, enabled = _get_llm_client_and_enabled()
        orch = ValidationOrchestrator(session, llm_client=client, llm_enabled=enabled)
        result = orch.validate(profile_id, req)
        return result.model_dump(mode="json")

    return _with_idem(
        session,
        request,
        method="POST",
        path_template=f"{PATH_PREFIX}/profiles/{{profile_id}}/validate",
        payload={"profile_id": profile_id, **body},
        action=_do,
    )


@router.get(f"{PATH_PREFIX}/reports/{{report_id}}")
def get_validation_report(
    report_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    report = repo.get_validation_report(report_id)
    if report is None:
        raise DomainError(
            "STYLE_REFERENCE_REPORT_NOT_FOUND",
            f"validation report {report_id!r} not found",
            status_code=404,
        )
    return ok({"report": _serialize_validation_report(report)}, req_id=_req_id(request))


@router.get(f"{PATH_PREFIX}/profiles/{{profile_id}}/reports")
def list_validation_reports(
    profile_id: str,
    request: Request,
    verdict: str | None = None,
    session: Session = Depends(get_session),
):
    repo = StyleReferenceRepository(session)
    reports = repo.list_validation_reports(profile_id=profile_id, verdict=verdict)
    return ok(
        {"reports": [_serialize_validation_report(r) for r in reports]},
        req_id=_req_id(request),
    )
