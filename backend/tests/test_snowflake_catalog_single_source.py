from novel_system.services import snowflake_steps as steps_mod
from novel_system.services.snowflake_planner import SNOWFLAKE_STEPS, STEP_INDEX


# 设计规定的雪花十步顺序 —— 单一事实源的「期望真值」,独立于实现派生。
# 钉成字面量:任何对 SNOWFLAKE_STEP_CATALOG 的重排 / 漏步 / 多步都会让下方断言变红。
# (原断言 [keys for SNOWFLAKE_STEPS] == [keys for catalog] 是同源自比,顺序写错也恒真。)
EXPECTED_STEP_ORDER = [
    "book_brief",
    "one_sentence_summary",
    "one_paragraph_summary",
    "character_sheets",
    "short_synopsis",
    "character_synopses",
    "long_synopsis",
    "character_bibles",
    "scene_list",
    "scene_details",
]
# 物化硬门步骤(设计的第 1/2/3/9/10 步);其余为可跳过的 warning 步骤。
EXPECTED_REQUIRED_STEPS = {
    "book_brief",
    "one_sentence_summary",
    "one_paragraph_summary",
    "scene_list",
    "scene_details",
}


def test_planner_steps_are_derived_from_the_single_catalog() -> None:
    catalog = steps_mod.SNOWFLAKE_STEP_CATALOG
    # (a) 顺序正确性:对独立字面量钉死,而非 catalog 自比自(后者顺序写错也恒真)。
    assert [s["step_key"] for s in catalog] == EXPECTED_STEP_ORDER
    # (b) planner 不分叉出第二份硬编码:其步骤序列与期望真值一致。
    assert [s["step_key"] for s in SNOWFLAKE_STEPS] == EXPECTED_STEP_ORDER
    # (c) STEP_INDEX 是目录顺序的正确投影 —— 对字面量校验,
    #     而非原来的 STEP_INDEX == STEP_ORDER(同一对象的 x==x,永真)。
    assert STEP_INDEX == {key: idx for idx, key in enumerate(EXPECTED_STEP_ORDER)}
    # 仍保留单源守护:planner 复用目录派生的同一对象,而非另立一份。
    assert STEP_INDEX is steps_mod.STEP_ORDER


def test_skippable_is_consistent_across_services() -> None:
    catalog = steps_mod.SNOWFLAKE_STEP_CATALOG
    cat_skip = {s["step_key"]: bool(s.get("skippable")) for s in catalog}
    plan_skip = {s["step_key"]: bool(s.get("skippable")) for s in SNOWFLAKE_STEPS}
    # planner 与目录对每一步的可跳过性完全一致(不再分叉)。
    assert plan_skip == cat_skip
    # 硬门集合本身钉成字面量真值,而非从 MATERIALIZATION_REQUIRED_STEPS 反推
    #(反推时漏标硬门 / 多标 warning 步骤会与派生公式同步漂移,断言永不变红)。
    assert set(steps_mod.MATERIALIZATION_REQUIRED_STEPS) == EXPECTED_REQUIRED_STEPS
    # 且「可跳过」==「非物化必需」—— 用独立真值判定,任何 skippable 误算都会变红。
    for s in catalog:
        assert bool(s.get("skippable")) == (s["step_key"] not in EXPECTED_REQUIRED_STEPS)
