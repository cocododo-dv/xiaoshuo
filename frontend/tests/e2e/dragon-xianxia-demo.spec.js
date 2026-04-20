import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { configureConnection } from "./helpers.js";

const API_BASE = `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;
const OPERATOR_REF = "ops.dragon-xianxia.e2e";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const fixturePath = path.resolve(scriptDir, "fixtures", "dragon-xianxia-safe-reference.md");

const FORBIDDEN_SOURCE_MARKERS = [
  "txt8080",
  "\u58f0\u660e\uff1a\u672c\u4e66",
  "\u8def\u660e\u975e",
  "\u695a\u5b50\u822a",
  "\u5361\u585e\u5c14",
  "\u6c5f\u5357",
  "\u9f99\u65cf",
];

const CHAPTERS = [
  {
    chapterId: "XXDEMO_CH01",
    sceneId: "XXDEMO_CH01_SC01",
    goal: "Open an original cultivation fantasy demo with a mortal oath and a hidden sect trial.",
    push: "The protagonist finds a spirit seal that points toward the mountain gate.",
    emotion: "Wonder under pressure.",
    ending: "The seal answers with a dangerous invitation.",
    location: "Misty ferry below Azure Peak",
    sceneGoal: "Show the first brush with cultivation power without copying source characters or settings.",
    beats: ["mortal errand", "spirit seal wakes", "sect messenger tests resolve"],
    mustInclude: "the spirit seal glows like cold jade",
  },
  {
    chapterId: "XXDEMO_CH02",
    sceneId: "XXDEMO_CH02_SC01",
    goal: "Escalate the trial into a sect conflict around a forbidden medicine furnace.",
    push: "The protagonist chooses to protect a weaker initiate during the entrance test.",
    emotion: "Fear turning into disciplined courage.",
    ending: "A senior elder notices the protagonist's unusual meridian pattern.",
    location: "Outer sect furnace hall",
    sceneGoal: "Turn the training challenge into a moral decision with clear consequences.",
    beats: ["furnace sabotage", "initiate in danger", "elder intervenes"],
    mustInclude: "the furnace flame bends away from the innocent initiate",
  },
  {
    chapterId: "XXDEMO_CH03",
    sceneId: "XXDEMO_CH03_SC01",
    goal: "Close the demo with an original oath, a new enemy, and a clean next-chapter hook.",
    push: "The protagonist earns a place in the sect while refusing an unsafe shortcut.",
    emotion: "Relief mixed with a sharper responsibility.",
    ending: "A rival clan marks the protagonist for future pursuit.",
    location: "Moonlit oath platform",
    sceneGoal: "Land a satisfying demo endpoint while leaving a fresh cultivation hook.",
    beats: ["oath platform", "shortcut refused", "rival clan threat"],
    mustInclude: "the oath platform rings once under the moon",
  },
];

async function apiRequest(request, method, apiPath, body = undefined, idempotencyKey = undefined) {
  const response = await request[method](`${API_BASE}${apiPath}`, {
    data: body,
    headers: {
      ...(idempotencyKey ? { "X-Idempotency-Key": idempotencyKey } : {}),
      "X-Operator-Ref": OPERATOR_REF,
    },
  });
  const payload = await response.json().catch(() => ({}));
  expect(response.ok(), `${method.toUpperCase()} ${apiPath}: ${JSON.stringify(payload)}`).toBeTruthy();
  return payload.data;
}

async function postJson(request, apiPath, body, idempotencyKey) {
  return apiRequest(request, "post", apiPath, body, idempotencyKey);
}

async function getJson(request, apiPath) {
  return apiRequest(request, "get", apiPath);
}

async function approveReview(request, reviewId, suffix) {
  const firstResponse = await request.post(`${API_BASE}/api/v1/review-items/${reviewId}/approve`, {
    data: {},
    headers: {
      "X-Idempotency-Key": `approve-${suffix}`,
      "X-Operator-Ref": OPERATOR_REF,
    },
  });
  const firstPayload = await firstResponse.json().catch(() => ({}));
  if (firstResponse.ok()) {
    return firstPayload.data;
  }
  if (firstPayload.error?.code !== "STYLE_PROFILE_RISK_CONFIRMATION_REQUIRED") {
    expect(firstResponse.ok(), `approve ${reviewId}: ${JSON.stringify(firstPayload)}`).toBeTruthy();
  }
  return postJson(
    request,
    `/api/v1/review-items/${reviewId}/approve`,
    {
      risk_confirmation: {
        acknowledged: true,
        reason: "E2E approves safe abstract reference profile materialization.",
      },
    },
    `approve-${suffix}-risk-confirmed`,
  );
}

function expectNoSourceLeakage(value) {
  const serialized = typeof value === "string" ? value : JSON.stringify(value);
  for (const marker of FORBIDDEN_SOURCE_MARKERS) {
    expect(serialized).not.toContain(marker);
  }
}

async function prepareSafeReferenceProfile(request) {
  const imported = await postJson(
    request,
    "/api/v1/reference-books/import-path",
    {
      file_path: fixturePath,
      title: "Safe reference fixture for Dragon-style closed-loop demo",
      author_label: "Synthetic fixture",
      cloud_policy: "local_only",
      analysis_focus: "style_structure",
    },
    "dragon-xianxia-import-safe-reference",
  );
  const bookId = imported.book_id;

  const started = await postJson(
    request,
    `/api/v1/reference-books/${bookId}/runs`,
    { batch_size: 8 },
    "dragon-xianxia-start-run",
  );
  const runId = started.run.run_id;
  const firstRound = await postJson(
    request,
    `/api/v1/reference-books/${bookId}/runs/${runId}/advance`,
    {},
    "dragon-xianxia-advance-round",
  );

  expect(firstRound.round.findings).toHaveLength(8);
  for (const [index, finding] of firstRound.round.findings.entries()) {
    await approveReview(request, finding.review.review_id, `dragon-xianxia-finding-${index}`);
  }

  const completed = await postJson(
    request,
    `/api/v1/reference-books/${bookId}/runs/${runId}/advance`,
    {},
    "dragon-xianxia-complete-profile",
  );
  expect(completed.profile.status).toBe("ready");
  expect(completed.profile.safety_summary.safe).toBe(true);
  expectNoSourceLeakage(completed.profile.profile_json);
  return { bookId, profile: completed.profile };
}

test("turns a safe Dragon reference-learning profile into a three-chapter xianxia demo without source leakage", async ({
  page,
  request,
}) => {
  await prepareSafeReferenceProfile(request);

  await page.goto("/");
  await configureConnection(page, { apiBase: API_BASE, operatorRef: OPERATOR_REF });
  await page.getByTestId("nav-reference").click();
  await expect(page.getByTestId("reference-learning-view")).toBeVisible();
  await expect(page.getByTestId("dragon-demo-workspace")).toBeVisible();
  await expect(page.getByTestId("dragon-demo-run")).toBeEnabled({ timeout: 30000 });
  await page.getByTestId("dragon-demo-run").click();
  await expect(page.getByTestId("dragon-demo-workspace")).toContainText(
    `Offline style draft for ${CHAPTERS[2].sceneId}.`,
    { timeout: 90000 },
  );
  await expect(page.getByTestId("dragon-demo-workspace")).toContainText("泄漏检查 通过");
  await expect(page.getByTestId("dragon-demo-workspace")).not.toContainText("txt8080");

  for (const chapter of CHAPTERS) {
    const workbench = await getJson(request, `/api/v1/scenes/${chapter.sceneId}/workbench`);
    expect(workbench.scene_run_state.current_final_scene_row_id).toBeTruthy();
    expect(workbench.final_scene?.content || "").toContain(`Offline style draft for ${chapter.sceneId}.`);
    expectNoSourceLeakage(workbench.bundle?.snapshot);
    expectNoSourceLeakage(workbench.final_scene?.content || "");
  }

  await page.getByTestId("nav-workbench").click();
  await page.getByTestId("scene-id-input").fill(CHAPTERS[2].sceneId);
  await page.getByTestId("scene-load-button").click();
  await expect(page.getByTestId("scene-workbench-view")).toContainText(`Offline style draft for ${CHAPTERS[2].sceneId}.`);
  await expect(page.getByTestId("scene-workbench-view")).not.toContainText("txt8080");
});
