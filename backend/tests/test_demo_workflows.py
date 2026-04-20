from __future__ import annotations

import json

from novel_system.db.models import (
    ReferenceBook,
    ReferenceBookSegment,
    ReferenceFinding,
    ReferenceLearningRound,
    ReferenceLearningRun,
    ReferenceProfile,
    ReviewItem,
)


DRAGON_BOOK_ID = "refbook_d4ae8e00eea8"
DRAGON_PROFILE_ID = "refprofile_refbook_d4ae8e00eea8_safe"
FORBIDDEN_MARKERS = ["txt8080", "Lu Mingfei", "Cassell", "Jiang Nan", "Dragon Raja"]


def _headers(key: str) -> dict[str, str]:
    return {"X-Idempotency-Key": key, "X-Operator-Ref": "ops.demo.test"}


def _seed_dragon_reference_profile(
    session,
    *,
    book_id: str = DRAGON_BOOK_ID,
    profile_id: str | None = None,
    title: str = "Dragon reference sample",
    status: str = "ready",
    unsafe: bool = False,
    review_status: str = "approved",
) -> None:
    profile_id = profile_id or f"refprofile_{book_id}_safe"
    run_id = f"refrun_{book_id}_ready"
    round_id = f"refround_{book_id}_ready_1"
    book = ReferenceBook(
        book_id=book_id,
        title=title,
        author_label="reference",
        source_kind="upload",
        source_path=None,
        file_name=f"{title}.txt",
        cloud_policy="local_only",
        analysis_focus="style_structure",
        text_checksum=f"{book_id}-reference",
        status="completed",
        total_chars=1200,
        total_segments=4,
        stats_json={"segment_kinds": {"structure": 4}},
    )
    run = ReferenceLearningRun(
        run_id=run_id,
        book_id=book_id,
        status="completed",
        batch_size=4,
        round_count=1,
        profile_id=profile_id,
    )
    round_row = ReferenceLearningRound(
        round_id=round_id,
        book_id=book_id,
        run_id=run.run_id,
        round_index=1,
        status="completed",
    )
    session.add_all([book, run, round_row])

    finding_ids: list[str] = []
    for index, finding_type in enumerate(
        ["style_rule_set", "narrative_pattern", "banned_rule_cluster", "style_rule_set"],
        start=1,
    ):
        segment_id = f"refseg_{book_id}_{index:04d}"
        finding_id = f"reffind_{book_id}_{index}"
        review_id = f"review_{finding_id}"
        finding_ids.append(finding_id)
        session.add(
            ReferenceBookSegment(
                segment_id=segment_id,
                book_id=book_id,
                segment_index=index,
                chapter_hint=None,
                segment_kind="structure",
                text="Protected source excerpt that must not be exposed to the demo UI.",
            )
        )
        session.add(
            ReviewItem(
                review_id=review_id,
                item_type=finding_type,
                status=review_status,
                candidate_text="Abstract craft guidance only.",
                candidate_payload_json={
                    "lineage_key": f"{book_id.upper()}_TEST_{index}",
                    "text": "Abstract craft guidance only.",
                    "scope": "global",
                    "scope_ref_id": "global",
                },
                active_on_approve=0,
                materialize_status="succeeded",
            )
        )
        session.add(
            ReferenceFinding(
                finding_id=finding_id,
                book_id=book_id,
                run_id=run.run_id,
                round_id=round_row.round_id,
                segment_id=segment_id,
                review_id=review_id,
                finding_type=finding_type,
                dimension="structure",
                summary="Use abstract pressure, visible consequence, and a clean scene turn.",
                evidence_preview="Protected source excerpt that should be hidden.",
                candidate_payload_json={},
                status="approved",
            )
        )

    profile_json = {
        "style_profile": {
            "contract_version": "STYLE_FEATURE_CONTRACT_v1",
            "features": {
                "rhythm": {"guidance": ["Use compact pressure beats before emotional release."]},
                "imagery": {"guidance": ["Use sensory contrast without source wording."]},
            },
            "banned_moves": ["Do not copy protected names, settings, signature lines, or scene bridges."],
        },
        "narrative_patterns": [
            "Open with a concrete anomaly, delay explanation, then turn the scene through visible consequence."
        ],
    }
    if unsafe:
        profile_json["narrative_patterns"].append("Evidence: txt8080 Cassell Lu Mingfei")

    session.add(
        ReferenceProfile(
            profile_id=profile_id,
            book_id=book_id,
            run_id=run.run_id,
            title="Dragon reference profile",
            status=status,
            profile_json=profile_json,
            coverage_json={
                "approved_findings": len(finding_ids),
                "covered_dimensions": ["structure", "rhythm"],
                "covered_finding_types": ["style_rule_set", "narrative_pattern", "banned_rule_cluster"],
                "profile_ready": status == "ready" and not unsafe,
                "profile_stale": status != "ready" or unsafe,
            },
            source_finding_ids_json=finding_ids,
        )
    )
    session.commit()


