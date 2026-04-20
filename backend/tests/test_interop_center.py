from __future__ import annotations

from textwrap import dedent

import yaml
from sqlalchemy import text

from .test_orchestrator_flow import seed_story, seed_traceable_bundle_sources


def _seed_active_style_rule(session) -> None:
    session.execute(
        text(
            """
            INSERT INTO style_rules (
                row_id,
                style_rule_set_id,
                version,
                scope,
                scope_ref_id,
                content,
                source_review_id,
                active_flag,
                runtime_eligible,
                runtime_eligibility_basis,
                effective_at,
                created_at,
                updated_at
            ) VALUES (
                'style_rule_STYLE_GLOBAL_MAIN_v1',
                'STYLE_GLOBAL_MAIN',
                1,
                'global',
                'global',
                'keep the reunion tight and gesture-led',
                NULL,
                1,
                1,
                'direct_read',
                NULL,
                '2026-04-11T00:00:00Z',
                '2026-04-11T00:00:00Z'
            )
            """
        )
    )
    session.execute(
        text(
            """
            INSERT INTO version_registry (
                object_type,
                lineage_key,
                version,
                physical_row_id,
                alias_scope,
                materialize_status,
                reindex_status,
                verify_status,
                sample_query_success,
                approved_at,
                materialized_at,
                activated_at,
                reindexed_at,
                notes
            ) VALUES (
                'style_rule',
                'STYLE_GLOBAL_MAIN',
                1,
                'style_rule_STYLE_GLOBAL_MAIN_v1',
                NULL,
                'succeeded',
                'not_required',
                'not_required',
                0,
                '2026-04-11T00:00:00Z',
                '2026-04-11T00:00:00Z',
                '2026-04-11T00:00:00Z',
                NULL,
                NULL
            )
            """
        )
    )
    session.commit()


def _worksheet_payload(*, bundle_id: str = "bundle_interop_import_v1", bundle_snapshot_hash: str | None = None) -> dict:
    payload = {
        "bundle_id": bundle_id,
        "scene_id": "CH001_SC01",
        "chapter_id": "CH001",
        "hash_contract_version": "BSHASH_v1",
        "hash_alg": "sha256",
        "execution_mode": "P1_scripted",
        "created_by_action": "bundle_worksheet_import",
        "snapshot": {
            "contract_version": "BSHASH_v1",
            "stage_allowlist_name": "bundle_build_allowlist_v1",
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "source_version_refs": {
                "chapter_goal": "CH001",
                "scene_card": "CH001_SC01",
                "style_rule_set_id": "STYLE_GLOBAL_MAIN",
            },
            "resolved_ref_ids": {
                "relation_ids": [],
                "world_rule_ids": [],
                "open_foreshadow_ids": [],
            },
            "ordered_injections": [
                {"slot": "chapter_goal", "ref_id": "CH001", "digest_key": "chapter_goal"},
                {"slot": "scene_card", "ref_id": "CH001_SC01", "digest_key": "scene_card"},
                {"slot": "style_rules", "ref_id": "STYLE_GLOBAL_MAIN", "digest_key": "style_rule"},
            ],
            "inline_digests": {
                "chapter_goal": "close the reunion chapter with a traceable knowledge bundle",
                "scene_card": "reunite the two leads and surface the old letter clue",
                "style_rule": "keep emotion in gesture and pause",
            },
        },
    }
    if bundle_snapshot_hash is not None:
        payload["bundle_snapshot_hash"] = bundle_snapshot_hash
    return payload


def _worksheet_yaml(*, bundle_id: str = "bundle_interop_import_v1", bundle_snapshot_hash: str | None = None) -> str:
    return yaml.safe_dump(
        _worksheet_payload(bundle_id=bundle_id, bundle_snapshot_hash=bundle_snapshot_hash),
        sort_keys=False,
        allow_unicode=True,
    )


