/**
 * PR-11 — style_reference 完整 E2E 链路:
 *   导入 corpus → run → findings 审阅 → synthesize →
 *   apply Profile(MIXED + intensity + sub_dim)→ ReviewInbox 审批 →
 *   KnowledgeConsole 验 metrics panel
 *
 * 沿用真后端 + 真 LLM offline placeholder(NOVEL_SYSTEM_LLM_ENABLED=false);
 * 测试中所有 click/fill 走 Playwright 的 expect 重试机制,容忍后端短暂延时。
 */
import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { configureConnection } from "./helpers.js";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const fixturePath = path.resolve(scriptDir, "fixtures", "reference-learning.md");

async function openImportForm(page) {
  const pathInput = page.getByTestId("reference-import-path");
  if (await pathInput.isVisible().catch(() => false)) {
    return;
  }
  await page.getByTestId("reference-import-toggle").click();
  await expect(pathInput).toBeVisible();
}

test("style_reference 完整链路 — 导入 → run → 审阅 → synthesize → apply MIXED → ReviewInbox → metrics", async ({ page }) => {
  test.setTimeout(120000);

  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.reference.e2e" });

  // 1) 进入 ReferenceLearningView,确认根可见
  await page.getByTestId("nav-reference").click();
  await expect(page.getByTestId("reference-learning-view")).toBeVisible();
  await page.waitForLoadState("networkidle");

  // 2) 导入 fixture
  await openImportForm(page);
  await page.getByTestId("reference-import-path").fill(fixturePath);
  await expect(page.getByTestId("reference-import-submit")).toBeEnabled();
  await page.getByTestId("reference-import-submit").click();
  await expect(page.getByTestId("reference-book-list")).toContainText("reference-learning");

  // 3) 启动 run + 等 findings 出现
  await page.getByTestId("reference-start-run").click();
  await expect(page.locator('article[data-testid^="reference-finding-"]'))
    .toHaveCount(8, { timeout: 30000 });

  // 4) 审阅:approve 前 4 个,reject 后 4 个
  const approveButtons = page.locator('[data-testid^="reference-approve-"]');
  const rejectButtons = page.locator('[data-testid^="reference-reject-"]');
  await expect(approveButtons).toHaveCount(8);
  for (let i = 0; i < 4; i++) await approveButtons.nth(0).click();
  for (let i = 0; i < 4; i++) await rejectButtons.nth(0).click();

  // 5) synthesize → 等 profile 出现
  await page.getByTestId("reference-advance-run").click();
  await expect(page.locator('[data-testid^="reference-profile-"], .profile-card'))
    .toHaveCount(1, { timeout: 20000 });

  // 6) 打开 apply dialog,验证 PR-9 4 组件可见
  await page.getByTestId("reference-apply-button").click();
  await expect(page.getByTestId("strategy-A")).toBeVisible();
  await expect(page.getByTestId("strategy-mixed")).toBeVisible();

  // 7) 选 MIXED → IntensitySlider + DimensionMultiSelect 展开
  await page.getByTestId("strategy-mixed").click();
  await expect(page.getByTestId("mixed-controls")).toBeVisible();
  await expect(page.getByTestId("intensity-input")).toBeVisible();

  // 8) intensity=70(fill 之后 dispatchEvent input 让 Vue 收到)
  await page.getByTestId("intensity-input").fill("70");

  // 9) 取消 1 个 sub_dim
  await page.getByTestId("sub-dim-language.sentence_structure").click();

  // 10) Bundle preview 应在 debounce 300ms 后出现(等 fragments / prefix)
  await expect(page.getByTestId("bundle-preview")).toBeVisible({ timeout: 3000 });

  // 11) 点 apply
  await page.getByTestId("confirm-apply").click();

  // 12) 进入 ReviewInbox(等可见 review 卡片)
  await page.getByTestId("nav-review").click();
  const applyCards = page.locator('[data-testid^="review-card-"]');
  await expect(applyCards.first()).toBeVisible({ timeout: 10000 });

  // 13) KnowledgeConsole 验 metrics panel 可见(指标已产生事件)
  await page.getByTestId("nav-knowledge").click();
  await page.getByTestId("knowledge-toggle-style-reference-metrics").click();
  await expect(page.getByTestId("style-reference-metrics-panel")).toBeVisible();
});
