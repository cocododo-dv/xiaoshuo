import { expect, test } from "@playwright/test";

const apiBase = `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;

const VIEWPORTS = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
];

const longChapterId = "CDBQA_20260508133323_01_extremely_long_chapter_identifier_for_readability_checks";
const longSceneId = `${longChapterId}_SC01`;

async function fulfill(route, data) {
  await route.fulfill({ json: { ok: true, data } });
}

function listPagination(returned) {
  return {
    mode: "cursor",
    limit: 25,
    returned,
    total: returned,
    has_next: false,
    next_cursor: null,
  };
}

function chapterListItem() {
  return {
    chapter_id: longChapterId,
    chapter_title: "第一章：零点玻璃雨落在未来失踪名单上",
    chapter_goal:
      "第一章：零点玻璃雨落在未来失踪名单上，城市档案修复师沈闻发现记录并非预言，而是有人提前写入的失踪顺序。",
    planned_scene_count: 3,
    scene_count: 3,
    generated_scene_count: 1,
    completion_status: "partial",
    comparison_status: "aggregate_missing",
    chapter_backfill_pending_count: 1,
    trash_allowed: 1,
  };
}

function chapterDetail() {
  return {
    chapter: chapterListItem(),
    chapter_state: {
      chapter_id: longChapterId,
      current_phase: "drafting",
      chapter_passed_scene_count: 1,
      chapter_backfill_pending_count: 1,
    },
    completion_status: "partial",
    comparison_status: "aggregate_missing",
    assembled: {
      row_id: `chapter_assembled_${longChapterId}`,
      content: "实时拼接正文。",
      char_count: 7,
      scene_count: 3,
      generated_scene_count: 1,
      missing_scene_ids: [`${longChapterId}_SC02`],
    },
    aggregate: {
      row_id: `chapter_memory_final_${longChapterId}_v1`,
      content: "最终聚合正文。",
      char_count: 7,
    },
    scenes: [
      {
        scene_id: longSceneId,
        chapter_id: longChapterId,
        scene_seq: 1,
        scene_goal: "沈闻在零点玻璃雨里发现未来失踪名单。",
        final_scene: { row_id: `final_scene_${longSceneId}_v1` },
      },
    ],
    source_safety_scan: {
      safe: true,
      blocked_terms: [],
      source_profile_ids: [],
    },
    editorial_workspace: {
      chapter_review: null,
      scene_reviews: [],
      revision_candidates: [],
      open_issue_counts: {},
    },
  };
}

function authorDraftPayload() {
  return {
    draft: {
      draft_id: `author_draft_chapter_${longChapterId}`,
      object_type: "chapter",
      object_id: longChapterId,
      source_text_ref: `chapter_memory:${longChapterId}`,
      content: "作者稿正文。",
      revision_no: 1,
      status: "current",
    },
    draft_mode: "chapter",
    desk_mode: "write_first",
    source_layer: "author_draft",
    open_structure_candidates: [],
    open_patch_candidates: [],
    open_draft_proposals: [],
    author_preference_summary: {},
  };
}

function jobItem() {
  return {
    job_id: "reindex_review_currentdb_20260508133323_calibration_line_chapter_CDBQA_long_identifier_for_layout",
    job_type: "reindex",
    review_id: "review_currentdb_20260508133323_calibration_line_chapter_CDBQA_long_identifier",
    alias_scope: `calibration_line:chapter:${longChapterId}`,
    status: "succeeded",
    target_snapshot_version: `snapshot__calibration_line__chapter__${longChapterId}__20260508133323`,
    target_embedding_version: `embed__calibration_line__chapter__${longChapterId}__20260508133323`,
    worker_id: "reindex-worker-with-a-long-readable-name",
    attempt_no: 1,
    heartbeat_at: "2026-05-08T05:36:17.591210+00:00",
    lease_expires_at: "2026-05-08T06:39:17.591210+00:00",
    started_at: "2026-05-08T05:36:17.591210+00:00",
    finished_at: "2026-05-08T05:36:17.592211+00:00",
    error_text: "",
  };
}

async function stubReadableLayoutApi(page) {
  await page.route("**/api/v2/projects", (route) => fulfill(route, { items: [] }));
  await page.route("**/api/v1/reference-books", (route) => fulfill(route, { items: [] }));
  await page.route("**/api/v1/review-items**", (route) => fulfill(route, { items: [], total: 0, next_cursor: null }));
  await page.route("**/api/v1/human-review-events**", (route) => fulfill(route, { items: [], total: 0, next_cursor: null }));
  await page.route("**/api/v1/chapter-manuscripts**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/chapter-manuscripts") {
      await fulfill(route, { items: [chapterListItem()] });
      return;
    }
    await fulfill(route, chapterDetail());
  });
  await page.route("**/api/v1/author-drafts/**/ensure-blank", (route) => fulfill(route, authorDraftPayload()));
  await page.route("**/api/v1/author-drafts/**/events", (route) => fulfill(route, { events: [] }));
  await page.route("**/api/v1/author-drafts/**/proposals", (route) => fulfill(route, { items: [] }));
  await page.route("**/api/v1/author-desk/**/snapshot", (route) =>
    fulfill(route, {
      target: { object_type: "chapter", object_id: longChapterId, chapter_id: longChapterId },
      author_draft: authorDraftPayload().draft,
      runtime_text: { content: "运行层正文。" },
      aggregate_text: { content: "最终聚合正文。" },
      deep_review_summary: { top_findings: [], judgment_layers: { blocking: [], revision: [], profile_mismatch: [], taste: [] } },
      open_candidates: [],
      longform_pressure: [],
      daily_focus: [],
    }),
  );
  await page.route("**/api/v1/chapters/**/deep-review", (route) => fulfill(route, { latest_evaluation: null, patch_candidates: [], lens_evaluations: [] }));
  await page.route("**/api/v1/author-preference-profile", (route) => fulfill(route, { profile: null }));
  await page.route("**/api/v1/vector-alias-scopes**", (route) => fulfill(route, { items: [], pagination: listPagination(0) }));
  await page.route("**/api/v1/index/jobs**", (route) => fulfill(route, { items: [jobItem()], pagination: listPagination(1) }));
}

async function openApp(page) {
  await page.addInitScript(({ nextApiBase }) => {
    window.localStorage.setItem("novel-system:ui-mode", "advanced");
    window.localStorage.setItem("novel-system-api-base", nextApiBase);
    window.localStorage.setItem("novel-system-operator-ref", "ops.readability-layout.e2e");
  }, { nextApiBase: apiBase });
  await page.goto("/");
}

async function openView(page, viewId, testId) {
  const mobileSelect = page.getByTestId("workflow-nav-mobile-select");
  if (await mobileSelect.isVisible()) {
    await mobileSelect.selectOption(viewId);
  } else {
    await page.getByTestId(`nav-${viewId}`).click();
  }
  await expect(page.getByTestId(testId)).toBeVisible();
}

async function expectNoHorizontalOverflow(locator) {
  const metrics = await locator.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(metrics.scrollWidth - metrics.clientWidth).toBeLessThanOrEqual(1);
}

async function expectTouchTarget(locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  expect(box.height).toBeGreaterThanOrEqual(44);
}

test("dense chapter selectors and index jobs stay readable across key viewports", async ({ page }) => {
  await stubReadableLayoutApi(page);

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport);
    await openApp(page);

    await openView(page, "manuscripts", "chapter-manuscript-view");
    const manuscriptPanel = page.locator(".manuscript-list-panel");
    const manuscriptRowButton = page.getByTestId(`manuscript-select-${longChapterId}`);
    await expect(manuscriptPanel).toBeVisible();
    await expect(manuscriptRowButton).toBeVisible();
    await expectNoHorizontalOverflow(manuscriptPanel);
    await expectTouchTarget(manuscriptRowButton);
    await manuscriptRowButton.click();

    await openView(page, "deepdesk", "writer-deep-desk");
    const deepDeskIndex = page.locator(".deep-desk-index");
    const deepDeskRow = deepDeskIndex.locator(".deep-chapter-row").first();
    await expect(deepDeskRow).toBeVisible();
    await expectNoHorizontalOverflow(deepDeskIndex);
    await expectTouchTarget(deepDeskRow);
    await deepDeskRow.click();

    await openView(page, "index", "index-console-view");
    const jobList = page.getByTestId("index-jobs-virtual-list");
    const jobRow = page.locator('[data-testid^="verify-job-"]').first();
    await expect(jobRow).toBeVisible();
    await expectNoHorizontalOverflow(jobList);
    await expect(jobRow).toHaveClass(/readable-job-row/);
    const targetButton = jobRow.getByRole("button", { name: "查看目标" });
    await expectTouchTarget(targetButton);
    await targetButton.click();
  }
});
