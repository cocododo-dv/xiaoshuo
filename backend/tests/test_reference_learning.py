from __future__ import annotations

import json
from pathlib import Path

from novel_system.db.models import (
    ChapterGoal,
    LlmCall,
    ReferenceBookSegment,
    ReferenceFinding,
    ReferenceLearningRound,
    ReviewItem,
    SceneCard,
    SceneRunState,
)
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.llm_client import LLMResponse
from novel_system.services.reference_learning import ReferenceLearningService, _sanitize_reference_profile_text
from novel_system.services.versioning.review_materialization import ReviewMaterializationService


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def _idempotency_headers(key: str) -> dict[str, str]:
    return {"X-Idempotency-Key": key, "X-Operator-Ref": "ops.reference.e2e"}


def _book_text() -> str:
    return """
# 第一章 雨夜来信

雨砸在窗台上，像有人用细小的指节敲门。少年把灯关掉，房间里只剩下电脑屏幕的蓝光。

“你听见了吗？”她问。

他没有回答。信封躺在桌面中央，火漆还湿，像刚从另一个世界递出来。

门外的脚步声停住了。走廊灯闪了三下，黑暗把墙面推得很近。

# 第二章 钟楼之后

他们穿过空教室，粉笔灰在月光里悬着。每一步都像踩在一段旧誓言上。

“现在后悔还来得及。”他说。

女孩笑了一下，笑意很轻，像刀背掠过水面。

钟声响起的时候，所有窗户同时亮了。城市在远处翻身，露出藏在皮肤下面的鳞。

# 第三章 余烬

风从天台边缘卷上来，把烧焦的纸片吹成一场黑雪。

他终于明白，所谓邀请从来不是选择，而是判决。

她把钥匙放进他掌心，没有解释，也没有告别。
""".strip()


def _many_reference_text(segment_count: int) -> str:
    return "\n\n".join(
        [
            (
                f"Scene {index}: The corridor light clicked twice, then held its breath. "
                "A character noticed the silence before anyone explained it, and the room "
                "shifted through gesture, pressure, and a delayed emotional release."
            )
            for index in range(1, segment_count + 1)
        ]
    )


def _import_reference_book(client, tmp_path: Path) -> str:
    book_path = tmp_path / "reference-book.md"
    book_path.write_text(_book_text(), encoding="utf-8")
    response = client.post(
        "/api/v1/reference-books/import-path",
        json={
            "file_path": str(book_path),
            "title": "雨夜参考书",
            "author_label": "reference",
            "cloud_policy": "allow_full_cloud",
            "analysis_focus": "style_structure",
        },
        headers=_idempotency_headers("import-reference-book"),
    )
    assert response.status_code == 200
    return response.json()["data"]["book_id"]


def _start_and_advance(client, book_id: str) -> dict:
    run_response = client.post(
        f"/api/v1/reference-books/{book_id}/runs",
        json={"batch_size": 8},
        headers=_idempotency_headers("start-reference-run"),
    )
    assert run_response.status_code == 200
    run_id = run_response.json()["data"]["run"]["run_id"]

    advance_response = client.post(
        f"/api/v1/reference-books/{book_id}/runs/{run_id}/advance",
        json={},
        headers=_idempotency_headers("advance-reference-run-1"),
    )
    assert advance_response.status_code == 200
    return advance_response.json()["data"]


class FakeReferenceLlmClient:
    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if request.node_id == "reference_sample_ranker":
            output = {
                "selections": [
                    {
                        "segment_id": f"refseg_refbook_llm_000{index}",
                        "dimension": "ranked",
                        "reason": "representative craft sample",
                        "risk_note": "abstract only",
                    }
                    for index in range(1, 6)
                ]
            }
        elif request.node_id == "reference_style_structure_extract":
            extract_index = sum(1 for item in self.requests if item.node_id == "reference_style_structure_extract")
            specs = [
                (
                    "style_rule_set",
                    "llm rhythm",
                    "LLM style rule: use pressure beats before release.",
                ),
                (
                    "narrative_pattern",
                    "llm chapter hook",
                    "LLM narrative pattern: delay explanation until a visible consequence lands.",
                ),
                (
                    "style_observation",
                    "llm imagery",
                    "LLM style observation: anchor tension in tactile details.",
                ),
                (
                    "banned_rule_cluster",
                    "llm banned move",
                    "LLM banned rule: do not copy names, settings, or source phrasing.",
                ),
                (
                    "calibration_candidate",
                    "llm calibration",
                    "LLM calibration: keep the reference as abstract craft guidance.",
                ),
            ]
            item_type, dimension, summary = specs[(extract_index - 1) % len(specs)]
            output = {
                "item_type": item_type,
                "dimension": dimension,
                "summary": summary,
                "transferable_rule": "Delay explanation until consequence changes the scene.",
                "banned_replication_rule": "Do not copy names, settings, or source phrasing.",
                "confidence": 0.91,
            }
        elif request.node_id == "reference_profile_synthesize":
            output = {
                "profile_title": "LLM reference profile",
                "style_features": ["Use pressure beats before release."],
                "narrative_patterns": ["LLM synthesized hook escalation."],
                "calibration_guidance": ["Keep calibration abstract."],
                "banned_replication_rules": ["Do not copy proper nouns or signature scenes."],
            }
        else:
            output = {}
        return LLMResponse(
            request_id=f"fake_{request.node_id}_{len(self.requests)}",
            provider="fake",
            model=request.model,
            text="{}",
            structured_output=output,
            response_format=request.response_format,
            raw_response={"id": f"fake_{request.node_id}_{len(self.requests)}", "model": request.model},
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )


