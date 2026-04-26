from __future__ import annotations

import ast
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from novel_system.db.models import ChapterRunJob, FinalScene, LlmCall, QcReport, SceneDraft


EXPECTED_PATCH_CANDIDATE_METADATA_COLUMNS = {
    "candidate_category",
    "target_range_json",
    "revision_strategy",
    "preference_tags_json",
    "inserted_into_author_draft",
}

EXPECTED_AUTHOR_DRAFT_PROPOSAL_COLUMNS = {
    "proposal_id",
    "draft_id",
    "object_type",
    "object_id",
    "proposal_type",
    "content",
    "rationale",
    "source_llm_call_id",
    "status",
    "author_decision_note",
}


def test_generation_persistence_migration_is_frozen_with_explicit_ddl() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260414_0007_add_llm_qc_and_chapter_jobs.py"
    )
    migration_source = migration_path.read_text(encoding="utf-8")
    migration_module = ast.parse(migration_source)
    downgrade_function = next(
        node for node in migration_module.body if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )

    assert re.search(r'op\.create_table\(\s*"llm_calls"', migration_source)
    assert re.search(r'op\.create_table\(\s*"qc_reports"', migration_source)
    assert re.search(r'op\.create_table\(\s*"chapter_run_jobs"', migration_source)
    assert "Base.metadata.create_all" not in migration_source
    assert ".drop(bind=" not in migration_source
    assert re.search(r"dynamic base migration", migration_source)
    assert len(downgrade_function.body) == 1
    assert isinstance(downgrade_function.body[0], ast.Pass)


