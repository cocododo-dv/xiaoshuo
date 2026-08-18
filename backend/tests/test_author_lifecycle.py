from __future__ import annotations

from sqlalchemy import select

from novel_system.db.models import (
    ChapterGoal,
    HumanReviewEvent,
    SceneBundle,
    SceneCard,
    SceneRunState,
    StoryProject,
)
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.vector_store import InMemoryVectorStore


def _create_chapter(client, chapter_id: str, *, goal: str = "Author a chapter") -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": chapter_id,
            "planned_scene_count": 3,
            "chapter_goal": goal,
            "main_plot_push": f"push {chapter_id}",
            "emotional_target": f"emotion {chapter_id}",
            "ending_effect": f"ending {chapter_id}",
            "must_not": f"avoid {chapter_id}",
            "notes": f"notes {chapter_id}",
        },
        headers={"X-Idempotency-Key": f"create-{chapter_id}"},
    )
    assert response.status_code == 200


def _create_scene(
    client,
    scene_id: str,
    *,
    chapter_id: str,
    scene_seq: int | None = None,
    is_chapter_last: int = 0,
    location: str = "Archive room",
) -> None:
    payload = {
        "scene_id": scene_id,
        "chapter_id": chapter_id,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_B"],
        "location": location,
        "scene_goal": f"goal for {scene_id}",
        "beats_json": [f"beat-{scene_id}-1", f"beat-{scene_id}-2"],
        "must_include_text": f"must include {scene_id}",
        "forbidden_text": f"forbidden {scene_id}",
        "exit_change": f"exit {scene_id}",
        "hook": f"hook {scene_id}",
        "target_length_band": "medium",
        "scene_type": "reunion",
        "is_chapter_last": is_chapter_last,
    }
    if scene_seq is not None:
        payload["scene_seq"] = scene_seq
    response = client.post(
        "/api/v1/scenes",
        json=payload,
        headers={"X-Idempotency-Key": f"create-{scene_id}"},
    )
    assert response.status_code == 200


def test_scene_purge_removes_only_its_project_vector_document(session) -> None:
    project_id = "project_vector_purge"
    chapter_id = "chapter_vector_purge"
    scene_id = "scene_vector_purge"
    session.add(StoryProject(
        project_id=project_id,
        title="Vector purge",
        outline_text="",
        planning_mode="snowflake",
    ))
    session.flush()
    session.add(ChapterGoal(
        chapter_id=chapter_id,
        project_id=project_id,
        chapter_goal="Purge one vector",
    ))
    session.flush()
    session.add(SceneCard(
        scene_id=scene_id,
        chapter_id=chapter_id,
        project_id=project_id,
        scene_seq=1,
        scene_goal="Purge",
        trashed_flag=1,
    ))
    session.flush()
    store = InMemoryVectorStore()
    store.write_collection(
        f"scenes_{project_id}",
        [
            {"id": scene_id, "text": "delete me"},
            {"id": "another_scene", "text": "keep me"},
        ],
    )

    result = AuthorLifecycleService(session, vector_store=store).purge_scenes([scene_id])

    assert result == {"processed": [{"scene_id": scene_id}], "blocked": []}
    assert store.load_collection(f"scenes_{project_id}") == [
        {"id": "another_scene", "text": "keep me"}
    ]


