"""Wave 1（结果闭环治理 §5.2）：作者采纳归档单入口 + 归档状态词表统一。

完成门可复算证明：前端置 done 的唯一合法路径是本端点的成功响应——
归档后必须存在可回放的后端 FinalScene（status=archived），章节聚合
（chapter_manuscripts，以 FinalScene 为源）能取到全文；缓存清除不丢稿。
"""

from __future__ import annotations

from novel_system.db.models import (
    FinalScene,
    SceneDraft,
    SceneRunState,
)
from novel_system.services.archiver import Archiver
from tests.test_chapter_manuscripts import _create_chapter, _create_scene


def _seed_style_draft(session, scene_id: str, chapter_id: str, *, content: str, row_id: str | None = None) -> str:
    draft_row_id = row_id or f"draft_style_{scene_id}_v1"
    session.add(
        SceneDraft(
            row_id=draft_row_id,
            scene_id=scene_id,
            chapter_id=chapter_id,
            stage="style",
            content=content,
            source_bundle_id=f"bundle_{scene_id}",
            source_bundle_hash=f"hash_{scene_id}",
        )
    )
    state = session.get(SceneRunState, scene_id)
    assert state is not None, "scenes POST 应已建运行态行"
    state.scene_status = "human_review_required"
    state.current_style_draft_row_id = draft_row_id
    session.commit()
    return draft_row_id


