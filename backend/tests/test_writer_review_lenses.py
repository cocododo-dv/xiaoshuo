from __future__ import annotations

from novel_system.db.models import ChapterGoal, FinalScene, LlmCall, RevisionCandidate, SceneCard, SceneRunState, WriterEvaluation
from novel_system.services.llm_client import LLMResponse
from novel_system.services.writer_review import WRITER_REVIEW_LENSES, WriterReviewService


CHAPTER_ID = "LENS100"
SCENE_ID = "LENS100_SC01"
FINAL_ROW_ID = "final_LENS100_SC01"


def _seed_scene(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id=CHAPTER_ID,
            planned_scene_count=1,
            chapter_goal="A friend hides a name.",
            writer_brief_json={"chapter_promise": "friendship will turn into suspicion"},
        )
    )
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            scene_seq=1,
            scene_goal="The protagonist asks and the friend deflects.",
            writer_brief_json={
                "character_desire": "get the truth",
                "choice_under_pressure": "trust or investigate",
                "power_shift": "the protagonist starts leading",
            },
        )
    )
    session.add(
        SceneRunState(
            scene_id=SCENE_ID,
            scene_status="finalized",
            current_final_scene_row_id=FINAL_ROW_ID,
            current_bundle_id="bundle_lens",
            current_bundle_hash="hash_lens",
        )
    )
    session.add(
        FinalScene(
            row_id=FINAL_ROW_ID,
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            content="Mira said the missing name. Jun smiled first, then moved the cup between them.",
            source_bundle_id="bundle_lens",
            source_bundle_hash="hash_lens",
        )
    )
    session.commit()


class LensReviewClient:
    def __init__(self, *, malformed_lens: bool = False) -> None:
        self.requests = []
        self.malformed_lens = malformed_lens

    def generate(self, request):
        self.requests.append(request)
        node_id = request.node_id
        if node_id.endswith("_diagnosis"):
            payload = self._diagnosis_payload(node_id)
        elif node_id == "writer_scene_revision":
            payload = {
                "revised_text": "Mira said the missing name. Jun's smile stopped before it reached his eyes.",
                "diff_summary": "Tightens the visible pressure around the deflection.",
                "changed_dimensions": ["dialogue_edge", "power_shift"],
                "rewrite_strategy": "full_scene_rewrite",
            }
        else:
            payload = {}
        return LLMResponse(
            request_id=f"req_{node_id}",
            provider="test",
            model=request.model,
            text="{}",
            structured_output=payload,
            response_format=request.response_format,
            raw_response={"id": f"req_{node_id}"},
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )

    def _diagnosis_payload(self, node_id: str) -> dict:
        if self.malformed_lens and node_id.endswith("reader_diagnosis"):
            return {"overall_score": "bad"}
        scores = {dimension: 0.72 for dimension in (
            "desire",
            "obstacle",
            "stakes",
            "turn",
            "subtext",
            "irreversible_change",
            "scene_necessity",
            "reader_hook",
            "continuity",
            "character_agency",
            "dialogue_edge",
            "information_rhythm",
            "imagery_freshness",
            "expression_repetition",
            "power_shift",
            "ending_drive",
        )}
        if node_id.endswith("character_diagnosis"):
            scores["character_agency"] = 0.31
            scores["power_shift"] = 0.33
        return {
            "overall_score": sum(scores.values()) / len(scores),
            "scores": scores,
            "findings": [
                {
                    "dimension": "power_shift",
                    "severity": "major",
                    "issue": f"{node_id} sees the deflection but wants a stronger choice.",
                    "recommendation": "Make the character choose instead of only noticing.",
                    "evidence_excerpt": "Jun smiled first",
                    "evidence_location": "paragraph 1",
                    "why_it_matters": "The reader needs pressure to land as action, not just mood.",
                    "evidence_spans": [{"start": 28, "end": 43}],
                }
            ],
            "revision_brief": [{"dimension": "power_shift", "action": "turn hesitation into a choice", "priority": "high"}],
            "requires_human_review": False,
        }


def test_scene_writer_review_creates_four_lens_children_aggregate_and_manual_patch_candidate(session) -> None:
    _seed_scene(session)
    fake_client = LensReviewClient()

    payload = WriterReviewService(session, llm_client=fake_client).run_scene_review(SCENE_ID, actor_ref="writer.tdd")

    requested_nodes = [request.node_id for request in fake_client.requests]
    assert requested_nodes[:4] == [lens.scene_node_id for lens in WRITER_REVIEW_LENSES]
    assert requested_nodes[-1] == "writer_scene_revision"
    assert payload["evaluation"]["lens"] == "aggregate"
    assert payload["evaluation"]["requires_human_review"] is True
    assert payload["lens_evaluations"]
    assert {item["lens"] for item in payload["lens_evaluations"]} == {"story", "character", "prose", "reader"}
    assert any(item.get("lens") in {"story", "character", "prose", "reader"} for item in payload["evaluation"]["findings"])
    assert payload["evaluation"]["evidence_spans"]

    candidate = payload["candidates"][0]
    assert candidate["apply_mode"] == "manual_only"
    assert candidate["target_text_ref"] == "final_scene:final_LENS100_SC01"
    assert candidate["patches"][0]["patch_type"] == "full_scene_rewrite"
    assert candidate["patches"][0]["manual_only"] is True

    aggregate = session.get(WriterEvaluation, payload["evaluation"]["evaluation_id"])
    child_count = session.query(WriterEvaluation).filter_by(parent_evaluation_id=aggregate.evaluation_id).count()
    assert child_count == 4
    assert session.get(RevisionCandidate, candidate["revision_id"]).apply_mode == "manual_only"
    assert session.query(LlmCall).filter(LlmCall.node_id.like("writer_scene_%_diagnosis")).count() == 4


def test_malformed_lens_blocks_without_revision_candidate_or_fabricated_final_score(session) -> None:
    _seed_scene(session)
    fake_client = LensReviewClient(malformed_lens=True)

    payload = WriterReviewService(session, llm_client=fake_client).run_scene_review(SCENE_ID, actor_ref="writer.tdd")

    assert payload["evaluation"]["lens"] == "aggregate"
    assert payload["evaluation"]["requires_human_review"] is True
    assert payload["evaluation"]["overall_score"] is None
    assert payload["candidates"] == []
    assert session.query(RevisionCandidate).filter_by(scene_id=SCENE_ID).count() == 0