def test_scene_trash_hides_records_from_active_views_and_surfaces_them_in_author_trash(client) -> None:
    _create_chapter(client, "CH600", goal="Trash a single scene")
    _create_scene(client, "CH600_SC01", chapter_id="CH600", scene_seq=1)
    _create_scene(client, "CH600_SC02", chapter_id="CH600", scene_seq=2, is_chapter_last=1)

    trash_response = client.post(
        "/api/v1/scenes/trash",
        json={"scene_ids": ["CH600_SC02"]},
        headers={"X-Idempotency-Key": "trash-ch600-sc02", "X-Operator-Ref": "ops.author.trash"},
    )

    assert trash_response.status_code == 200
    assert trash_response.json()["data"] == {
        "processed": [{"scene_id": "CH600_SC02"}],
        "blocked": [],
        "actor_ref": "ops.author.trash",
    }

    chapters_response = client.get("/api/v1/chapters")
    assert chapters_response.status_code == 200
    assert chapters_response.json()["data"]["items"] == [
        {
            "chapter_id": "CH600",
            "planned_scene_count": 3,
            "chapter_goal": "Trash a single scene",
            "main_plot_push": "push CH600",
            "emotional_target": "emotion CH600",
            "ending_effect": "ending CH600",
            "must_not": "avoid CH600",
            "notes": "notes CH600",
            "current_phase": "drafting",
            "chapter_passed_scene_count": 0,
            "chapter_backfill_pending_count": 0,
            "active_scene_count": 1,
            "trashed_scene_count": 1,
            "trash_allowed": 0,
            "trash_block_reason": "章节下已有单独移入回收站的场景",
        }
    ]

    workspace_response = client.get("/api/v1/chapters/CH600/author-workspace")
    assert workspace_response.status_code == 200
    assert [scene["scene_id"] for scene in workspace_response.json()["data"]["scenes"]] == ["CH600_SC01"]

    author_trash_response = client.get("/api/v1/author-trash")
    assert author_trash_response.status_code == 200
    assert author_trash_response.json()["data"] == {
        "chapters": [],
        "scenes": [
            {
                "scene_id": "CH600_SC02",
                "chapter_id": "CH600",
                "scene_seq": 2,
                "scene_goal": "goal for CH600_SC02",
                "trashed_at": author_trash_response.json()["data"]["scenes"][0]["trashed_at"],
                "trashed_by": "ops.author.trash",
                "chapter_trashed": 0,
                "restore_allowed": 1,
                "restore_block_reason": None,
                "purge_allowed": 1,
                "purge_block_reason": None,
            }
        ],
    }

    workbench_response = client.get("/api/v1/scenes/CH600_SC02/workbench")
    assert workbench_response.status_code == 409
    assert workbench_response.json()["error"]["code"] == "SCENE_TRASHED"


def test_scene_restore_preserves_original_position_and_shifts_active_collision(client, session) -> None:
    _create_chapter(client, "CH605", goal="Restore a scene to its original position")
    _create_scene(client, "CH605_SC01", chapter_id="CH605", scene_seq=1)
    _create_scene(client, "CH605_SC02", chapter_id="CH605", scene_seq=2)
    _create_scene(client, "CH605_SC03", chapter_id="CH605", scene_seq=3, is_chapter_last=1)

    trashed = client.post(
        "/api/v1/scenes/trash",
        json={"scene_ids": ["CH605_SC02"]},
        headers={"X-Idempotency-Key": "trash-ch605-sc02"},
    )
    assert trashed.status_code == 200, trashed.text

    reordered = client.post(
        "/api/v1/chapters/CH605/scene-order",
        json={"scene_ids": ["CH605_SC03", "CH605_SC01"], "last_scene_id": "CH605_SC01"},
        headers={"X-Idempotency-Key": "reorder-ch605-active-scenes"},
    )
    assert reordered.status_code == 200, reordered.text

    restored = client.post(
        "/api/v1/scenes/restore",
        json={"scene_ids": ["CH605_SC02"]},
        headers={"X-Idempotency-Key": "restore-ch605-sc02"},
    )
    assert restored.status_code == 200, restored.text

    scenes = session.execute(
        select(SceneCard)
        .where(SceneCard.chapter_id == "CH605", SceneCard.trashed_flag == 0)
        .order_by(SceneCard.scene_seq.asc())
    ).scalars().all()
    assert [(scene.scene_id, scene.scene_seq) for scene in scenes] == [
        ("CH605_SC03", 1),
        ("CH605_SC02", 2),
        ("CH605_SC01", 3),
    ]
    assert [scene.is_chapter_last for scene in scenes] == [0, 0, 1]


