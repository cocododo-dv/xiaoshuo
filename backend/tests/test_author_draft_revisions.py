"""author-draft 修订快照（FE-ALIGN F2：成稿中心版本对比的数据底座）。"""

from __future__ import annotations

from novel_system.db.models import AuthorDraftRevision


def _create_chapter(client, chapter_id: str) -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": chapter_id,
            "planned_scene_count": 1,
            "chapter_goal": f"目标 {chapter_id}",
            "main_plot_push": "推进主线",
            "emotional_target": "情绪转折",
            "ending_effect": "留下余味",
        },
        headers={"X-Idempotency-Key": f"rev-chapter-{chapter_id}"},
    )
    assert response.status_code == 200


def _create_scene(client, scene_id: str, *, chapter_id: str) -> None:
    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": scene_id,
            "chapter_id": chapter_id,
            "scene_seq": 1,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A"],
            "location": "档案室",
            "scene_goal": f"场景目标 {scene_id}",
            "beats_json": ["发现", "选择"],
            "exit_change": "关系改变",
            "hook": "尾钩",
            "target_length_band": "medium",
            "scene_type": "reunion",
            "is_chapter_last": 1,
        },
        headers={"X-Idempotency-Key": f"rev-scene-{scene_id}"},
    )
    assert response.status_code == 200


def _ensure_draft(client, scene_id: str) -> dict:
    response = client.post(
        f"/api/v1/author-drafts/scene/{scene_id}/ensure",
        headers={"X-Idempotency-Key": f"rev-ensure-{scene_id}"},
    )
    assert response.status_code == 200
    return response.json()["data"]["draft"]


def _save(client, draft_id: str, base_revision_no: int, content: str):
    return client.patch(
        f"/api/v1/author-drafts/{draft_id}",
        json={"content": content, "base_revision_no": base_revision_no},
    )


def test_each_save_snapshots_a_revision(client, session) -> None:
    _create_chapter(client, "CH_REV_1")
    _create_scene(client, "SC_REV_1", chapter_id="CH_REV_1")
    draft = _ensure_draft(client, "SC_REV_1")

    assert _save(client, draft["draft_id"], 1, "第一版正文。").status_code == 200
    assert _save(client, draft["draft_id"], 2, "第二版正文，比第一版长一点。").status_code == 200

    response = client.get(f"/api/v1/author-drafts/{draft['draft_id']}/revisions")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["revision_no"] == 3
    # 倒序：v3（第二次保存）、v2（第一次保存）、v1（ensure 初版快照）
    nos = [item["revision_no"] for item in data["items"]]
    assert nos == [3, 2, 1]
    assert all("content" not in item for item in data["items"])  # 列表轻量，不带正文


def test_revision_content_is_retrievable(client, session) -> None:
    _create_chapter(client, "CH_REV_2")
    _create_scene(client, "SC_REV_2", chapter_id="CH_REV_2")
    draft = _ensure_draft(client, "SC_REV_2")
    assert _save(client, draft["draft_id"], 1, "潮水在夜里退去。").status_code == 200
    assert _save(client, draft["draft_id"], 2, "潮水在夜里退去，露出一行脚印。").status_code == 200

    response = client.get(f"/api/v1/author-drafts/{draft['draft_id']}/revisions/2")
    assert response.status_code == 200
    revision = response.json()["data"]["revision"]
    assert revision["content"] == "潮水在夜里退去。"
    assert revision["origin"] == "edited"
    assert revision["words"] > 0

    missing = client.get(f"/api/v1/author-drafts/{draft['draft_id']}/revisions/99")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "AUTHOR_DRAFT_REVISION_NOT_FOUND"


def test_conflict_save_does_not_snapshot(client, session) -> None:
    _create_chapter(client, "CH_REV_3")
    _create_scene(client, "SC_REV_3", chapter_id="CH_REV_3")
    draft = _ensure_draft(client, "SC_REV_3")
    assert _save(client, draft["draft_id"], 1, "正式的一版。").status_code == 200

    conflict = _save(client, draft["draft_id"], 1, "基于旧版的改写。")
    assert conflict.status_code == 409

    rows = session.query(AuthorDraftRevision).filter_by(draft_id=draft["draft_id"]).all()
    assert {row.revision_no for row in rows} == {1, 2}


def test_unknown_draft_revisions_404(client, session) -> None:
    response = client.get("/api/v1/author-drafts/author_draft_missing/revisions")
    assert response.status_code == 404