def test_adopt_promotes_style_draft_to_archived_final(client, session):
    _create_chapter(client, "chapter_adopt_1")
    _create_scene(client, "scene_adopt_1", chapter_id="chapter_adopt_1", scene_seq=1)
    _seed_style_draft(session, "scene_adopt_1", "chapter_adopt_1", content="潮水退去，她看清了闸门上的名字。")

    response = client.post(
        "/api/v1/scenes/scene_adopt_1/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-1"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scene_status"] == "archived"
    final_row_id = data["final_scene_row_id"]
    assert final_row_id

    final = session.get(FinalScene, final_row_id)
    assert final is not None
    # 状态词表统一：归档事务写入的权威态是 archived，不再依赖 approved 的字符串巧合
    assert final.status == "archived"
    assert final.content == "潮水退去，她看清了闸门上的名字。"

    # 完成门：归档稿可从 workbench 回放
    workbench = client.get("/api/v1/scenes/scene_adopt_1/workbench").json()["data"]
    assert workbench["final_scene"]["content"] == "潮水退去，她看清了闸门上的名字。"
    assert workbench["author_state"]["author_state"] == "archived"

    # 完成门：章节聚合（FinalScene 为源）取到全文——清除任何前端缓存都不影响
    detail = client.get("/api/v1/chapter-manuscripts/chapter_adopt_1").json()["data"]
    assert "潮水退去" in detail["assembled"]["content"]


def test_adopt_without_any_draft_409(client, session):
    _create_chapter(client, "chapter_adopt_2")
    _create_scene(client, "scene_adopt_2", chapter_id="chapter_adopt_2", scene_seq=1)

    response = client.post(
        "/api/v1/scenes/scene_adopt_2/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-2"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_VALID_DRAFT"


def test_adopt_idempotent_replay_and_already_archived(client, session):
    _create_chapter(client, "chapter_adopt_3")
    _create_scene(client, "scene_adopt_3", chapter_id="chapter_adopt_3", scene_seq=1)
    _seed_style_draft(session, "scene_adopt_3", "chapter_adopt_3", content="第一次归档正文。")

    first = client.post(
        "/api/v1/scenes/scene_adopt_3/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-3"},
    )
    assert first.status_code == 200
    first_row = first.json()["data"]["final_scene_row_id"]

    # 同幂等键重放：同结果，不建第二行
    replay = client.post(
        "/api/v1/scenes/scene_adopt_3/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-3"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["final_scene_row_id"] == first_row

    # 已归档后换新幂等键再采纳：幂等返回已归档结果，不重复归档
    again = client.post(
        "/api/v1/scenes/scene_adopt_3/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-3-bis"},
    )
    assert again.status_code == 200
    assert again.json()["data"]["scene_status"] == "archived"
    assert again.json()["data"]["final_scene_row_id"] == first_row
    finals = session.query(FinalScene).filter(FinalScene.scene_id == "scene_adopt_3").all()
    assert len(finals) == 1


def test_adopt_source_safety_blocked_keeps_draft(client, session):
    """设计红线 8：来源安全未通过时草稿可保存，但不能标记为已安全归档。"""
    _create_chapter(client, "chapter_adopt_4")
    _create_scene(client, "scene_adopt_4", chapter_id="chapter_adopt_4", scene_seq=1)
    draft_row_id = _seed_style_draft(
        session, "scene_adopt_4", "chapter_adopt_4",
        content="他抬起头，看见路明非站在门口。",  # PROTECTED_SOURCE_TERMS 保护词
    )

    response = client.post(
        "/api/v1/scenes/scene_adopt_4/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-4"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOURCE_SAFETY_BLOCKED"

    # 草稿保留、未归档
    session.expire_all()
    assert session.get(SceneDraft, draft_row_id) is not None
    state = session.get(SceneRunState, "scene_adopt_4")
    assert state.scene_status != "archived"
    finals = session.query(FinalScene).filter(FinalScene.scene_id == "scene_adopt_4").all()
    assert not [f for f in finals if f.status == "archived"]


def test_adopt_promotes_existing_unarchived_final_scene(client, session):
    """管线停在 near_final_ready 的既有 FinalScene：adopt 提升归档它，不建新行。"""
    _create_chapter(client, "chapter_adopt_5")
    _create_scene(client, "scene_adopt_5", chapter_id="chapter_adopt_5", scene_seq=1)
    session.add(
        FinalScene(
            row_id="final_adopt_5_v1",
            scene_id="scene_adopt_5",
            chapter_id="chapter_adopt_5",
            content="近终稿正文。",
            status="near_final_ready",
            source_bundle_id="bundle_adopt_5",
            source_bundle_hash="hash_adopt_5",
        )
    )
    state = session.get(SceneRunState, "scene_adopt_5")
    state.scene_status = "human_review_required"
    state.current_final_scene_row_id = "final_adopt_5_v1"
    session.commit()

    response = client.post(
        "/api/v1/scenes/scene_adopt_5/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-5"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["final_scene_row_id"] == "final_adopt_5_v1"
    session.expire_all()
    assert session.get(FinalScene, "final_adopt_5_v1").status == "archived"
    finals = session.query(FinalScene).filter(FinalScene.scene_id == "scene_adopt_5").all()
    assert len(finals) == 1


def test_adopt_falls_back_to_author_draft(client, session):
    """人工手写场（无管线稿，只有 author-draft 正文）也能走同一归档入口。"""
    _create_chapter(client, "chapter_adopt_6")
    _create_scene(client, "scene_adopt_6", chapter_id="chapter_adopt_6", scene_seq=1)
    ensure = client.post("/api/v1/author-drafts/scene/scene_adopt_6/ensure", json={})
    assert ensure.status_code == 200
    draft_id = ensure.json()["data"]["draft"]["draft_id"]
    patched = client.patch(
        f"/api/v1/author-drafts/{draft_id}",
        json={"content": "<p>手写的正文段落。</p>", "base_revision_no": ensure.json()["data"]["draft"]["revision_no"]},
    )
    assert patched.status_code == 200

    response = client.post(
        "/api/v1/scenes/scene_adopt_6/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-6"},
    )
    assert response.status_code == 200
    final_row_id = response.json()["data"]["final_scene_row_id"]
    final = session.get(FinalScene, final_row_id)
    assert final is not None
    assert final.status == "archived"
    assert "手写的正文段落" in final.content


def test_archiver_marks_final_scene_archived(session):
    """单元级：归档事务统一写 FinalScene.status=archived（词表统一）。"""
    session.add(
        FinalScene(
            row_id="final_unit_1",
            scene_id="scene_unit_1",
            chapter_id="chapter_unit_1",
            content="正文",
            status="near_final_ready",
            source_bundle_id="bundle_u",
            source_bundle_hash="hash_u",
        )
    )
    session.add(SceneRunState(scene_id="scene_unit_1"))
    session.flush()

    result = Archiver(session).archive_final_scene("scene_unit_1", "final_unit_1")
    assert result["scene_status"] == "archived"
    assert session.get(FinalScene, "final_unit_1").status == "archived"


def test_adopt_updates_latest_valid_pointer(client, session):
    """归档路径同样维护 latest_valid_draft 指针（§4.3）。"""
    _create_chapter(client, "chapter_adopt_7")
    _create_scene(client, "scene_adopt_7", chapter_id="chapter_adopt_7", scene_seq=1)
    draft_row_id = _seed_style_draft(session, "scene_adopt_7", "chapter_adopt_7", content="指针维护正文。")

    response = client.post(
        "/api/v1/scenes/scene_adopt_7/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-7"},
    )
    assert response.status_code == 200
    session.expire_all()
    state = session.get(SceneRunState, "scene_adopt_7")
    assert state.latest_valid_draft_row_id == draft_row_id


def test_manuscript_detail_scene_entry_carries_content(client, session):
    """FE 换源数据面：detail 的 scenes[].final_scene 必须带 content 全文。"""
    _create_chapter(client, "chapter_adopt_8")
    _create_scene(client, "scene_adopt_8", chapter_id="chapter_adopt_8", scene_seq=1)
    _seed_style_draft(session, "scene_adopt_8", "chapter_adopt_8", content="逐场正文全文。")
    adopted = client.post(
        "/api/v1/scenes/scene_adopt_8/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "adopt-8"},
    )
    assert adopted.status_code == 200

    detail = client.get("/api/v1/chapter-manuscripts/chapter_adopt_8").json()["data"]
    entries = [s for s in detail["scenes"] if s["scene_id"] == "scene_adopt_8"]
    assert entries and entries[0]["final_scene"]["content"] == "逐场正文全文。"
