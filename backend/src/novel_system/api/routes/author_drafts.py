from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.author_drafts import AuthorDraftService

router = APIRouter(tags=["author-drafts"])


@router.get("/api/v1/author-drafts/{object_type}/{object_id}/current")
def get_current_author_draft(object_type: str, object_id: str, request: Request, session: Session = Depends(get_session)):
    payload = AuthorDraftService(session).current(object_type, object_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{object_type}/{object_id}/ensure")
def ensure_author_draft(object_type: str, object_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = AuthorDraftService(session).ensure(object_type, object_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{object_type}/{object_id}/ensure-blank")
def ensure_blank_author_draft(object_type: str, object_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = AuthorDraftService(session).ensure_blank(object_type, object_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.patch("/api/v1/author-drafts/{draft_id}")
def save_author_draft(draft_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).save(draft_id, payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/author-drafts/{draft_id}/events")
def get_author_draft_events(draft_id: str, request: Request, session: Session = Depends(get_session)):
    result = AuthorDraftService(session).events(draft_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/author-drafts/{draft_id}/revisions")
def list_author_draft_revisions(draft_id: str, request: Request, session: Session = Depends(get_session)):
    result = AuthorDraftService(session).revisions(draft_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/author-drafts/{draft_id}/revisions/{revision_no}")
def get_author_draft_revision(draft_id: str, revision_no: int, request: Request, session: Session = Depends(get_session)):
    result = AuthorDraftService(session).revision(draft_id, revision_no)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/derive-from-generation")
def derive_author_draft_from_generation(draft_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).derive_from_generation(draft_id, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/author-drafts/{draft_id}/proposals")
def get_author_draft_proposals(draft_id: str, request: Request, session: Session = Depends(get_session)):
    result = AuthorDraftService(session).proposals(draft_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/author-drafts/{draft_id}/proposals/{proposal_id}/diff")
def get_author_draft_proposal_diff(
    draft_id: str,
    proposal_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    result = AuthorDraftService(session).proposal_diff(draft_id, proposal_id)
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/apply-proposal")
def apply_author_draft_scoped_proposal(
    draft_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).apply_proposal_to_draft(draft_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/proposals/generate")
def generate_author_draft_proposal(
    draft_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).generate_proposal(draft_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/proposals/generate-set")
def generate_author_draft_proposal_set(
    draft_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).generate_proposal_set(draft_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-draft-proposals/{proposal_id}/apply")
def apply_author_draft_proposal(
    proposal_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).apply_proposal(proposal_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-draft-proposals/{proposal_id}/reject")
def reject_author_draft_proposal(
    proposal_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).reject_proposal(proposal_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/apply-patch-option")
def apply_author_draft_patch_option(draft_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).apply_patch_option(draft_id, payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/candidate-events")
def record_author_draft_candidate_event(draft_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).record_candidate_event(draft_id, payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/structure-extract")
def extract_author_draft_structure(draft_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).extract_structure(draft_id, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-structure-candidates/{candidate_id}/apply")
def apply_author_structure_candidate(
    candidate_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).apply_structure_candidate(candidate_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-structure-candidates/{candidate_id}/reject")
def reject_author_structure_candidate(
    candidate_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).reject_structure_candidate(candidate_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/projects/{project_id}/discovery-draft/current")
def get_project_discovery_draft(project_id: str, request: Request, session: Session = Depends(get_session)):
    payload = AuthorDraftService(session).current("project", project_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/projects/{project_id}/discovery-draft/ensure")
def ensure_project_discovery_draft(project_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = AuthorDraftService(session).ensure_blank("project", project_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/projects/{project_id}/chapter-drafts/open")
def open_project_chapter_draft(
    project_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).open_chapter_draft(project_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-structure-candidates/{candidate_id}/apply-to-snowflake")
def apply_author_structure_candidate_to_snowflake(
    candidate_id: str,
    request: Request,
    payload: dict | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).apply_project_structure_to_snowflake(candidate_id, payload or {}, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))
