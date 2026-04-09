from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.contracts.bundle import BundleWorksheetEnvelope
from novel_system.db.models import FinalScene, SceneBundle, SceneDraft

router = APIRouter(tags=["interop"])


@router.get("/api/v1/interop/export/bundle-worksheet/{bundle_id}")
def export_bundle_worksheet(bundle_id: str, request: Request, session: Session = Depends(get_session)):
    bundle = session.get(SceneBundle, bundle_id)
    envelope = BundleWorksheetEnvelope(
        bundle_id=bundle.bundle_id,
        scene_id=bundle.scene_id,
        chapter_id=bundle.chapter_id,
        bundle_snapshot_hash=bundle.bundle_snapshot_hash,
        snapshot=bundle.frozen_snapshot_json,
    )
    return ok(envelope.model_dump(mode="json"), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/replay/final-scene/{row_id}")
def replay_final_scene(row_id: str, request: Request, session: Session = Depends(get_session)):
    final = session.get(FinalScene, row_id)
    bundle = session.get(SceneBundle, final.source_bundle_id)
    envelope = BundleWorksheetEnvelope(
        bundle_id=bundle.bundle_id,
        scene_id=bundle.scene_id,
        chapter_id=bundle.chapter_id,
        bundle_snapshot_hash=bundle.bundle_snapshot_hash,
        snapshot=bundle.frozen_snapshot_json,
    )
    return ok(envelope.model_dump(mode="json"), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/replay/draft/{row_id}")
def replay_draft(row_id: str, request: Request, session: Session = Depends(get_session)):
    draft = session.get(SceneDraft, row_id)
    bundle = session.get(SceneBundle, draft.source_bundle_id)
    envelope = BundleWorksheetEnvelope(
        bundle_id=bundle.bundle_id,
        scene_id=bundle.scene_id,
        chapter_id=bundle.chapter_id,
        bundle_snapshot_hash=bundle.bundle_snapshot_hash,
        snapshot=bundle.frozen_snapshot_json,
    )
    return ok(envelope.model_dump(mode="json"), req_id=getattr(request.state, "request_id", None))
