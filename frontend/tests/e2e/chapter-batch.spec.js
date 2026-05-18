import { expect, test } from "@playwright/test";

import { configureConnection, switchToAdvancedMode } from "./helpers.js";

const API_BASE = `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;
const OPERATOR_REF = "ops.chapter-batch.e2e";

async function postJson(request, path, body, idempotencyKey) {
  const response = await request.post(`${API_BASE}${path}`, {
    data: body,
    headers: {
      "X-Idempotency-Key": idempotencyKey,
      "X-Operator-Ref": OPERATOR_REF,
    },
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test("launches a chapter batch run, shows where it stopped, and resumes from persisted progress", async ({
  page,
  request,
}) => {
  await postJson(
    request,
    "/api/v1/chapters",
    {
      chapter_id: "CH910",
      planned_scene_count: 3,
      chapter_goal: "Batch chapter run",
      main_plot_push: "Move the chapter run forward",
      emotional_target: "Keep operators oriented",
      ending_effect: "Arrive at a visible stop point",
      must_not: "",
      notes: "",
    },
    "create-ch910",
  );

  await postJson(
    request,
    "/api/v1/scenes",
    {
      scene_id: "CH910_SC01",
      chapter_id: "CH910",
      scene_seq: 1,
      pov_character_id: "CHAR_A",
      onstage_chars_json: ["CHAR_A", "CHAR_B"],
      location: "North archive",
      scene_goal: "Open the batch run with a staged backfill blocker",
      beats_json: ["open", "reveal"],
      must_include_text: '{{backfill id=F910 text="pending archive clue"}}',
      forbidden_text: "",
      exit_change: "the clue points deeper",
      hook: "continue",
      target_length_band: "short",
      scene_type: "bridge",
      is_chapter_last: 0,
    },
    "create-ch910-sc01",
  );

  await postJson(
    request,
    "/api/v1/scenes",
    {
      scene_id: "CH910_SC02",
      chapter_id: "CH910",
      scene_seq: 2,
      pov_character_id: "CHAR_A",
      onstage_chars_json: ["CHAR_A", "CHAR_B"],
      location: "North archive",
      scene_goal: "Continue once the blocker is cleared",
      beats_json: ["discover", "hold"],
      must_include_text: "the archive clue resolves cleanly",
      forbidden_text: "",
      exit_change: "the clue cannot resolve yet",
      hook: "continue",
      target_length_band: "short",
      scene_type: "bridge",
      is_chapter_last: 0,
    },
    "create-ch910-sc02",
  );

  await postJson(
    request,
    "/api/v1/scenes",
    {
      scene_id: "CH910_SC03",
      chapter_id: "CH910",
      scene_seq: 3,
      pov_character_id: "CHAR_A",
      onstage_chars_json: ["CHAR_A", "CHAR_B"],
      location: "North archive",
      scene_goal: "Finish after resume",
      beats_json: ["finish", "land"],
      must_include_text: "the chapter closes cleanly",
      forbidden_text: "",
      exit_change: "the chapter can close",
      hook: "done",
      target_length_band: "short",
      scene_type: "bridge",
      is_chapter_last: 1,
    },
    "create-ch910-sc03",
  );

  await page.goto("/");
  await configureConnection(page, { apiBase: API_BASE, operatorRef: OPERATOR_REF });
  await switchToAdvancedMode(page);
  await page.getByTestId("nav-author").click();
  await page.getByTestId("author-chapter-select-CH910").click();

  await page.getByTestId("author-run-chapter-button").click();
  await expect(page.getByTestId("chapter-run-status-panel")).toContainText("blocked");
  await expect(page.getByTestId("chapter-run-status-panel")).toContainText("CH910_SC01");
  await expect(page.getByTestId("author-scene-batch-state-CH910_SC01")).toContainText("blocked");
  await expect(page.getByTestId("author-scene-batch-state-CH910_SC02")).toContainText("pending");
  await expect(page.getByTestId("author-scene-batch-state-CH910_SC03")).toContainText("pending");

  const chapterStateResponse = await request.get(`${API_BASE}/api/v1/chapters/CH910/status`);
  expect(chapterStateResponse.ok()).toBeTruthy();
  const chapterStatePayload = await chapterStateResponse.json();
  const stageId = chapterStatePayload.data.staged_backfill_items[0].stage_id;

  const backfillResponse = await request.post(`${API_BASE}/api/v1/chapters/CH910/runtime/backfill/${stageId}`, {
    data: { strategy: "create_tracker_now" },
    headers: {
      "X-Idempotency-Key": "resolve-ch910-stage",
      "X-Operator-Ref": OPERATOR_REF,
    },
  });
  expect(backfillResponse.ok()).toBeTruthy();

  await page.getByTestId("author-run-chapter-button").click();
  await expect(page.getByTestId("chapter-run-status-panel")).toContainText("completed");
  await expect(page.getByTestId("author-scene-batch-state-CH910_SC03")).toContainText("completed");
});