class LeakyReferenceLlmClient(FakeReferenceLlmClient):
    def generate(self, request):
        self.requests.append(request)
        if request.node_id == "reference_sample_ranker":
            output = {
                "selections": [
                    {
                        "segment_id": f"refseg_refbook_llm_000{index}",
                        "dimension": "ranked",
                        "reason": "representative craft sample",
                        "risk_note": "abstract only",
                    }
                    for index in range(1, 6)
                ]
            }
        elif request.node_id == "reference_style_structure_extract":
            specs = [
                (
                    "style_rule_set",
                    "rhythm",
                    "Use compressed pressure beats. Evidence: 声明：本书为八零电子书(txt8080.com)的用户上传至本站的存储空间，路明非站在卡塞尔学院门口。",
                ),
                (
                    "narrative_pattern",
                    "chapter hook",
                    "Open with an anomaly. Evidence pattern: 楚子航与江南笔下的卡塞尔雨夜桥段不可复用。",
                ),
                (
                    "style_observation",
                    "imagery",
                    "Use sensory contrast without copying names.",
                ),
                (
                    "banned_rule_cluster",
                    "banned move",
                    "Do not copy protected expression, names, or settings.",
                ),
                (
                    "calibration_candidate",
                    "calibration",
                    "Keep the reference abstract.",
                ),
            ]
            index = sum(1 for item in self.requests if item.node_id == "reference_style_structure_extract") - 1
            item_type, dimension, summary = specs[index % len(specs)]
            output = {
                "item_type": item_type,
                "dimension": dimension,
                "summary": summary,
                "transferable_rule": summary,
                "banned_replication_rule": "Do not copy 龙族, 路明非, 楚子航, 卡塞尔, or 江南.",
                "confidence": 0.92,
            }
        elif request.node_id == "reference_profile_synthesize":
            output = {
                "profile_title": "Leaky reference profile",
                "style_features": [
                    "Use short pressure beats. Evidence: 声明：本书为八零电子书(txt8080.com)的用户上传至本站，路明非收到卡塞尔学院来信。",
                    "Use sensory contrast without copying source wording.",
                ],
                "narrative_patterns": [
                    "Delay explanation until consequence lands. Evidence pattern: 楚子航在雨夜推进江南式桥段。",
                ],
                "calibration_guidance": [
                    "Calibrate toward 龙族·火之晨曦 江南 著 without reusing names.",
                ],
                "banned_replication_rules": [
                    "Do not copy 卡塞尔, 路明非, 楚子航, 江南, txt8080, or any source scene.",
                ],
            }
        else:
            output = {}
        return LLMResponse(
            request_id=f"fake_{request.node_id}_{len(self.requests)}",
            provider="fake",
            model=request.model,
            text="{}",
            structured_output=output,
            response_format=request.response_format,
            raw_response={"id": f"fake_{request.node_id}_{len(self.requests)}", "model": request.model},
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )


