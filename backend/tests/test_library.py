"""资料库(library)实体与关系 — 后端 P0 回归测试。

Conventions mirror tests/test_character_entity_sync.py (``client`` + ``session``
fixtures from conftest.py).
"""
from __future__ import annotations

import uuid


def _idem() -> dict:
    return {"X-Idempotency-Key": f"lib-test-{uuid.uuid4().hex[:10]}"}

from novel_system.db.models import StoryCharacter


def _create_project(client) -> dict:
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "盐镇来信",
            "genre": "悬疑",
            "target_chapter_count": 2,
            "target_word_count": 100000,
            "outline_text": "怀梅在盐场捡到一枚注销的旧工牌。\n她追查工牌主人。\n真相牵出家史。",
            "planning_mode": "snowflake",
        },
        headers={"X-Idempotency-Key": f"create-{uuid.uuid4().hex}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["project"]


def _seed_character(session, project_id: str, character_id: str = "CHAR_HM") -> StoryCharacter:
    character = StoryCharacter(
        character_id=character_id,
        project_id=project_id,
        display_name="苏怀梅",
        role="主角",
        summary_json={"one_line": "替父亲跑腿时撞见家史边缘的女儿"},
        status="draft",
    )
    session.add(character)
    session.commit()
    return character


def test_library_overview_merges_characters_and_entities(client, session) -> None:
    project = _create_project(client)
    _seed_character(session, project["project_id"])

    created = client.post(
        f"/api/v2/projects/{project['project_id']}/library/entities",
        json={"kind": "location", "name": "盐场", "summary": "故事的秩序中心", "tags": ["第一幕"]},
        headers=_idem(),
    )
    assert created.status_code == 200, created.text
    entity = created.json()["data"]
    assert entity["ref"].startswith("entity:")
    assert entity["kind"] == "location"

    overview = client.get(f"/api/v2/projects/{project['project_id']}/library")
    assert overview.status_code == 200, overview.text
    data = overview.json()["data"]
    assert [item["name"] for item in data["characters"]] == ["苏怀梅"]
    assert data["characters"][0]["kind"] == "character"
    assert data["characters"][0]["summary"] == "替父亲跑腿时撞见家史边缘的女儿"
    assert [item["name"] for item in data["entities"]] == ["盐场"]
    assert data["relations"] == []


def test_library_entity_validation_and_update(client) -> None:
    project = _create_project(client)

    missing_name = client.post(
        f"/api/v2/projects/{project['project_id']}/library/entities",
        json={"kind": "location", "name": "  "},
        headers=_idem(),
    )
    assert missing_name.status_code == 400
    assert missing_name.json()["error"]["code"] == "LIBRARY_ENTITY_NAME_REQUIRED"

    bad_kind = client.post(
        f"/api/v2/projects/{project['project_id']}/library/entities",
        json={"kind": "spaceship", "name": "X"},
        headers=_idem(),
    )
    assert bad_kind.status_code == 400
    assert bad_kind.json()["error"]["code"] == "LIBRARY_ENTITY_KIND_INVALID"

    entity = client.post(
        f"/api/v2/projects/{project['project_id']}/library/entities",
        json={"kind": "item", "name": "旧工牌"},
        headers=_idem(),
    ).json()["data"]

    updated = client.patch(
        f"/api/v2/projects/{project['project_id']}/library/entities/{entity['entity_id']}",
        json={"summary": "名字被磨掉的注销工牌", "status": "archived", "tags": ["线索"]},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert body["summary"] == "名字被磨掉的注销工牌"
    assert body["status"] == "archived"
    assert body["tags"] == ["线索"]


def test_library_relations_validate_refs_and_scope(client, session) -> None:
    project = _create_project(client)
    character = _seed_character(session, project["project_id"])
    entity = client.post(
        f"/api/v2/projects/{project['project_id']}/library/entities",
        json={"kind": "location", "name": "祖屋"},
        headers=_idem(),
    ).json()["data"]

    relation = client.post(
        f"/api/v2/projects/{project['project_id']}/library/relations",
        json={
            "from_ref": f"character:{character.character_id}",
            "to_ref": entity["ref"],
            "kind": "lives_in",
            "note": "三代同堂的老宅",
        },
        headers=_idem(),
    )
    assert relation.status_code == 200, relation.text
    relation_body = relation.json()["data"]
    assert relation_body["kind"] == "lives_in"

    bad_ref = client.post(
        f"/api/v2/projects/{project['project_id']}/library/relations",
        json={"from_ref": "scene:SC01", "to_ref": entity["ref"]},
        headers=_idem(),
    )
    assert bad_ref.status_code == 400
    assert bad_ref.json()["error"]["code"] == "LIBRARY_RELATION_REF_INVALID"

    self_loop = client.post(
        f"/api/v2/projects/{project['project_id']}/library/relations",
        json={"from_ref": entity["ref"], "to_ref": entity["ref"]},
        headers=_idem(),
    )
    assert self_loop.status_code == 400
    assert self_loop.json()["error"]["code"] == "LIBRARY_RELATION_SELF_LOOP"

    other_project = _create_project(client)
    cross_scope = client.get(f"/api/v2/projects/{other_project['project_id']}/library")
    assert cross_scope.status_code == 200
    assert cross_scope.json()["data"]["entities"] == []
    assert cross_scope.json()["data"]["relations"] == []

    deleted = client.delete(
        f"/api/v2/projects/{project['project_id']}/library/relations/{relation_body['relation_id']}",
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

    overview = client.get(f"/api/v2/projects/{project['project_id']}/library")
    assert overview.json()["data"]["relations"] == []