def test_chapter_trash_is_blocked_when_it_has_previously_trashed_child_scenes(client) -> None:
    _create_chapter(client, "CH610", goal="Block ambiguous chapter trash")
    _create_scene(client, "CH610_SC01", chapter_id="CH610", scene_seq=1)
    _create_scene(client, "CH610_SC02", chapter_id="CH610", scene_seq=2, is_chapter_last=1)

    response = client.post(
        "/api/v1/scenes/trash",
        json={"scene_ids": ["CH610_SC02"]},
        headers={"X-Idempotency-Key": "trash-ch610-sc02"},
    )
    assert response.status_code == 200

    chapter_trash_response = client.post(
        "/api/v1/chapters/trash",
        json={"chapter_ids": ["CH610"]},
        headers={"X-Idempotency-Key": "trash-ch610"},
    )

    assert chapter_trash_response.status_code == 200
    assert chapter_trash_response.json()["data"] == {
        "processed": [],
        "blocked": [
            {
                "chapter_id": "CH610",
                "code": "CHAPTER_TRASH_BLOCKED_HAS_TRASHED_SCENES",
                "message": "章节下已有单独移入回收站的场景",
            }
        ],
        "actor_ref": "operator",
    }


def test_chapter_trash_moves_chapter_and_child_scenes_to_trash_and_restore_returns_them(client) -> None:
    _create_chapter(client, "CH620", goal="Trash and restore a chapter")
    _create_scene(client, "CH620_SC01", chapter_id="CH620", scene_seq=1)
    _create_scene(client, "CH620_SC02", chapter_id="CH620", scene_seq=2, is_chapter_last=1)

    chapter_trash_response = client.post(
        "/api/v1/chapters/trash",
        json={"chapter_ids": ["CH620"]},
        headers={"X-Idempotency-Key": "trash-ch620", "X-Operator-Ref": "ops.author.chapter"},
    )

    assert chapter_trash_response.status_code == 200
    assert chapter_trash_response.json()["data"] == {
        "processed": [{"chapter_id": "CH620", "scene_ids": ["CH620_SC01", "CH620_SC02"]}],
        "blocked": [],
        "actor_ref": "ops.author.chapter",
    }

    chapters_response = client.get("/api/v1/chapters")
    assert chapters_response.status_code == 200
    assert chapters_response.json()["data"]["items"] == []

    chapter_workspace_response = client.get("/api/v1/chapters/CH620/author-workspace")
    assert chapter_workspace_response.status_code == 409
    assert chapter_workspace_response.json()["error"]["code"] == "CHAPTER_TRASHED"

    author_trash_response = client.get("/api/v1/author-trash")
    assert author_trash_response.status_code == 200
    assert author_trash_response.json()["data"]["chapters"] == [
        {
            "chapter_id": "CH620",
            "chapter_goal": "Trash and restore a chapter",
            "trashed_at": author_trash_response.json()["data"]["chapters"][0]["trashed_at"],
            "trashed_by": "ops.author.chapter",
            "scene_count": 2,
            "restore_allowed": 1,
            "restore_block_reason": None,
            "purge_allowed": 1,
            "purge_block_reason": None,
        }
    ]
    assert author_trash_response.json()["data"]["scenes"] == [
        {
            "scene_id": "CH620_SC01",
            "chapter_id": "CH620",
            "scene_seq": 1,
            "scene_goal": "goal for CH620_SC01",
            "trashed_at": author_trash_response.json()["data"]["scenes"][0]["trashed_at"],
            "trashed_by": "ops.author.chapter",
            "chapter_trashed": 1,
            "restore_allowed": 0,
            "restore_block_reason": "请先恢复所属章节，再恢复该场景",
            "purge_allowed": 0,
            "purge_block_reason": "该场景随章节一起回收，请在章节行中处理",
        },
        {
            "scene_id": "CH620_SC02",
            "chapter_id": "CH620",
            "scene_seq": 2,
            "scene_goal": "goal for CH620_SC02",
            "trashed_at": author_trash_response.json()["data"]["scenes"][1]["trashed_at"],
            "trashed_by": "ops.author.chapter",
            "chapter_trashed": 1,
            "restore_allowed": 0,
            "restore_block_reason": "请先恢复所属章节，再恢复该场景",
            "purge_allowed": 0,
            "purge_block_reason": "该场景随章节一起回收，请在章节行中处理",
        },
    ]

    scene_restore_response = client.post(
        "/api/v1/scenes/restore",
        json={"scene_ids": ["CH620_SC01"]},
        headers={"X-Idempotency-Key": "restore-ch620-sc01"},
    )
    assert scene_restore_response.status_code == 200
    assert scene_restore_response.json()["data"] == {
        "processed": [],
        "blocked": [
            {
                "scene_id": "CH620_SC01",
                "code": "SCENE_RESTORE_BLOCKED_CHAPTER_TRASHED",
                "message": "请先恢复所属章节，再恢复该场景",
            }
        ],
        "actor_ref": "operator",
    }

    chapter_restore_response = client.post(
        "/api/v1/chapters/restore",
        json={"chapter_ids": ["CH620"]},
        headers={"X-Idempotency-Key": "restore-ch620", "X-Operator-Ref": "ops.author.restore"},
    )

    assert chapter_restore_response.status_code == 200
    assert chapter_restore_response.json()["data"] == {
        "processed": [{"chapter_id": "CH620", "scene_ids": ["CH620_SC01", "CH620_SC02"]}],
        "blocked": [],
        "actor_ref": "ops.author.restore",
    }

    restored_workspace = client.get("/api/v1/chapters/CH620/author-workspace")
    assert restored_workspace.status_code == 200
    assert [scene["scene_id"] for scene in restored_workspace.json()["data"]["scenes"]] == ["CH620_SC01", "CH620_SC02"]


