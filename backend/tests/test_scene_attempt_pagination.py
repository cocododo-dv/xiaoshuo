from __future__ import annotations

from sqlalchemy import event

from novel_system.db.models import AttemptTracker, ChapterGoal, ChapterState, SceneCard, SceneRunState
from novel_system.db.session import engine


def test_scene_attempts_support_page_and_cursor_pagination_without_breaking_workbench(client, session) -> None:
    session.add_all(
        [
            ChapterGoal(
                chapter_id="CH300",
                chapter_goal="Track scene attempts with paged reads",
            ),
            ChapterState(
                chapter_id="CH300",
                current_phase="drafting",
                chapter_passed_scene_count=0,
                chapter_backfill_pending_count=0,
                mid_aggregate_enabled_effective=0,
                aggregate_block_reason="none",
            ),
            SceneCard(
                scene_id="CH300_SC01",
                chapter_id="CH300",
                scene_seq=1,
                scene_goal="Exercise paged attempts",
                beats_json=["beat one"],
            ),
            SceneRunState(
                scene_id="CH300_SC01",
                scene_status="ready",
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            AttemptTracker(
                scene_id="CH300_SC01",
                chapter_id="CH300",
                step="bundle_built",
                status="ok",
                source_bundle_id="bundle_001",
                details_json={},
            ),
            AttemptTracker(
                scene_id="CH300_SC01",
                chapter_id="CH300",
                step="hard_checked",
                status="ok",
                source_bundle_id="bundle_002",
                details_json={},
            ),
            AttemptTracker(
                scene_id="CH300_SC01",
                chapter_id="CH300",
                step="style_rewritten",
                status="ok",
                source_bundle_id="bundle_003",
                details_json={},
            ),
            AttemptTracker(
                scene_id="CH300_SC01",
                chapter_id="CH300",
                step="archived",
                status="ok",
                source_bundle_id="bundle_004",
                details_json={},
            ),
        ]
    )
    session.commit()

    attempt_selects: list[str] = []

    def capture_attempt_selects(_connection, _cursor, statement, _parameters, _context, _many) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "attempt_tracker" in normalized:
            attempt_selects.append(normalized)

    event.listen(engine(), "before_cursor_execute", capture_attempt_selects)
    try:
        page_response = client.get(
            "/api/v1/scenes/CH300_SC01/attempts",
            params={"page": 1, "page_size": 2},
        )
    finally:
        event.remove(engine(), "before_cursor_execute", capture_attempt_selects)

    assert len(attempt_selects) == 2
    assert any("count(" in statement for statement in attempt_selects)
    assert any(" limit " in statement for statement in attempt_selects)
    assert all("count(" in statement or " limit " in statement for statement in attempt_selects)
    assert page_response.status_code == 200
    page_data = page_response.json()["data"]
    assert [item["step"] for item in page_data["items"]] == ["archived", "style_rewritten"]
    assert page_data["pagination"]["mode"] == "page"
    assert page_data["pagination"]["limit"] == 2
    assert page_data["pagination"]["page"] == 1
    assert page_data["pagination"]["page_size"] == 2
    assert page_data["pagination"]["returned"] == 2
    assert page_data["pagination"]["total"] == 4
    assert page_data["pagination"]["has_next"] is True
    assert isinstance(page_data["pagination"]["next_cursor"], str)
    assert page_data["pagination"]["next_cursor"]

    cursor_response = client.get("/api/v1/scenes/CH300_SC01/attempts", params={"limit": 2})
    assert cursor_response.status_code == 200
    cursor_data = cursor_response.json()["data"]
    assert [item["step"] for item in cursor_data["items"]] == ["archived", "style_rewritten"]
    assert cursor_data["pagination"]["mode"] == "cursor"
    assert cursor_data["pagination"]["page"] is None
    assert cursor_data["pagination"]["page_size"] is None
    assert cursor_data["pagination"]["returned"] == 2
    assert cursor_data["pagination"]["total"] == 4
    assert cursor_data["pagination"]["has_next"] is True
    assert isinstance(cursor_data["pagination"]["next_cursor"], str)
    assert cursor_data["pagination"]["next_cursor"]

    next_cursor_response = client.get(
        "/api/v1/scenes/CH300_SC01/attempts",
        params={"cursor": cursor_data["pagination"]["next_cursor"], "limit": 2},
    )
    assert next_cursor_response.status_code == 200
    next_cursor_data = next_cursor_response.json()["data"]
    assert [item["step"] for item in next_cursor_data["items"]] == ["hard_checked", "bundle_built"]
    assert next_cursor_data["pagination"]["has_next"] is False
    assert next_cursor_data["pagination"]["next_cursor"] is None

    workbench_response = client.get("/api/v1/scenes/CH300_SC01/workbench")
    assert workbench_response.status_code == 200
    assert [item["step"] for item in workbench_response.json()["data"]["attempts"]] == [
        "bundle_built",
        "hard_checked",
        "style_rewritten",
        "archived",
    ]
