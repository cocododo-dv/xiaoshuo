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


def _seed_dragon_reference_profile(session, *, status: str = "ready", unsafe: bool = False) -> None:
    book = ReferenceBook(
        book_id=DRAGON_BOOK_ID,
        title="Dragon reference sample",
        author_label="reference",
        source_kind="upload",
        source_path=None,
        file_name="dragon-reference.txt",
        cloud_policy="local_only",
        analysis_focus="style_structure",
        text_checksum="dragon-reference",
        status="completed",
        total_chars=1200,
        total_segments=4,
        stats_json={"segment_kinds": {"structure": 4}},
    )
    run = ReferenceLearningRun(
        run_id="refrun_dragon_ready",
        book_id=DRAGON_BOOK_ID,
        status="completed",
        batch_size=4,
        round_count=1,
        profile_id=DRAGON_PROFILE_ID,
    )
    round_row = ReferenceLearningRound(
        round_id="refround_dragon_ready_1",
        book_id=DRAGON_BOOK_ID,
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
        segment_id = f"refseg_dragon_{index:04d}"
        finding_id = f"reffind_dragon_{index}"
        review_id = f"review_{finding_id}"
        finding_ids.append(finding_id)
        session.add(
            ReferenceBookSegment(
                segment_id=segment_id,
                book_id=DRAGON_BOOK_ID,
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
                status="approved",
                candidate_text="Abstract craft guidance only.",
                candidate_payload_json={
                    "lineage_key": f"DRAGON_TEST_{index}",
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
                book_id=DRAGON_BOOK_ID,
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
            profile_id=DRAGON_PROFILE_ID,
            book_id=DRAGON_BOOK_ID,
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


def test_dragon_xianxia_status_reports_missing_safe_profile_blocker(client, session) -> None:
    _seed_dragon_reference_profile(session, status="stale")

    response = client.get("/api/v1/demo/dragon-xianxia/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["book_id"] == DRAGON_BOOK_ID
    assert data["ready"] is False
    assert any(blocker["code"] == "DRAGON_PROFILE_NOT_READY" for blocker in data["blockers"])


def test_dragon_xianxia_run_blocks_unsafe_profile(client, session) -> None:
    _seed_dragon_reference_profile(session, unsafe=True)

    response = client.post("/api/v1/demo/dragon-xianxia/run", json={}, headers=_headers("run-unsafe-demo"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DRAGON_DEMO_BLOCKED"
    assert "DRAGON_PROFILE_NOT_READY" in json.dumps(response.json()["error"]["details"])


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
