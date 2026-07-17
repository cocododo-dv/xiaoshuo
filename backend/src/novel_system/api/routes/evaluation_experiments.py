"""质量实验通道路由（结果闭环治理 §6.2/§6.3）。

匿名 A/B 人类盲评：建实验 → 加对（服务端盲化落库）→ 冻结题包 → next-pair
（盲化视图只出 pair_id + 左右纯文本，另附纯计数进度）→ 投票 → 可复算报告。
映射/策略/token/快照哈希在投票前一律不下发；实验清单/详情同样只含元信息与计数。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import EvaluationExperiment, EvaluationPair, EvaluationVote
from novel_system.services.evaluation_experiment import EvaluationExperimentService
from novel_system.services.idempotency import execute_with_idempotency

router = APIRouter(tags=["evaluation_experiments"])


class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    hypothesis: str = ""
    treatment_policy: dict[str, Any] = {}
    control_policy: dict[str, Any] = {}
    isolation_mode: str | None = None
    snapshot_source_ref: str | None = None
    evidence_provenance: str = "synthetic"


class AddPairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_snapshot_hash: str
    treatment_text: str
    control_text: str
    treatment_ref: str | None = None
    control_ref: str | None = None
    token_cost: dict[str, Any] = {}
    genre: str | None = None
    scene_function: str | None = None


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: str
    reviewer_ref: str | None = None
    duration_ms: int | None = None


def _experiment_dict(exp: EvaluationExperiment) -> dict[str, Any]:
    return {
        "experiment_id": exp.experiment_id,
        "name": exp.name,
        "hypothesis": exp.hypothesis,
        "treatment_policy": exp.treatment_policy_json,
        "control_policy": exp.control_policy_json,
        "status": exp.status,
        "isolation_mode": exp.isolation_mode,
        "snapshot_source_ref": exp.snapshot_source_ref,
        "evidence_provenance": exp.evidence_provenance,
        "frozen_at": exp.frozen_at,
        "frozen_pair_manifest_hash": exp.frozen_pair_manifest_hash,
        "created_at": exp.created_at,
    }


def _pair_admin_dict(pair: EvaluationPair) -> dict[str, Any]:
    """seed 回执——含 pair_id/no_contrast，但**不含** blind_mapping（连 seeding 也不回显隐藏键）。"""
    return {
        "pair_id": pair.pair_id,
        "experiment_id": pair.experiment_id,
        "scene_snapshot_hash": pair.scene_snapshot_hash,
        "no_contrast": pair.no_contrast,
        "genre": pair.genre,
        "scene_function": pair.scene_function,
    }


def _vote_dict(vote: EvaluationVote) -> dict[str, Any]:
    return {
        "vote_id": vote.vote_id,
        "pair_id": vote.pair_id,
        "choice": vote.choice,
        "reviewer_ref": vote.reviewer_ref,
        "duration_ms": vote.duration_ms,
    }


@router.get("/api/v1/evaluation-experiments")
def list_experiments(request: Request, session: Session = Depends(get_session)):
    """盲评工作台入口：全部实验 + 进度摘要（纯元信息与计数，不含盲化隐藏键）。"""
    data = EvaluationExperimentService(session).list_experiments()
    return ok(data, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/evaluation-experiments/{experiment_id}/overview")
def experiment_overview(experiment_id: str, request: Request, session: Session = Depends(get_session)):
    data = EvaluationExperimentService(session).experiment_overview(experiment_id)
    return ok(data, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/evaluation-experiments")
def create_experiment(payload: CreateExperimentRequest, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/evaluation-experiments",
        payload=payload.model_dump(),
        action=lambda: _experiment_dict(
            EvaluationExperimentService(session).create_experiment(
                name=payload.name,
                hypothesis=payload.hypothesis,
                treatment_policy=payload.treatment_policy,
                control_policy=payload.control_policy,
                isolation_mode=payload.isolation_mode,
                snapshot_source_ref=payload.snapshot_source_ref,
                evidence_provenance=payload.evidence_provenance,
            )
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/evaluation-experiments/{experiment_id}/freeze")
def freeze_experiment(experiment_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/evaluation-experiments/{experiment_id}/freeze",
        payload={"experiment_id": experiment_id},
        action=lambda: _experiment_dict(
            EvaluationExperimentService(session).freeze_experiment(experiment_id)
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/evaluation-experiments/{experiment_id}/pairs")
def add_pair(experiment_id: str, payload: AddPairRequest, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/evaluation-experiments/{experiment_id}/pairs",
        payload={"experiment_id": experiment_id, **payload.model_dump()},
        action=lambda: _pair_admin_dict(
            EvaluationExperimentService(session).add_pair(
                experiment_id,
                scene_snapshot_hash=payload.scene_snapshot_hash,
                treatment_text=payload.treatment_text,
                control_text=payload.control_text,
                treatment_ref=payload.treatment_ref,
                control_ref=payload.control_ref,
                token_cost=payload.token_cost,
                genre=payload.genre,
                scene_function=payload.scene_function,
            )
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/evaluation-experiments/{experiment_id}/next-pair")
def next_pair(experiment_id: str, request: Request, reviewer_ref: str | None = None, session: Session = Depends(get_session)):
    view = EvaluationExperimentService(session).next_pair(experiment_id, reviewer_ref=reviewer_ref)
    return ok(view, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/evaluation-pairs/{pair_id}/vote")
def vote(pair_id: str, payload: VoteRequest, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/evaluation-pairs/{pair_id}/vote",
        payload={"pair_id": pair_id, **payload.model_dump()},
        action=lambda: _vote_dict(
            EvaluationExperimentService(session).record_vote(
                pair_id,
                choice=payload.choice,
                reviewer_ref=payload.reviewer_ref,
                duration_ms=payload.duration_ms,
            )
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/evaluation-experiments/{experiment_id}/report")
def report(experiment_id: str, request: Request, session: Session = Depends(get_session)):
    data = EvaluationExperimentService(session).build_report(experiment_id)
    return ok(data, req_id=getattr(request.state, "request_id", None))