def test_scene_purge_only_succeeds_for_runtime_clean_records(client, session) -> None:
    _create_chapter(client, "CH630", goal="Purge clean scenes only")
    _create_scene(client, "CH630_SC01", chapter_id="CH630", scene_seq=1)
    _create_scene(client, "CH630_SC02", chapter_id="CH630", scene_seq=2, is_chapter_last=1)

    session.add(
        SceneBundle(
            bundle_id="bundle_ch630_sc02",
            scene_id="CH630_SC02",
            chapter_id="CH630",
            execution_mode="P2",
            bundle_snapshot_hash="hash_ch630_sc02",
            frozen_snapshot_json={"scene_id": "CH630_SC02"},
        )
    )
    session.add(
        HumanReviewEvent(
            event_id="human_review_ch630_sc02",
            scene_id="CH630_SC02",
            chapter_id="CH630",
            object_ref="scene_card:CH630_SC02",
            event_source="system",
            status="open",
            allowed_actions_json=["retry_request"],
            details_json={"reason": "needs a human pass"},
        )
    )
    session.commit()

    trash_response = client.post(
        "/api/v1/scenes/trash",
        json={"scene_ids": ["CH630_SC01", "CH630_SC02"]},
        headers={"X-Idempotency-Key": "trash-ch630-scenes"},
    )
    assert trash_response.status_code == 200

    author_trash_response = client.get("/api/v1/author-trash")
    assert author_trash_response.status_code == 200
    assert author_trash_response.json()["data"]["scenes"] == [
        {
            "scene_id": "CH630_SC01",
            "chapter_id": "CH630",
            "scene_seq": 1,
            "scene_goal": "goal for CH630_SC01",
            "trashed_at": author_trash_response.json()["data"]["scenes"][0]["trashed_at"],
            "trashed_by": "operator",
            "chapter_trashed": 0,
            "restore_allowed": 1,
            "restore_block_reason": None,
            "purge_allowed": 1,
            "purge_block_reason": None,
        },
        {
            "scene_id": "CH630_SC02",
            "chapter_id": "CH630",
            "scene_seq": 2,
            "scene_goal": "goal for CH630_SC02",
            "trashed_at": author_trash_response.json()["data"]["scenes"][1]["trashed_at"],
            "trashed_by": "operator",
            "chapter_trashed": 0,
            "restore_allowed": 1,
            "restore_block_reason": None,
            "purge_allowed": 0,
            "purge_block_reason": "场景已有下游运行产物",
        },
    ]

    purge_response = client.post(
        "/api/v1/scenes/purge",
        json={"scene_ids": ["CH630_SC01", "CH630_SC02"]},
        headers={"X-Idempotency-Key": "purge-ch630-scenes"},
    )

    assert purge_response.status_code == 200
    assert purge_response.json()["data"] == {
        "processed": [{"scene_id": "CH630_SC01"}],
        "blocked": [
            {
                "scene_id": "CH630_SC02",
                "code": "SCENE_PURGE_BLOCKED_RUNTIME_ARTIFACTS",
                "message": "场景已有下游运行产物",
            }
        ],
        "actor_ref": "operator",
    }
    assert session.get(SceneCard, "CH630_SC01") is None
    assert session.get(SceneRunState, "CH630_SC01") is None
    assert session.get(SceneCard, "CH630_SC02") is not None