def test_import_path_decodes_gb18030_and_segments_chapters(client, tmp_path: Path) -> None:
    book_path = tmp_path / "gb-book.txt"
    book_path.write_bytes(_book_text().encode("gb18030"))

    response = client.post(
        "/api/v1/reference-books/import-path",
        json={
            "file_path": str(book_path),
            "title": "GB Book",
            "cloud_policy": "allow_full_cloud",
            "analysis_focus": "style_structure",
        },
        headers=_idempotency_headers("import-gb-book"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["book"]["title"] == "GB Book"
    assert data["book"]["cloud_policy"] == "allow_full_cloud"
    assert data["stats"]["total_segments"] >= 5
    assert data["stats"]["segment_kinds"]["opening"] >= 1
    assert data["stats"]["segment_kinds"]["dialogue"] >= 1
    assert data["stats"]["segment_kinds"]["imagery"] >= 1

    detail = client.get(f"/api/v1/reference-books/{data['book']['book_id']}")
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["coverage"]["approved_findings"] == 0
    assert detail_data["book"]["analysis_focus"] == "style_structure"


def test_import_path_rejects_empty_and_url_sources(client, tmp_path: Path) -> None:
    empty_path = tmp_path / "empty.txt"
    empty_path.write_text("   \n", encoding="utf-8")

    empty_response = client.post(
        "/api/v1/reference-books/import-path",
        json={"file_path": str(empty_path), "cloud_policy": "allow_full_cloud"},
        headers=_idempotency_headers("import-empty-book"),
    )
    assert empty_response.status_code == 400
    assert empty_response.json()["error"]["code"] == "REFERENCE_BOOK_EMPTY"

    url_response = client.post(
        "/api/v1/reference-books/import-path",
        json={"file_path": "https://example.com/book.txt", "cloud_policy": "allow_full_cloud"},
        headers=_idempotency_headers("import-url-book"),
    )
    assert url_response.status_code == 400
    assert url_response.json()["error"]["code"] == "REFERENCE_BOOK_PATH_UNSUPPORTED"


def test_learning_run_pauses_for_review_then_completes_profile(client, tmp_path: Path) -> None:
    book_id = _import_reference_book(client, tmp_path)
    first_advance = _start_and_advance(client, book_id)

    assert first_advance["run"]["status"] == "waiting_review"
    findings = first_advance["round"]["findings"]
    assert 5 <= len(findings) <= 8
    assert {"style_rule_set", "style_observation", "narrative_pattern"} <= {
        finding["review"]["item_type"] for finding in findings
    }
    assert all(finding["source_excerpt_hidden"] is True for finding in findings)
    assert all(finding["source_segment"]["preview"] is None for finding in findings)
    assert all(finding["source_segment"]["chapter_hint"] is None for finding in findings)
    assert all(finding["source_segment"]["display_label"] for finding in findings)

    run_id = first_advance["run"]["run_id"]
    waiting_again = client.post(
        f"/api/v1/reference-books/{book_id}/runs/{run_id}/advance",
        json={},
        headers=_idempotency_headers("advance-reference-run-still-waiting"),
    )
    assert waiting_again.status_code == 200
    assert waiting_again.json()["data"]["run"]["status"] == "waiting_review"
    assert waiting_again.json()["data"]["round"]["round_id"] == first_advance["round"]["round_id"]

    for index, finding in enumerate(findings):
        review_id = finding["review"]["review_id"]
        if index == 0:
            reject = client.post(
                f"/api/v1/review-items/{review_id}/reject",
                json={"reason": "样本重复，暂不采纳"},
                headers=_idempotency_headers(f"reject-reference-review-{index}"),
            )
            assert reject.status_code == 200
        else:
            approve = client.post(
                f"/api/v1/review-items/{review_id}/approve",
                json={},
                headers=_idempotency_headers(f"approve-reference-review-{index}"),
            )
            assert approve.status_code == 200

    completed = client.post(
        f"/api/v1/reference-books/{book_id}/runs/{run_id}/advance",
        json={},
        headers=_idempotency_headers("advance-reference-run-complete"),
    )
    assert completed.status_code == 200
    data = completed.json()["data"]
    if data["run"]["coverage"]["learning_complete"]:
        assert data["run"]["status"] == "completed"
        profile = data["profile"]
    else:
        assert data["run"]["status"] == "waiting_review"
        assert data["run"]["coverage"]["learning_complete"] is False
        assert data["run"]["coverage"]["pending_findings"] > 0
        assert "round" in data
        detail = client.get(f"/api/v1/reference-books/{book_id}")
        assert detail.status_code == 200
        profile = detail.json()["data"]["profiles"][0]
    assert profile["status"] == "ready"
    assert profile["coverage"]["approved_findings"] >= 4
    assert "style_profile" in profile["profile_json"]
    assert "narrative_patterns" in profile["profile_json"]


def test_reference_finding_response_hides_source_excerpt_by_default(client, tmp_path: Path) -> None:
    book_id = _import_reference_book(client, tmp_path)
    first_advance = _start_and_advance(client, book_id)

    finding = first_advance["round"]["findings"][0]

    assert finding["source_excerpt_hidden"] is True
    assert finding["evidence_preview"] is None
    assert finding["source_segment"]["preview"] is None
    assert finding["source_segment"]["chapter_hint"] is None
    assert "片段" in finding["source_segment"]["display_label"]
    assert not finding["source_segment"]["display_label"].endswith("segment")
    assert finding["source_segment"]["segment_kind"]
    assert finding["summary"]
    assert _has_cjk(finding["summary"])


def test_reference_learning_profile_ready_still_allows_more_unsampled_segments(session, tmp_path: Path) -> None:
    book_path = tmp_path / "many-reference.md"
    book_path.write_text(_many_reference_text(12), encoding="utf-8")
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="Many Reference",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    book_id = imported["book_id"]
    run = service.start_run(book_id, batch_size=5)["run"]
    first_advance = service.advance_run(book_id, run["run_id"])
    first_segment_ids = {
        finding["source_segment"]["segment_id"]
        for finding in first_advance["round"]["findings"]
    }

    review_service = ReviewMaterializationService(session)
    for finding in first_advance["round"]["findings"]:
        review_service.materialize_review(finding["review"]["review_id"])

    ready_coverage = service.coverage_for_run(run["run_id"])
    assert ready_coverage["ready"] is True
    assert ready_coverage["sampled_segments"] == 5
    assert ready_coverage["eligible_segments"] == 12
    assert ready_coverage["remaining_segments"] == 7
    assert ready_coverage["sample_coverage_score"] < 1
    assert ready_coverage["dimension_coverage_score"] == ready_coverage["coverage_score"]
    assert ready_coverage["learning_complete"] is False
    assert ready_coverage["next_round_available"] is True

    continuation = service.advance_run(book_id, run["run_id"])
    assert continuation["run"]["status"] == "waiting_review"
    assert "round" in continuation
    second_segment_ids = {
        finding["source_segment"]["segment_id"]
        for finding in continuation["round"]["findings"]
    }
    assert first_segment_ids.isdisjoint(second_segment_ids)

    detail = service.detail(book_id)
    assert detail["profiles"]
    assert detail["profiles"][0]["status"] == "ready"
    assert detail["latest_run"]["coverage"]["profile_ready"] is True
    assert detail["latest_run"]["coverage"]["learning_complete"] is False


def test_reference_learning_uses_round_ledger_to_skip_partially_created_round_segments(
    session,
    tmp_path: Path,
) -> None:
    book_path = tmp_path / "partial-round-reference.md"
    book_path.write_text(_many_reference_text(10), encoding="utf-8")
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="Partial Round Reference",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    book_id = imported["book_id"]
    run = service.start_run(book_id, batch_size=5)["run"]
    first_segment_ids = [
        segment.segment_id
        for segment in session.query(ReferenceBookSegment)
        .filter(ReferenceBookSegment.book_id == book_id)
        .order_by(ReferenceBookSegment.segment_index.asc())
        .limit(5)
        .all()
    ]
    session.add(
        ReferenceLearningRound(
            round_id=f"refround_{run['run_id']}_1",
            book_id=book_id,
            run_id=run["run_id"],
            round_index=1,
            status="completed",
            segment_ids_json=first_segment_ids,
            finding_ids_json=[],
        )
    )
    run_row = service._run(book_id, run["run_id"])
    run_row.round_count = 1
    session.flush()

    coverage = service.coverage_for_run(run["run_id"])
    assert coverage["sampled_segments"] == 5
    assert coverage["remaining_segments"] == 5

    continuation = service.advance_run(book_id, run["run_id"])
    second_segment_ids = {
        finding["source_segment"]["segment_id"]
        for finding in continuation["round"]["findings"]
    }
    assert second_segment_ids
    assert second_segment_ids.isdisjoint(first_segment_ids)


def test_reference_learning_skips_segments_attempted_by_earlier_runs(
    session,
    tmp_path: Path,
) -> None:
    book_path = tmp_path / "cross-run-reference.md"
    book_path.write_text(_many_reference_text(12), encoding="utf-8")
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="Cross Run Reference",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    book_id = imported["book_id"]
    first_run = service.start_run(book_id, batch_size=5)["run"]
    first_advance = service.advance_run(book_id, first_run["run_id"])
    first_segment_ids = {
        finding["source_segment"]["segment_id"]
        for finding in first_advance["round"]["findings"]
    }

    for segment_id in first_segment_ids:
        segment = session.get(ReferenceBookSegment, segment_id)
        segment.selected_count = 0
    session.flush()

    second_run = service.start_run(book_id, batch_size=5)["run"]
    second_advance = service.advance_run(book_id, second_run["run_id"])
    second_segment_ids = {
        finding["source_segment"]["segment_id"]
        for finding in second_advance["round"]["findings"]
    }
    assert second_segment_ids
    assert second_segment_ids.isdisjoint(first_segment_ids)


def test_reference_learning_advance_reuses_waiting_round_without_findings(
    session,
    tmp_path: Path,
) -> None:
    book_path = tmp_path / "duplicate-advance-reference.md"
    book_path.write_text(_many_reference_text(8), encoding="utf-8")
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="Duplicate Advance Reference",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    book_id = imported["book_id"]
    run = service.start_run(book_id, batch_size=5)["run"]
    first_segment_ids = [
        segment.segment_id
        for segment in session.query(ReferenceBookSegment)
        .filter(ReferenceBookSegment.book_id == book_id)
        .order_by(ReferenceBookSegment.segment_index.asc())
        .limit(5)
        .all()
    ]
    session.add(
        ReferenceLearningRound(
            round_id=f"refround_{run['run_id']}_1",
            book_id=book_id,
            run_id=run["run_id"],
            round_index=1,
            status="waiting_review",
            segment_ids_json=first_segment_ids,
            finding_ids_json=[],
        )
    )
    session.flush()

    replayed = service.advance_run(book_id, run["run_id"])
    assert replayed["round"]["round_index"] == 1
    assert replayed["round"]["findings"] == []
    assert session.query(ReferenceLearningRound).filter(ReferenceLearningRound.run_id == run["run_id"]).count() == 1


def test_reference_learning_filters_front_matter_synopsis_and_epigraph_from_candidates(
    session,
    tmp_path: Path,
) -> None:
    book_path = tmp_path / "front-matter-candidates.txt"
    book_path.write_text(
        "\n\n".join(
            [
                "《Example》合集\n包含《Example One》《Example Two》\nSomeone 著",
                "内容简介：\n《Example One》：A plain marketing synopsis that explains the plot instead of showing craft.",
                "Example·First Dawn\nSomeone 著",
                "When you feel most lonely and desperate,\nthere will be a door open for you.",
                *_many_reference_text(5).split("\n\n"),
            ]
        ),
        encoding="utf-8",
    )
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="Front Matter Candidates",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    run = service.start_run(imported["book_id"], batch_size=5)["run"]
    first_advance = service.advance_run(imported["book_id"], run["run_id"])

    selected_segment_ids = [finding["source_segment"]["segment_id"] for finding in first_advance["round"]["findings"]]
    selected_segments = session.query(ReferenceBookSegment).filter(ReferenceBookSegment.segment_id.in_(selected_segment_ids)).all()
    selected_text = "\n".join(segment.text for segment in selected_segments)
    assert "合集" not in selected_text
    assert "内容简介" not in selected_text
    assert "Someone 著" not in selected_text
    assert "When you feel most lonely" not in selected_text
    assert service.coverage_for_run(run["run_id"])["eligible_segments"] == 5


def test_reference_learning_completes_only_after_all_analysis_worthy_segments_sampled(session, tmp_path: Path) -> None:
    book_path = tmp_path / "small-reference.md"
    book_path.write_text(_many_reference_text(5), encoding="utf-8")
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="Small Reference",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    book_id = imported["book_id"]
    run = service.start_run(book_id, batch_size=5)["run"]
    first_advance = service.advance_run(book_id, run["run_id"])

    review_service = ReviewMaterializationService(session)
    for finding in first_advance["round"]["findings"]:
        review_service.materialize_review(finding["review"]["review_id"])

    completed = service.advance_run(book_id, run["run_id"])
    assert completed["run"]["status"] == "completed"
    assert completed["profile"]["status"] == "ready"
    assert completed["run"]["coverage"]["sampled_segments"] == 5
    assert completed["run"]["coverage"]["eligible_segments"] == 5
    assert completed["run"]["coverage"]["remaining_segments"] == 0
    assert completed["run"]["coverage"]["sample_coverage_score"] == 1
    assert completed["run"]["coverage"]["learning_complete"] is True
    assert completed["run"]["coverage"]["next_round_available"] is False


def test_reference_segment_excerpt_is_loaded_on_demand_and_blocks_invalid_sources(
    client,
    session,
    tmp_path: Path,
) -> None:
    book_id = _import_reference_book(client, tmp_path)
    first_advance = _start_and_advance(client, book_id)
    finding = first_advance["round"]["findings"][0]
    segment_id = finding["source_segment"]["segment_id"]

    assert finding["source_excerpt_hidden"] is True
    assert finding["source_segment"]["preview"] is None

    excerpt_response = client.get(f"/api/v1/reference-books/{book_id}/segments/{segment_id}/excerpt")
    assert excerpt_response.status_code == 200
    excerpt = excerpt_response.json()["data"]
    assert excerpt["segment_id"] == segment_id
    assert excerpt["display_label"]
    assert excerpt["source_visibility"] == "review_only"
    assert excerpt["max_chars"] == 800
    assert 0 < len(excerpt["excerpt"]) <= 800
    assert "仅供审核" in excerpt["safety_note"]

    second_book_path = tmp_path / "second-reference.md"
    second_book_path.write_text(_many_reference_text(5), encoding="utf-8")
    second = client.post(
        "/api/v1/reference-books/import-path",
        json={
            "file_path": str(second_book_path),
            "title": "Second Reference",
            "author_label": "reference",
            "cloud_policy": "local_only",
            "analysis_focus": "style_structure",
        },
        headers=_idempotency_headers("import-second-reference-book"),
    )
    assert second.status_code == 200
    wrong_book_id = second.json()["data"]["book_id"]
    wrong_book_response = client.get(f"/api/v1/reference-books/{wrong_book_id}/segments/{segment_id}/excerpt")
    assert wrong_book_response.status_code == 404

    boilerplate_path = tmp_path / "boilerplate-reference.md"
    boilerplate_path.write_text(
        "\n\n".join(
            [
                "txt8080 http://example.com copyright notice only, please support the original author.",
                *_many_reference_text(5).split("\n\n"),
            ]
        ),
        encoding="utf-8",
    )
    boilerplate = client.post(
        "/api/v1/reference-books/import-path",
        json={
            "file_path": str(boilerplate_path),
            "title": "Boilerplate Reference",
            "author_label": "reference",
            "cloud_policy": "local_only",
            "analysis_focus": "style_structure",
        },
        headers=_idempotency_headers("import-boilerplate-excerpt-book"),
    )
    assert boilerplate.status_code == 200
    boilerplate_book_id = boilerplate.json()["data"]["book_id"]
    boilerplate_segment = (
        session.query(ReferenceBookSegment)
        .filter(
            ReferenceBookSegment.book_id == boilerplate_book_id,
            ReferenceBookSegment.segment_kind == "boilerplate",
        )
        .first()
    )
    assert boilerplate_segment is not None
    blocked_response = client.get(
        f"/api/v1/reference-books/{boilerplate_book_id}/segments/{boilerplate_segment.segment_id}/excerpt"
    )
    assert blocked_response.status_code == 404

    front_matter_path = tmp_path / "front-matter-reference.md"
    front_matter_path.write_text(
        "\n\n".join(
            [
                "《Example》合集 包含《Example One》《Example Two》 Someone 著",
                *_many_reference_text(5).split("\n\n"),
            ]
        ),
        encoding="utf-8",
    )
    front_matter_import = client.post(
        "/api/v1/reference-books/import-path",
        json={
            "file_path": str(front_matter_path),
            "title": "Front Matter Reference",
            "author_label": "reference",
            "cloud_policy": "local_only",
            "analysis_focus": "style_structure",
        },
        headers=_idempotency_headers("import-front-matter-excerpt-book"),
    )
    assert front_matter_import.status_code == 200
    front_matter_book_id = front_matter_import.json()["data"]["book_id"]
    front_matter_segment = (
        session.query(ReferenceBookSegment)
        .filter(
            ReferenceBookSegment.book_id == front_matter_book_id,
            ReferenceBookSegment.text.like("%合集%"),
        )
        .first()
    )
    assert front_matter_segment is not None
    blocked_front_matter = client.get(
        f"/api/v1/reference-books/{front_matter_book_id}/segments/{front_matter_segment.segment_id}/excerpt"
    )
    assert blocked_front_matter.status_code == 404
    front_matter_detail = client.get(f"/api/v1/reference-books/{front_matter_book_id}")
    assert front_matter_detail.status_code == 200
    assert front_matter_detail.json()["data"]["coverage"]["eligible_segments"] == 5


def test_reference_finding_sanitizes_llm_source_markers_before_review(session, tmp_path: Path) -> None:
    book_path = tmp_path / "leaky-reference.md"
    book_path.write_text(_book_text(), encoding="utf-8")
    service = ReferenceLearningService(session, llm_client=LeakyReferenceLlmClient())

    imported = service.import_path(
        file_path=str(book_path),
        title="龙族[1-3部全].txt",
        author_label="reference",
        cloud_policy="allow_full_cloud",
        analysis_focus="style_structure",
    )
    run = service.start_run(imported["book_id"], batch_size=5)["run"]
    first_advance = service.advance_run(imported["book_id"], run["run_id"])

    findings = first_advance["round"]["findings"]
    assert findings
    serialized_findings = json.dumps(findings, ensure_ascii=False)
    for marker in ["Evidence:", "Evidence pattern:", "txt8080", "声明：本书", "路明非", "楚子航", "卡塞尔", "江南", "龙族"]:
        assert marker not in serialized_findings

    for finding in findings:
        review = session.get(ReviewItem, finding["review"]["review_id"])
        assert review is not None
        serialized_review = json.dumps(
            {
                "candidate_text": review.candidate_text,
                "candidate_payload_json": review.candidate_payload_json,
            },
            ensure_ascii=False,
        )
        assert "safety_notes" in review.candidate_payload_json
        assert review.candidate_payload_json["safety_notes"]["source_excerpt_hidden"] is True
        assert review.candidate_payload_json["safety_notes"]["stripped_count"] >= 0
        for marker in ["Evidence:", "Evidence pattern:", "txt8080", "声明：本书", "路明非", "楚子航", "卡塞尔", "江南", "龙族"]:
            assert marker not in serialized_review


def test_reference_finding_serializer_sanitizes_legacy_raw_review_rows(session, tmp_path: Path) -> None:
    book_path = tmp_path / "legacy-reference.md"
    book_path.write_text(_book_text(), encoding="utf-8")
    service = ReferenceLearningService(session, llm_client=LeakyReferenceLlmClient())

    imported = service.import_path(
        file_path=str(book_path),
        title="龙族[1-3部全].txt",
        author_label="reference",
        cloud_policy="allow_full_cloud",
        analysis_focus="style_structure",
    )
    run = service.start_run(imported["book_id"], batch_size=5)["run"]
    first_advance = service.advance_run(imported["book_id"], run["run_id"])
    finding_id = first_advance["round"]["findings"][0]["finding_id"]
    review_id = first_advance["round"]["findings"][0]["review"]["review_id"]

    raw_summary = (
        "Evidence: 路明非 joins 卡塞尔 after a dragon attack tied to the Japanese branch, "
        "Soviet dissolution, and roller coaster imagery."
    )
    finding = session.get(ReferenceFinding, finding_id)
    review = session.get(ReviewItem, review_id)
    assert finding is not None
    assert review is not None
    finding.summary = raw_summary
    review.candidate_text = raw_summary
    review.candidate_payload_json = {
        "source": "reference_book_learning",
        "lineage_key": "refbook_legacy_safe_output",
        "text": raw_summary,
        "profile_title": "龙族[1-3部全].txt reference profile",
        "narrative_patterns": [raw_summary],
        "safety_notes": {
            "source_excerpt_hidden": True,
            "stripped_count": 1,
            "blocked_markers": ["龙族", "路明非"],
        },
    }
    session.flush()

    serialized = service.serialize_finding(finding)
    serialized_json = json.dumps(serialized, ensure_ascii=False)
    for marker in [
        "Evidence:",
        "路明非",
        "卡塞尔",
        "龙族",
        "dragon",
        "Japanese branch",
        "Soviet",
        "roller coaster",
    ]:
        assert marker not in serialized_json
    assert serialized["source_segment"]["chapter_hint"] is None
    assert "片段" in serialized["source_segment"]["display_label"]
    assert "segment" not in serialized["source_segment"]["display_label"]
    assert serialized["review"]["candidate_payload_json"]["lineage_key"] == "refbook_legacy_safe_output"
    assert serialized["review"]["candidate_payload_json"]["safety_notes"]["source_excerpt_hidden"] is True


def test_reference_finding_serializer_localizes_legacy_english_summary_for_chinese_reference(
    session,
    tmp_path: Path,
) -> None:
    book_path = tmp_path / "legacy-english-reference.md"
    book_path.write_text(_book_text(), encoding="utf-8")
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="雨夜参考书",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    run = service.start_run(imported["book_id"], batch_size=5)["run"]
    first_advance = service.advance_run(imported["book_id"], run["run_id"])
    finding_id = first_advance["round"]["findings"][0]["finding_id"]
    finding = session.get(ReferenceFinding, finding_id)
    assert finding is not None

    finding.summary = (
        "The opening segment uses a catalog-like structure to introduce the series, "
        "which may disrupt the reader's immersion."
    )
    session.flush()

    serialized = service.serialize_finding(finding)

    assert _has_cjk(serialized["summary"])
    assert "The opening segment" not in serialized["summary"]
    assert "catalog-like" not in serialized["summary"]
    assert "片段" in serialized["source_segment"]["display_label"]
    assert "segment" not in serialized["source_segment"]["display_label"]


def test_review_reject_marks_status_and_does_not_materialize(client, session) -> None:
    create = client.post(
        "/api/v1/review-items",
        json={
            "review_id": "review_reject_reference_style",
            "item_type": "style_rule_set",
            "candidate_text": "Use short beats before a long emotional release.",
            "candidate_payload_json": {
                "lineage_key": "REF_REJECT_STYLE",
                "content": "Use short beats before a long emotional release.",
                "scope": "global",
                "scope_ref_id": "global",
            },
            "active_on_approve": 0,
        },
        headers=_idempotency_headers("create-review-to-reject"),
    )
    assert create.status_code == 200

    reject = client.post(
        "/api/v1/review-items/review_reject_reference_style/reject",
        json={"reason": "不是这本书的核心特征"},
        headers=_idempotency_headers("reject-review-to-reject"),
    )
    assert reject.status_code == 200
    data = reject.json()["data"]
    assert data["review_id"] == "review_reject_reference_style"
    assert data["status"] == "rejected"
    assert data["materialize_status"] == "pending"
    assert data["approved_item_row_id"] is None


def test_apply_profile_creates_scoped_reviews_and_bundle_uses_released_narrative_pattern(
    client,
    session,
    tmp_path: Path,
) -> None:
    book_id = _import_reference_book(client, tmp_path)
    first_advance = _start_and_advance(client, book_id)
    run_id = first_advance["run"]["run_id"]

    for index, finding in enumerate(first_advance["round"]["findings"]):
        client.post(
            f"/api/v1/review-items/{finding['review']['review_id']}/approve",
            json={},
            headers=_idempotency_headers(f"approve-apply-reference-review-{index}"),
        )

    completed = client.post(
        f"/api/v1/reference-books/{book_id}/runs/{run_id}/advance",
        json={},
        headers=_idempotency_headers("advance-apply-reference-run-complete"),
    )
    completed_data = completed.json()["data"]
    if "profile" in completed_data:
        profile_id = completed_data["profile"]["profile_id"]
    else:
        detail_for_profile = client.get(f"/api/v1/reference-books/{book_id}")
        assert detail_for_profile.status_code == 200
        profile_id = detail_for_profile.json()["data"]["profiles"][0]["profile_id"]

    apply_response = client.post(
        f"/api/v1/reference-books/{book_id}/profiles/{profile_id}/apply",
        json={"scope": "chapter", "scope_ref_id": "CHREF"},
        headers=_idempotency_headers("apply-reference-profile"),
    )
    assert apply_response.status_code == 200
    apply_data = apply_response.json()["data"]
    assert apply_data["applied"] is False
    assert {item["item_type"] for item in apply_data["reviews"]} >= {"style_rule_set", "narrative_pattern"}
    assert all(item["status"] == "pending" for item in apply_data["reviews"])
    assert apply_data["application_status"]["total"] == len(apply_data["reviews"])
    assert apply_data["application_status"]["pending"] == len(apply_data["reviews"])
    assert apply_data["application_status"]["approved"] == 0
    assert apply_data["application_status"]["rejected"] == 0
    assert apply_data["application_status"]["scope"] == "chapter"
    assert apply_data["application_status"]["scope_ref_id"] == "CHREF"
    assert set(apply_data["application_status"]["review_ids"]) == {
        item["review_id"] for item in apply_data["reviews"]
    }

    detail = client.get(f"/api/v1/reference-books/{book_id}")
    assert detail.status_code == 200
    applied_profile = next(
        item
        for item in detail.json()["data"]["profiles"]
        if item["profile_id"] == profile_id
    )
    assert applied_profile["application_status"]["pending"] == len(apply_data["reviews"])
    assert set(applied_profile["application_status"]["review_ids"]) == {
        item["review_id"] for item in apply_data["reviews"]
    }

    narrative_review = next(item for item in apply_data["reviews"] if item["item_type"] == "narrative_pattern")
    approve = client.post(
        f"/api/v1/review-items/{narrative_review['review_id']}/approve",
        json={},
        headers=_idempotency_headers("approve-applied-narrative-pattern"),
    )
    assert approve.status_code == 200
    release = client.post(
        f"/api/v1/review-items/{narrative_review['review_id']}/release",
        json={},
        headers=_idempotency_headers("release-applied-narrative-pattern"),
    )
    assert release.status_code == 200

    session.add(
        ChapterGoal(
            chapter_id="CHREF",
            planned_scene_count=1,
            chapter_goal="Use the reference structure without copying protected expression.",
        )
    )
    session.add(
        SceneCard(
            scene_id="CHREF_SC01",
            chapter_id="CHREF",
            scene_seq=1,
            onstage_chars_json=[],
            scene_goal="Test reference narrative pattern injection.",
        )
    )
    session.add(SceneRunState(scene_id="CHREF_SC01"))
    session.commit()

    bundle = BundleBuilder(session).build("CHREF_SC01")["snapshot"]
    assert "narrative_pattern_ids" in bundle["source_version_refs"]
    assert "章节钩子" in bundle["inline_digests"]["narrative_pattern"]


def test_llm_enabled_reference_learning_uses_ranker_extractor_and_profile_synthesizer(session, tmp_path: Path) -> None:
    book_path = tmp_path / "llm-reference.md"
    book_path.write_text(_book_text(), encoding="utf-8")
    fake_client = FakeReferenceLlmClient()
    service = ReferenceLearningService(session, llm_client=fake_client)

    imported = service.import_path(
        file_path=str(book_path),
        title="LLM Reference",
        author_label="reference",
        cloud_policy="allow_full_cloud",
        analysis_focus="style_structure",
    )
    book_id = imported["book_id"]
    run = service.start_run(book_id, batch_size=5)["run"]
    first_advance = service.advance_run(book_id, run["run_id"])

    assert first_advance["round"]["findings"]
    assert fake_client.requests[0].node_id == "reference_sample_ranker"
    assert {
        request.node_id for request in fake_client.requests
    } >= {"reference_sample_ranker", "reference_style_structure_extract"}
    finding_types = {finding["finding_type"] for finding in first_advance["round"]["findings"]}
    assert {"style_rule_set", "narrative_pattern", "style_observation"} <= finding_types
    assert first_advance["round"]["findings"][0]["model_trace"]["provider"] == "fake"
    assert first_advance["round"]["findings"][0]["model_trace"]["node_id"] == "reference_style_structure_extract"
    first_summary = first_advance["round"]["findings"][0]["summary"]
    assert _has_cjk(first_summary)
    assert not first_summary.startswith("LLM style rule")
    style_request = next(
        request for request in fake_client.requests if request.node_id == "reference_style_structure_extract"
    )
    assert '"locale_hint": "zh"' in style_request.messages[1]["content"]
    assert "中文" in style_request.messages[1]["content"]

    review_service = ReviewMaterializationService(session)
    for finding in first_advance["round"]["findings"]:
        review_service.materialize_review(finding["review"]["review_id"])

    advanced = service.advance_run(book_id, run["run_id"])
    profile = advanced.get("profile") or service.detail(book_id)["profiles"][0]
    assert profile["profile_json"]["narrative_patterns"] == ["LLM synthesized hook escalation."]
    assert profile["model_trace"]["provider"] == "fake"
    assert profile["model_trace"]["success_count"] >= 1
    assert len(profile["source_finding_ids"]) == len(first_advance["round"]["findings"])
    assert any(request.node_id == "reference_profile_synthesize" for request in fake_client.requests)
    llm_nodes = {
        row.node_id
        for row in session.query(LlmCall).filter(LlmCall.node_id.like("reference_%")).all()
    }
    assert llm_nodes >= {
        "reference_sample_ranker",
        "reference_style_structure_extract",
        "reference_profile_synthesize",
    }


def test_reference_profile_sanitizes_llm_evidence_and_source_markers(session, tmp_path: Path) -> None:
    book_path = tmp_path / "leaky-reference.md"
    book_path.write_text(_book_text(), encoding="utf-8")
    service = ReferenceLearningService(session, llm_client=LeakyReferenceLlmClient())

    imported = service.import_path(
        file_path=str(book_path),
        title="龙族[1-3部全].txt",
        author_label="reference",
        cloud_policy="allow_full_cloud",
        analysis_focus="style_structure",
    )
    run = service.start_run(imported["book_id"], batch_size=5)["run"]
    first_advance = service.advance_run(imported["book_id"], run["run_id"])

    review_service = ReviewMaterializationService(session)
    for finding in first_advance["round"]["findings"]:
        review_service.materialize_review(finding["review"]["review_id"])

    advanced = service.advance_run(imported["book_id"], run["run_id"])
    profile = advanced.get("profile") or service.detail(imported["book_id"])["profiles"][0]
    serialized_profile = json.dumps(profile["profile_json"], ensure_ascii=False)

    assert profile["status"] == "ready"
    assert profile["safety_summary"]["safe"] is True
    assert profile["safety_summary"]["stripped_count"] >= 1
    assert profile["profile_json"]["locale"] == "zh"
    assert 0 <= profile["profile_json"]["quality_score"] <= 1
    assert profile["profile_json"]["source_term_audit"]["blocked_markers"] == []
    assert "repetition_score" in profile["profile_json"]
    assert "safety_findings" in profile["profile_json"]
    for marker in ["Evidence:", "Evidence pattern:", "txt8080", "声明：本书", "路明非", "楚子航", "卡塞尔", "江南"]:
        assert marker not in serialized_profile


def test_reference_profile_sanitizer_blocks_source_phrase_and_uses_chinese_fallback() -> None:
    cleaned, stripped_count = _sanitize_reference_profile_text("Keep lonely George as an emotional calibration phrase.")

    assert stripped_count >= 1
    assert "lonely George" not in cleaned
    assert "Convert the reference" not in cleaned
    assert "抽象写作技法" in cleaned


def test_local_only_reference_learning_does_not_call_llm(session, tmp_path: Path) -> None:
    book_path = tmp_path / "local-only-reference.md"
    book_path.write_text(_book_text(), encoding="utf-8")
    fake_client = FakeReferenceLlmClient()
    service = ReferenceLearningService(session, llm_client=fake_client)

    imported = service.import_path(
        file_path=str(book_path),
        title="Local Only Reference",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    run = service.start_run(imported["book_id"], batch_size=5)["run"]
    first_advance = service.advance_run(imported["book_id"], run["run_id"])

    assert fake_client.requests == []
    assert {finding["finding_type"] for finding in first_advance["round"]["findings"]} >= {
        "style_rule_set",
        "style_observation",
        "narrative_pattern",
    }


def test_reference_learning_skips_boilerplate_segments_and_keeps_findings_abstract(session, tmp_path: Path) -> None:
    boilerplate = (
        "声明：本书为八零电子书(txt8080.com)的用户上传至本站的存储空间，"
        "本站只提供TXT全集电子书存储服务，以下作品内容之版权与本站无任何关系。"
    )
    craft_paragraphs = [
        "雨沿着教学楼的玻璃向下走，路明非把手缩进袖口，听见远处钟声像一枚硬币落进水里。",
        "女孩没有立刻回答，她先看向走廊尽头，那里的灯一盏接一盏暗下去，像有人正在擦掉地图。",
        "他们穿过空教室，粉笔灰在月光里悬着，每一步都像踩在一句没有说出口的誓言上。",
        "门外忽然传来脚步声，短促，停顿，再短促，所有人的呼吸都被迫排成同一个节拍。",
        "最后一扇窗亮起来时，他明白邀请从来不是选择，而是一场迟到的判决。",
    ]
    book_path = tmp_path / "boilerplate-reference.txt"
    book_path.write_text("\n\n".join([boilerplate, *craft_paragraphs]), encoding="utf-8")
    service = ReferenceLearningService(session)

    imported = service.import_path(
        file_path=str(book_path),
        title="Boilerplate Reference",
        author_label="reference",
        cloud_policy="local_only",
        analysis_focus="style_structure",
    )
    run = service.start_run(imported["book_id"], batch_size=5)["run"]
    first_advance = service.advance_run(imported["book_id"], run["run_id"])

    selected_segment_ids = [finding["source_segment"]["segment_id"] for finding in first_advance["round"]["findings"]]
    selected_segments = session.query(ReferenceBookSegment).filter(ReferenceBookSegment.segment_id.in_(selected_segment_ids)).all()
    assert selected_segments
    assert all(segment.segment_kind != "boilerplate" for segment in selected_segments)
    assert all("txt8080" not in segment.text and "本站" not in segment.text for segment in selected_segments)
    assert all("Evidence:" not in finding["summary"] for finding in first_advance["round"]["findings"])


def test_reference_learning_review_can_be_rejected_after_unreleased_approval(client, session, tmp_path: Path) -> None:
    book_id = _import_reference_book(client, tmp_path)
    first_advance = _start_and_advance(client, book_id)
    review_id = first_advance["round"]["findings"][0]["review"]["review_id"]

    approve = client.post(
        f"/api/v1/review-items/{review_id}/approve",
        json={},
        headers=_idempotency_headers("approve-before-reject-reference-review"),
    )
    assert approve.status_code == 200
    approved_item = session.get(ReviewItem, review_id)
    assert approved_item.status == "approved"
    assert approved_item.materialize_status == "succeeded"

    reject = client.post(
        f"/api/v1/review-items/{review_id}/reject",
        json={"reason": "not representative enough"},
        headers=_idempotency_headers("reject-after-approve-reference-review"),
    )
    assert reject.status_code == 200
    data = reject.json()["data"]
    assert data["status"] == "rejected"
    assert data["materialize_status"] == "rejected"
    assert data["approved_item_row_id"] is None


def test_rejected_after_profile_marks_profile_stale_and_blocks_apply(client, session, tmp_path: Path) -> None:
    book_id = _import_reference_book(client, tmp_path)
    first_advance = _start_and_advance(client, book_id)
    run_id = first_advance["run"]["run_id"]

    for index, finding in enumerate(first_advance["round"]["findings"]):
        approve = client.post(
            f"/api/v1/review-items/{finding['review']['review_id']}/approve",
            json={},
            headers=_idempotency_headers(f"approve-stale-profile-review-{index}"),
        )
        assert approve.status_code == 200

    completed = client.post(
        f"/api/v1/reference-books/{book_id}/runs/{run_id}/advance",
        json={},
        headers=_idempotency_headers("advance-stale-profile-complete"),
    )
    assert completed.status_code == 200
    completed_data = completed.json()["data"]
    if "profile" in completed_data:
        profile = completed_data["profile"]
    else:
        detail_for_profile = client.get(f"/api/v1/reference-books/{book_id}")
        assert detail_for_profile.status_code == 200
        profile = detail_for_profile.json()["data"]["profiles"][0]
    assert profile["status"] == "ready"
    assert profile["source_finding_ids"]

    rejected_finding = first_advance["round"]["findings"][0]
    reject = client.post(
        f"/api/v1/review-items/{rejected_finding['review']['review_id']}/reject",
        json={"reason": "not representative enough"},
        headers=_idempotency_headers("reject-after-profile-ready"),
    )
    assert reject.status_code == 200

    detail = client.get(f"/api/v1/reference-books/{book_id}")
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    stale_profile = next(item for item in detail_data["profiles"] if item["profile_id"] == profile["profile_id"])
    assert stale_profile["status"] == "stale"
    assert stale_profile["safety_summary"]["safe"] is True
    assert detail_data["latest_run"]["coverage"]["profile_stale"] is True

    apply_response = client.post(
        f"/api/v1/reference-books/{book_id}/profiles/{profile['profile_id']}/apply",
        json={"scope": "chapter", "scope_ref_id": "CH001"},
        headers=_idempotency_headers("apply-stale-reference-profile"),
    )
    assert apply_response.status_code == 409
    assert apply_response.json()["error"]["code"] == "REFERENCE_PROFILE_STALE"
