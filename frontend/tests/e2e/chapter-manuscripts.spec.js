import { expect, test } from "@playwright/test";

import { configureConnection, switchToAdvancedMode } from "./helpers.js";

const CHAPTER_ID = "CHME2E";

function listItem(state) {
  return {
    chapter_id: CHAPTER_ID,
    planned_scene_count: 3,
    chapter_goal: "章节成稿中心 E2E",
    main_plot_push: "验证成稿管理",
    emotional_target: "让作者知道正文在哪里",
    ending_effect: "聚合状态清晰",
    must_not: "",
    notes: "",
    current_phase: "drafting",
    chapter_passed_scene_count: state.generatedSceneCount,
    chapter_backfill_pending_count: 0,
    active_scene_count: state.scenes.length,
    trashed_scene_count: state.trashedScenes.length,
    trash_allowed: 1,
    trash_block_reason: null,
    scene_count: state.scenes.length,
    generated_scene_count: state.generatedSceneCount,
    missing_scene_ids: state.missingSceneIds,
    completion_status: state.completionStatus,
    comparison_status: state.comparisonStatus,
    aggregate_row_id: state.aggregate?.row_id || null,
  };
}

function detailPayload(state) {
  return {
    chapter: {
      chapter_id: CHAPTER_ID,
      planned_scene_count: 3,
      mid_aggregate_enabled: 0,
      chapter_goal: "章节成稿中心 E2E",
      main_plot_push: "验证成稿管理",
      emotional_target: "让作者知道正文在哪里",
      ending_effect: "聚合状态清晰",
      must_not: "",
      notes: "",
    },
    chapter_state: {
      chapter_id: CHAPTER_ID,
      current_phase: "drafting",
      chapter_passed_scene_count: state.generatedSceneCount,
      chapter_backfill_pending_count: 0,
    },
    completion_status: state.completionStatus,
    comparison_status: state.comparisonStatus,
    assembled: {
      content: state.assembledContent,
      char_count: state.assembledContent.length,
      scene_count: state.scenes.length,
      generated_scene_count: state.generatedSceneCount,
      missing_scene_ids: state.missingSceneIds,
    },
    aggregate: state.aggregate,
    scenes: state.scenes,
  };
}

function recompute(state) {
  const generated = state.scenes.filter((scene) => scene.final_scene);
  state.generatedSceneCount = generated.length;
  state.missingSceneIds = state.scenes.filter((scene) => !scene.final_scene).map((scene) => scene.scene_id);
  state.assembledContent = generated.map((scene) => scene.content).join("\n");
  state.completionStatus = state.generatedSceneCount === 0 ? "empty" : state.generatedSceneCount === state.scenes.length ? "complete" : "partial";
  state.comparisonStatus = state.aggregate
    ? state.aggregate.content === state.assembledContent
      ? "aggregate_matches_current"
      : "aggregate_differs_current"
    : "aggregate_missing";
}

function createState() {
  const state = {
    aggregate: null,
    trashedScenes: [],
    scenes: [
      {
        scene_id: `${CHAPTER_ID}_SC01`,
        chapter_id: CHAPTER_ID,
        scene_seq: 1,
        scene_goal: "第一场生成正文",
        beats_json: ["进入", "发现"],
        must_include_text: "",
        forbidden_text: "",
        exit_change: "",
        hook: "",
        target_length_band: "short",
        scene_type: "bridge",
        is_chapter_last: 0,
        scene_status: "archived",
        current_bundle_id: "bundle_CHME2E_SC01",
        current_final_scene_row_id: "final_scene_CHME2E_SC01_v1",
        final_scene: {
          row_id: "final_scene_CHME2E_SC01_v1",
          char_count: 5,
          created_at: "2026-04-22T01:00:00+00:00",
        },
        content: "第一场正文",
      },
      {
        scene_id: `${CHAPTER_ID}_SC02`,
        chapter_id: CHAPTER_ID,
        scene_seq: 2,
        scene_goal: "第二场生成正文",
        beats_json: ["追问"],
        must_include_text: "",
        forbidden_text: "",
        exit_change: "",
        hook: "",
        target_length_band: "short",
        scene_type: "bridge",
        is_chapter_last: 0,
        scene_status: "archived",
        current_bundle_id: "bundle_CHME2E_SC02",
        current_final_scene_row_id: "final_scene_CHME2E_SC02_v1",
        final_scene: {
          row_id: "final_scene_CHME2E_SC02_v1",
          char_count: 5,
          created_at: "2026-04-22T01:05:00+00:00",
        },
        content: "第二场正文",
      },
      {
        scene_id: `${CHAPTER_ID}_SC03`,
        chapter_id: CHAPTER_ID,
        scene_seq: 3,
        scene_goal: "第三场尚未生成",
        beats_json: [],
        must_include_text: "",
        forbidden_text: "",
        exit_change: "",
        hook: "",
        target_length_band: "short",
        scene_type: "bridge",
        is_chapter_last: 1,
        scene_status: "ready",
        current_bundle_id: null,
        current_final_scene_row_id: null,
        final_scene: null,
        content: "",
      },
    ],
  };
  recompute(state);
  return state;
}