def test_generation_persistence_alembic_schema_contract(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "generation-persistence-head.sqlite"

    _run_alembic(repo_root, db_path, "head")

    connection = sqlite3.connect(db_path)
    try:
        table_names = _table_names(connection)
        llm_columns = _pragma_columns_by_name(connection, "llm_calls")
        qc_columns = _pragma_columns_by_name(connection, "qc_reports")
        draft_columns = _pragma_columns_by_name(connection, "scene_drafts")
        final_columns = _pragma_columns_by_name(connection, "final_scenes")
        chapter_job_columns = _pragma_columns_by_name(connection, "chapter_run_jobs")
        patch_columns = _pragma_columns_by_name(connection, "passage_patch_candidates")
        proposal_columns = _pragma_columns_by_name(connection, "author_draft_proposals")
    finally:
        connection.close()

    assert "llm_calls" in table_names
    assert "qc_reports" in table_names
    assert "chapter_run_jobs" in table_names
    assert "author_draft_proposals" in table_names
    assert {
        "llm_call_id",
        "provider",
        "provider_id",
        "account_id",
        "model",
        "node_id",
        "reasoning_level",
        "native_reasoning_json",
        "credential_mode",
        "prompt_hash",
        "step",
        "scene_id",
        "chapter_id",
        "request_payload_summary",
        "response_payload_summary",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "finish_reason",
        "error_code",
    } <= llm_columns.keys()
    assert {
        "qc_report_id",
        "scene_id",
        "chapter_id",
        "qc_type",
        "source_draft_row_id",
        "source_bundle_id",
        "resolution_code",
        "pass_flag",
        "next_action",
        "issues_json",
        "rewrite_brief_json",
    } <= qc_columns.keys()
    assert "generation_llm_call_id" in draft_columns
    assert "generation_llm_call_id" in final_columns
    assert {"job_id", "chapter_id", "status", "job_type"} <= chapter_job_columns.keys()
    assert EXPECTED_PATCH_CANDIDATE_METADATA_COLUMNS <= patch_columns.keys()
    assert EXPECTED_AUTHOR_DRAFT_PROPOSAL_COLUMNS <= proposal_columns.keys()
    assert chapter_job_columns["status"][3] == 1
    assert chapter_job_columns["job_type"][3] == 1


def test_generation_persistence_orm_round_trip(session) -> None:

    llm_call = LlmCall(
        llm_call_id="llm_call_scene_CH001_SC01_style",
        provider="demo-provider",
        model="demo-model",
        prompt_hash="hash_prompt_demo",
        step="style_draft",
        scene_id="CH001_SC01",
        chapter_id="CH001",
        request_payload_summary={"messages": 3, "temperature": 0.7},
        response_payload_summary={"choice_count": 1},
        prompt_tokens=123,
        completion_tokens=456,
        total_tokens=579,
        latency_ms=2300,
        finish_reason="stop",
        error_code=None,
    )
    session.add(llm_call)
    session.add(
        ChapterRunJob(
            job_id="chapter_job_CH001_qc_pass",
            chapter_id="CH001",
            status="queued",
            job_type="chapter_qc",
        )
    )
    session.add(
        SceneDraft(
            row_id="draft_CH001_SC01_style_v1",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            stage="style_draft",
            content="draft text",
            source_bundle_id="bundle_CH001_SC01",
            source_bundle_hash="bundle_hash_demo",
            generation_llm_call_id=llm_call.llm_call_id,
        )
    )
    session.add(
        FinalScene(
            row_id="final_scene_CH001_SC01_v1",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            content="final text",
            status="approved",
            source_bundle_id="bundle_CH001_SC01",
            source_bundle_hash="bundle_hash_demo",
            generation_llm_call_id=llm_call.llm_call_id,
        )
    )
    session.add(
        QcReport(
            qc_report_id="qc_report_CH001_SC01_hard_v1",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            qc_type="hard_qc",
            source_draft_row_id="draft_CH001_SC01_style_v1",
            source_bundle_id="bundle_CH001_SC01",
            resolution_code="hard_pass",
            pass_flag=1,
            next_action="pass",
            issues_json=[{"issue_key": "continuity_ok"}],
            rewrite_brief_json=[],
        )
    )
    session.commit()

    stored_qc = session.get(QcReport, "qc_report_CH001_SC01_hard_v1")
    stored_draft = session.get(SceneDraft, "draft_CH001_SC01_style_v1")
    stored_final = session.get(FinalScene, "final_scene_CH001_SC01_v1")

    assert stored_qc is not None
    assert stored_qc.source_draft_row_id == "draft_CH001_SC01_style_v1"
    assert stored_qc.issues_json == [{"issue_key": "continuity_ok"}]
    assert stored_draft is not None
    assert stored_draft.generation_llm_call_id == llm_call.llm_call_id
    assert stored_final is not None
    assert stored_final.generation_llm_call_id == llm_call.llm_call_id


def test_generation_persistence_upgrade_keeps_historical_rows_readable(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "generation-persistence.sqlite"

    _build_true_pre_0007_database(db_path)
    _run_alembic(repo_root, db_path, "head")

    connection = sqlite3.connect(db_path)
    try:
        table_names = _table_names(connection)
        draft_columns = _pragma_columns_by_name(connection, "scene_drafts")
        final_columns = _pragma_columns_by_name(connection, "final_scenes")
        llm_columns = _pragma_columns_by_name(connection, "llm_calls")
        qc_columns = _pragma_columns_by_name(connection, "qc_reports")
        job_columns = _pragma_columns_by_name(connection, "chapter_run_jobs")
        config_columns = _pragma_columns_by_name(connection, "system_config_snapshots")
        secret_columns = _pragma_columns_by_name(connection, "system_secrets")
        author_structure_columns = _pragma_columns_by_name(connection, "author_structure_candidates")
        planning_columns = _pragma_columns_by_name(connection, "generation_planning_artifacts")
        patch_columns = _pragma_columns_by_name(connection, "passage_patch_candidates")
        proposal_columns = _pragma_columns_by_name(connection, "author_draft_proposals")
        historical_draft = connection.execute(
            """
            SELECT row_id, scene_id, chapter_id, stage, generation_llm_call_id
            FROM scene_drafts
            WHERE row_id = 'draft_hist_CH001_SC01'
            """
        ).fetchone()
        historical_final = connection.execute(
            """
            SELECT row_id, scene_id, chapter_id, status, generation_llm_call_id
            FROM final_scenes
            WHERE row_id = 'final_hist_CH001_SC01'
            """
        ).fetchone()
        version_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()

    assert version_row == ("20260426_0021",)
    assert "llm_calls" in table_names
    assert "qc_reports" in table_names
    assert "chapter_run_jobs" in table_names
    assert "scene_blueprints" in table_names
    assert "passage_patch_candidates" in table_names
    assert "author_preference_profiles" in table_names
    assert "author_drafts" in table_names
    assert "author_draft_events" in table_names
    assert "author_draft_proposals" in table_names
    assert "author_structure_candidates" in table_names
    assert "generation_planning_artifacts" in table_names
    assert "longform_diagnostic_cards" in table_names
    assert "longform_structure_guidance" in table_names
    assert "system_config_snapshots" in table_names
    assert "system_secrets" in table_names
    assert "generation_llm_call_id" in draft_columns
    assert "generation_llm_call_id" in final_columns
    assert {"llm_call_id", "provider", "provider_id", "account_id", "model", "node_id"} <= llm_columns.keys()
    assert {"qc_report_id", "source_draft_row_id", "issues_json"} <= qc_columns.keys()
    assert {"job_id", "chapter_id", "status", "job_type"} <= job_columns.keys()
    assert {"snapshot_id", "category", "version", "yaml_raw", "active_flag"} <= config_columns.keys()
    assert {"secret_id", "encrypted_value", "value_hint", "secret_type", "metadata_json", "expires_at"} <= secret_columns.keys()
    assert {
        "candidate_id",
        "object_type",
        "object_id",
        "source_draft_id",
        "candidate_brief_json",
        "status",
        "author_decision",
    } <= author_structure_columns.keys()
    assert {
        "row_id",
        "artifact_type",
        "object_type",
        "object_id",
        "payload_json",
        "status",
    } <= planning_columns.keys()
    assert EXPECTED_PATCH_CANDIDATE_METADATA_COLUMNS <= patch_columns.keys()
    assert EXPECTED_AUTHOR_DRAFT_PROPOSAL_COLUMNS <= proposal_columns.keys()
    assert job_columns["status"][3] == 1
    assert job_columns["job_type"][3] == 1
    assert historical_draft == ("draft_hist_CH001_SC01", "CH001_SC01", "CH001", "neutral_draft", None)
    assert historical_final == ("final_hist_CH001_SC01", "CH001_SC01", "CH001", "approved", None)


def test_generation_persistence_downgrade_is_non_destructive_on_dynamic_checkout(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "generation-persistence-downgrade.sqlite"

    _run_alembic(repo_root, db_path, "head")
    _run_alembic_downgrade(repo_root, db_path, "20260413_0006")

    connection = sqlite3.connect(db_path)
    try:
        table_names = _table_names(connection)
        draft_columns = _pragma_columns_by_name(connection, "scene_drafts")
        final_columns = _pragma_columns_by_name(connection, "final_scenes")
        version_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()

    assert version_row == ("20260413_0006",)
    assert "llm_calls" in table_names
    assert "qc_reports" in table_names
    assert "chapter_run_jobs" in table_names
    assert "generation_llm_call_id" in draft_columns
    assert "generation_llm_call_id" in final_columns


def test_generation_persistence_upgrade_is_idempotent_when_0006_already_materialized_task3_objects(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "generation-persistence-idempotent.sqlite"

    _run_alembic(repo_root, db_path, "20260413_0006")
    _seed_dynamic_0006_materialized_generation_rows(db_path)
    _run_alembic(repo_root, db_path, "head")

    connection = sqlite3.connect(db_path)
    try:
        table_names = _table_names(connection)
        llm_call = connection.execute(
            """
            SELECT llm_call_id, provider, model, step, total_tokens
            FROM llm_calls
            WHERE llm_call_id = 'llm_call_existing'
            """
        ).fetchone()
        qc_report = connection.execute(
            """
            SELECT qc_report_id, source_draft_row_id, source_bundle_id, next_action
            FROM qc_reports
            WHERE qc_report_id = 'qc_report_existing'
            """
        ).fetchone()
        chapter_job = connection.execute(
            """
            SELECT job_id, chapter_id, status, job_type
            FROM chapter_run_jobs
            WHERE job_id = 'chapter_job_existing'
            """
        ).fetchone()
        config_columns = _pragma_columns_by_name(connection, "system_config_snapshots")
        secret_columns = _pragma_columns_by_name(connection, "system_secrets")
        author_structure_columns = _pragma_columns_by_name(connection, "author_structure_candidates")
        planning_columns = _pragma_columns_by_name(connection, "generation_planning_artifacts")
        patch_columns = _pragma_columns_by_name(connection, "passage_patch_candidates")
        proposal_columns = _pragma_columns_by_name(connection, "author_draft_proposals")
        scene_draft = connection.execute(
            """
            SELECT row_id, generation_llm_call_id
            FROM scene_drafts
            WHERE row_id = 'draft_existing'
            """
        ).fetchone()
        final_scene = connection.execute(
            """
            SELECT row_id, generation_llm_call_id
            FROM final_scenes
            WHERE row_id = 'final_existing'
            """
        ).fetchone()
        version_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()

    assert version_row == ("20260426_0021",)
    assert "llm_calls" in table_names
    assert "qc_reports" in table_names
    assert "chapter_run_jobs" in table_names
    assert "scene_blueprints" in table_names
    assert "passage_patch_candidates" in table_names
    assert "author_preference_profiles" in table_names
    assert "author_drafts" in table_names
    assert "author_draft_events" in table_names
    assert "author_draft_proposals" in table_names
    assert "author_structure_candidates" in table_names
    assert "generation_planning_artifacts" in table_names
    assert "longform_diagnostic_cards" in table_names
    assert "longform_structure_guidance" in table_names
    assert "system_config_snapshots" in table_names
    assert "system_secrets" in table_names
    assert {"snapshot_id", "category", "version", "yaml_raw", "active_flag"} <= config_columns.keys()
    assert {"secret_id", "encrypted_value", "value_hint", "secret_type", "metadata_json", "expires_at"} <= secret_columns.keys()
    assert {
        "candidate_id",
        "object_type",
        "object_id",
        "source_draft_id",
        "candidate_brief_json",
        "status",
        "author_decision",
    } <= author_structure_columns.keys()
    assert {
        "row_id",
        "artifact_type",
        "object_type",
        "object_id",
        "payload_json",
        "status",
    } <= planning_columns.keys()
    assert EXPECTED_PATCH_CANDIDATE_METADATA_COLUMNS <= patch_columns.keys()
    assert EXPECTED_AUTHOR_DRAFT_PROPOSAL_COLUMNS <= proposal_columns.keys()
    assert llm_call == ("llm_call_existing", "seed-provider", "seed-model", "style_draft", 42)
    assert qc_report == ("qc_report_existing", "draft_existing", "bundle_existing", "pass")
    assert chapter_job == ("chapter_job_existing", "CH001", "queued", "chapter_qc")
    assert scene_draft == ("draft_existing", "llm_call_existing")
    assert final_scene == ("final_existing", "llm_call_existing")


def _run_alembic(backend_dir: Path, db_path: Path, revision: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir / "src")
    env["NOVEL_SYSTEM_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend_dir / "alembic.ini"), "upgrade", revision],
        cwd=backend_dir,
        env=env,
        check=True,
    )


def _run_alembic_downgrade(backend_dir: Path, db_path: Path, revision: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir / "src")
    env["NOVEL_SYSTEM_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend_dir / "alembic.ini"), "downgrade", revision],
        cwd=backend_dir,
        env=env,
        check=True,
    )


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _pragma_columns_by_name(connection: sqlite3.Connection, table_name: str) -> dict[str, tuple]:
    return {row[1]: row for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _build_true_pre_0007_database(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            )
            """
        )
        connection.execute("INSERT INTO alembic_version (version_num) VALUES ('20260413_0006')")
        connection.execute(
            """
            CREATE TABLE scene_drafts (
                row_id VARCHAR NOT NULL PRIMARY KEY,
                scene_id VARCHAR NOT NULL,
                chapter_id VARCHAR NOT NULL,
                stage VARCHAR NOT NULL,
                content TEXT NOT NULL,
                source_bundle_id VARCHAR NOT NULL,
                source_bundle_hash VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE final_scenes (
                row_id VARCHAR NOT NULL PRIMARY KEY,
                scene_id VARCHAR NOT NULL,
                chapter_id VARCHAR NOT NULL,
                content TEXT NOT NULL,
                status VARCHAR NOT NULL,
                source_bundle_id VARCHAR NOT NULL,
                source_bundle_hash VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO scene_drafts (
                row_id,
                scene_id,
                chapter_id,
                stage,
                content,
                source_bundle_id,
                source_bundle_hash,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "draft_hist_CH001_SC01",
                "CH001_SC01",
                "CH001",
                "neutral_draft",
                "historical draft text",
                "bundle_hist_CH001_SC01",
                "bundle_hash_hist",
                "2026-04-13T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO final_scenes (
                row_id,
                scene_id,
                chapter_id,
                content,
                status,
                source_bundle_id,
                source_bundle_hash,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "final_hist_CH001_SC01",
                "CH001_SC01",
                "CH001",
                "historical final text",
                "approved",
                "bundle_hist_CH001_SC01",
                "bundle_hash_hist",
                "2026-04-13T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _seed_dynamic_0006_materialized_generation_rows(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO llm_calls (
                llm_call_id,
                provider,
                model,
                prompt_hash,
                step,
                scene_id,
                chapter_id,
                request_payload_summary,
                response_payload_summary,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                latency_ms,
                finish_reason,
                error_code,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "llm_call_existing",
                "seed-provider",
                "seed-model",
                "prompt_hash_existing",
                "style_draft",
                "CH001_SC01",
                "CH001",
                '{"messages": 1}',
                '{"choices": 1}',
                10,
                32,
                42,
                1500,
                "stop",
                None,
                "2026-04-14T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO scene_drafts (
                row_id,
                scene_id,
                chapter_id,
                stage,
                content,
                source_bundle_id,
                source_bundle_hash,
                generation_llm_call_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "draft_existing",
                "CH001_SC01",
                "CH001",
                "style_draft",
                "existing draft",
                "bundle_existing",
                "bundle_hash_existing",
                "llm_call_existing",
                "2026-04-14T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO final_scenes (
                row_id,
                scene_id,
                chapter_id,
                content,
                status,
                source_bundle_id,
                source_bundle_hash,
                generation_llm_call_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "final_existing",
                "CH001_SC01",
                "CH001",
                "existing final",
                "approved",
                "bundle_existing",
                "bundle_hash_existing",
                "llm_call_existing",
                "2026-04-14T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO qc_reports (
                qc_report_id,
                scene_id,
                chapter_id,
                qc_type,
                source_draft_row_id,
                source_bundle_id,
                resolution_code,
                pass_flag,
                next_action,
                issues_json,
                rewrite_brief_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "qc_report_existing",
                "CH001_SC01",
                "CH001",
                "hard_qc",
                "draft_existing",
                "bundle_existing",
                "hard_pass",
                1,
                "pass",
                '[{"issue_key":"ok"}]',
                "[]",
                "2026-04-14T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO chapter_run_jobs (
                job_id,
                chapter_id,
                status,
                job_type,
                payload_json,
                result_summary_json,
                worker_id,
                attempt_no,
                heartbeat_at,
                lease_expires_at,
                started_at,
                finished_at,
                error_code,
                error_text,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "chapter_job_existing",
                "CH001",
                "queued",
                "chapter_qc",
                '{"scene_count": 1}',
                '{"status": "pending"}',
                None,
                1,
                None,
                None,
                None,
                None,
                None,
                None,
                "2026-04-14T00:00:00+00:00",
                "2026-04-14T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()
