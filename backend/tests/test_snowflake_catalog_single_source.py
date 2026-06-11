from novel_system.services import snowflake_steps as steps_mod
from novel_system.services.snowflake_planner import SNOWFLAKE_STEPS, STEP_INDEX


def test_planner_steps_are_derived_from_the_single_catalog() -> None:
    catalog = steps_mod.SNOWFLAKE_STEP_CATALOG
    # 同样的步骤、同样的顺序
    assert [s["step_key"] for s in SNOWFLAKE_STEPS] == [s["step_key"] for s in catalog]
    assert STEP_INDEX == steps_mod.STEP_ORDER


def test_skippable_is_consistent_across_services() -> None:
    catalog = steps_mod.SNOWFLAKE_STEP_CATALOG
    cat_skip = {s["step_key"]: bool(s.get("skippable")) for s in catalog}
    plan_skip = {s["step_key"]: bool(s.get("skippable")) for s in SNOWFLAKE_STEPS}
    # planner 与目录对每一步的可跳过性完全一致（不再分叉）
    assert plan_skip == cat_skip
    # 且「可跳过」== 「非物化必需的 warning 步骤」
    required = set(steps_mod.MATERIALIZATION_REQUIRED_STEPS)
    for s in catalog:
        assert bool(s.get("skippable")) == (s["step_key"] not in required)