def test_chapter_purge_is_blocked_until_all_child_scenes_are_runtime_clean(client, session) -> None:
    _create_chapter(client, "CH640", goal="Protect chapter purge")
    _create_scene(client, "CH640_SC01", chapter_id="CH640", scene_seq=1, is_chapter_last=1)
    session.add(
        SceneBundle(
            bundle_id="bundle_ch640_sc01",
            scene_id="CH640_SC01",
            chapter_id="CH640",
            execution_mode="P2",
            bundle_snapshot_hash="hash_ch640_sc01",
            frozen_snapshot_json={"scene_id": "CH640_SC01"},
        )
    )
    session.commit()

    trash_response = client.post(
        "/api/v1/chapters/trash",
        json={"chapter_ids": ["CH640"]},
        headers={"X-Idempotency-Key": "trash-ch640"},
    )
    assert trash_response.status_code == 200

    author_trash_response = client.get("/api/v1/author-trash")
    assert author_trash_response.status_code == 200
    assert author_trash_response.json()["data"]["chapters"] == [
        {
            "chapter_id": "CH640",
            "chapter_goal": "Protect chapter purge",
            "trashed_at": author_trash_response.json()["data"]["chapters"][0]["trashed_at"],
            "trashed_by": "operator",
            "scene_count": 1,
            "restore_allowed": 1,
            "restore_block_reason": None,
            "purge_allowed": 0,
            "purge_block_reason": "章节下仍有场景存在下游运行产物",
        }
    ]

    purge_response = client.post(
        "/api/v1/chapters/purge",
        json={"chapter_ids": ["CH640"]},
        headers={"X-Idempotency-Key": "purge-ch640"},
    )
    assert purge_response.status_code == 200
    assert purge_response.json()["data"] == {
        "processed": [],
        "blocked": [
            {
                "chapter_id": "CH640",
                "code": "CHAPTER_PURGE_BLOCKED_RUNTIME_ARTIFACTS",
                "message": "章节下仍有场景存在下游运行产物",
            }
        ],
        "actor_ref": "operator",
    }
    assert session.get(ChapterGoal, "CH640") is not None
    remaining_scene_ids = session.execute(select(SceneCard.scene_id).where(SceneCard.chapter_id == "CH640")).scalars().all()
    assert remaining_scene_ids == ["CH640_SC01"]
