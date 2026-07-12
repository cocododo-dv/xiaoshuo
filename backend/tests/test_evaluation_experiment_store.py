"""Wave 5 — evaluation 三张表建表 + Alembic 迁移三件套（§6.2）。"""
from __future__ import annotations

import sqlalchemy as sa

from novel_system.db.models import (
    Base,
    EvaluationExperiment,
    EvaluationPair,
    EvaluationVote,
)


def test_orm_models_registered() -> None:
    for name in ("evaluation_experiments", "evaluation_pairs", "evaluation_votes"):
        assert name in Base.metadata.tables


def test_tables_persist_rows(session) -> None:
    session.add(EvaluationExperiment(experiment_id="exp1", name="BoN vs 单发"))
    session.add(EvaluationPair(
        pair_id="p1", experiment_id="exp1", scene_snapshot_hash="h1",
        left_text="左", right_text="右", blind_mapping_json={"treatment_slot": "left"},
    ))
    session.add(EvaluationVote(vote_id="v1", pair_id="p1", choice="left", duration_ms=1200))
    session.commit()
    assert session.get(EvaluationExperiment, "exp1").name == "BoN vs 单发"
    assert session.get(EvaluationPair, "p1").blind_mapping_json["treatment_slot"] == "left"
    assert session.get(EvaluationVote, "v1").choice == "left"


def test_migration_upgrade_head_builds_eval_tables(tmp_path, monkeypatch) -> None:
    """隔离库跑 alembic upgrade head → 三表存在（迁移三件套的迁移半边）。

    env.py 无条件用 ``get_settings().database_url`` 覆盖 sqlalchemy.url，且 get_settings
    每次读 NOVEL_SYSTEM_DATABASE_URL——故用 monkeypatch 指向隔离库，让迁移在全新链上跑。
    """
    from alembic.config import Config
    from alembic import command

    db_path = tmp_path / "wave5_migrate.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("NOVEL_SYSTEM_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")

    engine = sa.create_engine(url)
    tables = set(sa.inspect(engine).get_table_names())
    engine.dispose()
    assert {"evaluation_experiments", "evaluation_pairs", "evaluation_votes"} <= tables