test("opens chapter manuscript center, syncs aggregate, and refreshes after trashing a scene", async ({ page }) => {
  const state = createState();

  await page.route("**/api/v1/chapter-manuscripts", async (route) => {
    await route.fulfill({ json: { ok: true, data: { items: [listItem(state)] } } });
  });
  await page.route(`**/api/v1/chapter-manuscripts/${CHAPTER_ID}`, async (route) => {
    await route.fulfill({ json: { ok: true, data: detailPayload(state) } });
  });
  await page.route(`**/api/v1/chapters/${CHAPTER_ID}/runtime/aggregate/final`, async (route) => {
    state.aggregate = {
      row_id: "chapter_memory_final_CHME2E_v1",
      content: state.assembledContent,
      char_count: state.assembledContent.length,
      created_at: "2026-04-22T01:10:00+00:00",
    };
    recompute(state);
    await route.fulfill({
      json: { ok: true, data: { status: "created", chapter_memory_row_id: state.aggregate.row_id } },
    });
  });
  await page.route("**/api/v1/scenes/trash", async (route) => {
    const payload = route.request().postDataJSON();
    const trashed = new Set(payload.scene_ids || []);
    state.trashedScenes = [...state.trashedScenes, ...state.scenes.filter((scene) => trashed.has(scene.scene_id))];
    state.scenes = state.scenes.filter((scene) => !trashed.has(scene.scene_id));
    recompute(state);
    await route.fulfill({
      json: {
        ok: true,
        data: { processed: [...trashed].map((scene_id) => ({ scene_id })), blocked: [] },
      },
    });
  });
  await page.route("**/api/v1/author-trash", async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        data: {
          chapters: [],
          scenes: state.trashedScenes.map((scene) => ({
            scene_id: scene.scene_id,
            chapter_id: scene.chapter_id,
            scene_seq: scene.scene_seq,
            scene_goal: scene.scene_goal,
            trashed_at: "2026-04-22T01:15:00+00:00",
            trashed_by: "ops.e2e",
            chapter_trashed: 0,
            restore_allowed: 1,
            restore_block_reason: null,
            purge_allowed: 1,
            purge_block_reason: null,
          })),
        },
      },
    });
  });

  page.on("dialog", (dialog) => dialog.accept());

  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.manuscript.e2e" });
  await switchToAdvancedMode(page);
  await page.getByTestId("nav-manuscripts").click();

  await expect(page.getByTestId("chapter-manuscript-view")).toBeVisible();
  await expect(page.getByTestId("assembled-manuscript-pane")).toContainText("第一场正文");
  await expect(page.getByTestId("assembled-manuscript-pane")).toContainText("第二场正文");
  await expect(page.getByTestId("chapter-manuscript-view")).toContainText("CHME2E_SC03");
  await expect(page.getByTestId("chapter-manuscript-view")).toContainText("未聚合");

  await page.getByTestId("run-final-aggregate-button").click();
  await expect(page.getByTestId("chapter-manuscript-view")).toContainText("聚合已同步");
  await expect(page.getByTestId("aggregate-manuscript-pane")).toContainText("第一场正文");

  await page.locator("#manuscript-scene-CHME2E_SC01").check();
  await page.getByTestId("manuscript-trash-scenes-button").click();

  await expect(page.getByTestId("assembled-manuscript-pane")).not.toContainText("第一场正文");
  await expect(page.getByTestId("assembled-manuscript-pane")).toContainText("第二场正文");
  await expect(page.getByTestId("chapter-manuscript-view")).toContainText("聚合不同步");
  await expect(page.getByTestId("chapter-manuscript-view")).toContainText("CHME2E_SC03");
});