def test_dragon_xianxia_status_supports_explicit_book_selection_and_action_payload(client, session) -> None:
    _seed_dragon_reference_profile(session)
    alternate_book_id = "refbook_dragon_alt"
    alternate_profile_id = "refprofile_dragon_alt_safe"
    _seed_dragon_reference_profile(
        session,
        book_id=alternate_book_id,
        profile_id=alternate_profile_id,
        title="Dragon alternate sample",
    )

    response = client.get(f"/api/v1/demo/dragon-xianxia/status?book_id={alternate_book_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["book_id"] == alternate_book_id
    assert data["selected_book"]["book_id"] == alternate_book_id
    assert data["selected_profile"]["profile_id"] == alternate_profile_id
    assert [profile["profile_id"] for profile in data["ready_profiles"]] == [alternate_profile_id]
    assert {book["book_id"] for book in data["candidate_books"]} >= {DRAGON_BOOK_ID, alternate_book_id}
    assert data["primary_action"]["code"] == "run_demo"
    assert data["primary_action"]["enabled"] is True
    assert data["blockers"] == []


def test_dragon_xianxia_status_classifies_stale_unsafe_and_pending_blockers(client, session) -> None:
    _seed_dragon_reference_profile(session, status="stale")

    stale_response = client.get("/api/v1/demo/dragon-xianxia/status")

    assert stale_response.status_code == 200
    stale_data = stale_response.json()["data"]
    assert stale_data["ready"] is False
    assert stale_data["primary_action"]["code"] == "regenerate_profile"
    assert any(blocker["code"] == "DRAGON_PROFILE_STALE" for blocker in stale_data["blockers"])

    session.query(ReferenceProfile).delete()
    session.query(ReferenceFinding).delete()
    session.query(ReferenceLearningRound).delete()
    session.query(ReferenceLearningRun).delete()
    session.query(ReviewItem).delete()
    session.query(ReferenceBookSegment).delete()
    session.query(ReferenceBook).delete()
    session.commit()

    _seed_dragon_reference_profile(session, unsafe=True)

    unsafe_response = client.get("/api/v1/demo/dragon-xianxia/status")

    assert unsafe_response.status_code == 200
    unsafe_data = unsafe_response.json()["data"]
    assert unsafe_data["primary_action"]["code"] == "regenerate_profile"
    assert any(blocker["code"] == "DRAGON_PROFILE_UNSAFE" for blocker in unsafe_data["blockers"])

    session.query(ReferenceProfile).delete()
    session.query(ReferenceFinding).delete()
    session.query(ReferenceLearningRound).delete()
    session.query(ReferenceLearningRun).delete()
    session.query(ReviewItem).delete()
    session.query(ReferenceBookSegment).delete()
    session.query(ReferenceBook).delete()
    session.commit()

    _seed_dragon_reference_profile(session, review_status="pending")

    pending_response = client.get("/api/v1/demo/dragon-xianxia/status")

    assert pending_response.status_code == 200
    pending_data = pending_response.json()["data"]
    assert pending_data["primary_action"]["code"] == "review_findings"
    assert any(blocker["code"] == "DRAGON_REVIEW_PENDING" for blocker in pending_data["blockers"])


def test_dragon_xianxia_status_reports_missing_safe_profile_blocker(client, session) -> None:
    _seed_dragon_reference_profile(session, status="stale")

    response = client.get("/api/v1/demo/dragon-xianxia/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["book_id"] == DRAGON_BOOK_ID
    assert data["ready"] is False
    assert any(blocker["code"] == "DRAGON_PROFILE_STALE" for blocker in data["blockers"])


def test_dragon_xianxia_run_blocks_unsafe_profile(client, session) -> None:
    _seed_dragon_reference_profile(session, unsafe=True)

    response = client.post("/api/v1/demo/dragon-xianxia/run", json={}, headers=_headers("run-unsafe-demo"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DRAGON_DEMO_BLOCKED"
    assert "DRAGON_PROFILE_UNSAFE" in json.dumps(response.json()["error"]["details"])


def test_dragon_xianxia_run_uses_explicit_book_and_profile(client, session) -> None:
    _seed_dragon_reference_profile(session)
    alternate_book_id = "refbook_dragon_alt"
    alternate_profile_id = "refprofile_dragon_alt_safe"
    _seed_dragon_reference_profile(
        session,
        book_id=alternate_book_id,
        profile_id=alternate_profile_id,
        title="Dragon alternate sample",
    )

    response = client.post(
        "/api/v1/demo/dragon-xianxia/run",
        json={"book_id": alternate_book_id, "profile_id": alternate_profile_id},
        headers=_headers("run-explicit-demo"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["book_id"] == alternate_book_id
    assert data["selected_book"]["book_id"] == alternate_book_id
    assert data["profile_id"] == alternate_profile_id
    assert data["selected_profile"]["profile_id"] == alternate_profile_id
    assert data["primary_action"]["code"] == "view_results"


def test_dragon_xianxia_run_creates_three_chapter_demo_without_source_markers(client, session) -> None:
    _seed_dragon_reference_profile(session)

    response = client.post("/api/v1/demo/dragon-xianxia/run", json={}, headers=_headers("run-safe-demo"))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["book_id"] == DRAGON_BOOK_ID
    assert data["profile_id"] == DRAGON_PROFILE_ID
    assert data["mode"] in {"live", "offline_placeholder"}
    assert data["blockers"] == []
    assert data["leakage_check"]["passed"] is True
    assert data["leakage_check"]["hits"] == []
    assert [chapter["chapter_id"] for chapter in data["chapters"]] == ["XXDEMO_CH01", "XXDEMO_CH02", "XXDEMO_CH03"]
    assert all(chapter["status"] == "completed" for chapter in data["chapters"])
    assert all(chapter["final_scene"]["content"] for chapter in data["chapters"])

    serialized = json.dumps(data, ensure_ascii=False)
    for marker in FORBIDDEN_MARKERS:
        assert marker not in serialized

    rerun = client.post("/api/v1/demo/dragon-xianxia/run", json={}, headers=_headers("run-safe-demo"))
    assert rerun.status_code == 200
    assert rerun.json()["data"]["chapters"][0]["final_scene"]["row_id"] == data["chapters"][0]["final_scene"]["row_id"]