def test_preview_rejects_invalid_yaml(client) -> None:
    response = client.post(
        "/api/v1/interop/preview/bundle-worksheet",
        json={"worksheet_yaml": "bundle_id: [unterminated"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BUNDLE_WORKSHEET_YAML_INVALID"


def test_preview_returns_normalized_envelope_and_source_ref_comparisons_without_persisting(client, session) -> None:
    seed_story(client, session=session)
    _seed_active_style_rule(session)

    response = client.post(
        "/api/v1/interop/preview/bundle-worksheet",
        json={"worksheet_yaml": _worksheet_yaml()},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["envelope"]["bundle_id"] == "bundle_interop_import_v1"
    assert data["hash_validation"]["status"] == "computed"
    assert data["hash_validation"]["computed_hash"]

    style_rule_comparison = next(
        item for item in data["source_ref_comparisons"] if item["object_type"] == "style_rule"
    )
    assert style_rule_comparison["lineage_key"] == "STYLE_GLOBAL_MAIN"
    assert style_rule_comparison["source_ref_key"] == "style_rule_set_id"
    assert style_rule_comparison["source_text"] == "keep emotion in gesture and pause"
    assert style_rule_comparison["active_text"] == "keep the reunion tight and gesture-led"
    assert style_rule_comparison["text_status"] == "changed"
    assert session.execute(text("SELECT COUNT(*) FROM scene_bundles")).scalar_one() == 0


def test_import_persists_bundle_and_interop_artifact(client, session) -> None:
    seed_story(client, session=session)
    _seed_active_style_rule(session)

    response = client.post(
        "/api/v1/interop/import/bundle-worksheet",
        json={"worksheet_yaml": _worksheet_yaml()},
        headers={"X-Idempotency-Key": "interop-import-1"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["bundle"]["bundle_id"] == "bundle_interop_import_v1"
    assert data["artifact_receipt"]["artifact_kind"] == "bundle_worksheet_import"
    assert data["artifact_receipt"]["direction"] == "import"
    assert data["artifact_receipt"]["file_path"].startswith("inline://interop-center/")

    bundle_row = session.execute(
        text(
            "SELECT execution_mode, bundle_snapshot_hash FROM scene_bundles WHERE bundle_id = 'bundle_interop_import_v1'"
        )
    ).one()
    assert bundle_row.execution_mode == "P1_scripted"
    assert bundle_row.bundle_snapshot_hash == data["bundle"]["bundle_snapshot_hash"]

    artifact_row = session.execute(
        text(
            """
            SELECT artifact_kind, direction, file_format, status, source_bundle_id
            FROM interop_artifacts
            WHERE source_bundle_id = 'bundle_interop_import_v1'
            """
        )
    ).one()
    assert artifact_row.artifact_kind == "bundle_worksheet_import"
    assert artifact_row.direction == "import"
    assert artifact_row.file_format == "yaml"
    assert artifact_row.status == "completed"


def test_import_reuses_existing_bundle_for_same_hash_and_conflicts_for_different_hash(client, session) -> None:
    seed_story(client, session=session)
    _seed_active_style_rule(session)

    first = client.post(
        "/api/v1/interop/import/bundle-worksheet",
        json={"worksheet_yaml": _worksheet_yaml(bundle_id="bundle_interop_reuse")},
        headers={"X-Idempotency-Key": "interop-import-reuse-1"},
    )
    assert first.status_code == 200

    reused = client.post(
        "/api/v1/interop/import/bundle-worksheet",
        json={"worksheet_yaml": _worksheet_yaml(bundle_id="bundle_interop_reuse")},
        headers={"X-Idempotency-Key": "interop-import-reuse-2"},
    )
    assert reused.status_code == 200
    assert reused.json()["data"]["bundle"]["reused_existing_bundle"] is True

    conflicting_yaml = dedent(
        """
        bundle_id: bundle_interop_reuse
        scene_id: CH001_SC01
        chapter_id: CH001
        hash_contract_version: BSHASH_v1
        hash_alg: sha256
        execution_mode: P1_scripted
        created_by_action: bundle_worksheet_import
        snapshot:
          contract_version: BSHASH_v1
          stage_allowlist_name: bundle_build_allowlist_v1
          scene_id: CH001_SC01
          chapter_id: CH001
          source_version_refs:
            chapter_goal: CH001
            scene_card: CH001_SC01
            style_rule_set_id: STYLE_GLOBAL_MAIN
          resolved_ref_ids:
            relation_ids: []
            world_rule_ids: []
            open_foreshadow_ids: []
          ordered_injections:
            - slot: chapter_goal
              ref_id: CH001
              digest_key: chapter_goal
            - slot: scene_card
              ref_id: CH001_SC01
              digest_key: scene_card
            - slot: style_rules
              ref_id: STYLE_GLOBAL_MAIN
              digest_key: style_rule
          inline_digests:
            chapter_goal: close the reunion chapter with a traceable knowledge bundle
            scene_card: reunite the two leads and surface the old letter clue
            style_rule: a conflicting import payload
        """
    ).strip()

    conflict = client.post(
        "/api/v1/interop/import/bundle-worksheet",
        json={"worksheet_yaml": conflicting_yaml},
        headers={"X-Idempotency-Key": "interop-import-reuse-3"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "INTEROP_BUNDLE_CONFLICT"


def test_export_and_replay_return_complete_envelopes_with_artifacts_and_diffs(client, session) -> None:
    seed_story(client, session=session)
    _seed_active_style_rule(session)

    run_scene = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "interop-export-run-scene"},
    )
    assert run_scene.status_code == 200
    bundle_id = run_scene.json()["data"]["current_bundle_id"]
    final_scene_row_id = run_scene.json()["data"]["current_final_scene_row_id"]

    export_response = client.get(f"/api/v1/interop/export/bundle-worksheet/{bundle_id}")
    assert export_response.status_code == 200
    export_data = export_response.json()["data"]
    assert export_data["envelope"]["bundle_id"] == bundle_id
    assert export_data["envelope"]["hash_contract_version"] == "BSHASH_v1"
    assert export_data["envelope"]["hash_alg"] == "sha256"
    assert export_data["artifact_receipt"]["artifact_kind"] == "bundle_worksheet_export"
    assert export_data["artifact_receipt"]["direction"] == "export"
    assert export_data["source_ref_comparisons"]
    scene_card_comparison = next(
        item for item in export_data["source_ref_comparisons"] if item["object_type"] == "scene_card"
    )
    assert scene_card_comparison["text_status"] == "same"
    assert scene_card_comparison["active_text"] == scene_card_comparison["source_text"]

    replay_response = client.get(f"/api/v1/replay/final-scene/{final_scene_row_id}")
    assert replay_response.status_code == 200
    replay_data = replay_response.json()["data"]
    assert replay_data["envelope"]["bundle_id"] == bundle_id
    assert replay_data["artifact_receipt"]["artifact_kind"] == "scene_replay_export"
    assert any(item["object_type"] == "style_rule" for item in replay_data["source_ref_comparisons"])
