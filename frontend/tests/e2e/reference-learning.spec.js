/**
 * PR-11 — style_reference E2E 链路（维护轮 2026-06-12 重构为双轨）:
 *
 * 抽取/合成自 PR-3 起强制要求 LLM（STYLE_REFERENCE_LLM_REQUIRED 诚实降级，
 * 与 React 端 smoke-f5 同语义），无 LLM 环境跑「导入 + 降级引导」轨；
 * 完整链路轨仅在 NOVEL_SYSTEM_LLM_ENABLED=true 的环境运行
 * （counts 按 PR-23 的全 4 层 / 16 sub_dim 契约更新）。
 */
import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { configureConnection } from "./helpers.js";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const fixturePath = path.resolve(scriptDir, "fixtures", "reference-learning.md");
const LLM_LIVE = (process.env.NOVEL_SYSTEM_LLM_ENABLED || "").toLowerCase() === "true";

async function openImportForm(page) {
  const pathInput = page.getByTestId("reference-import-path");
  if (await pathInput.isVisible().catch(() => false)) {
    return;
  }
  await page.getByTestId("reference-import-toggle").click();
  await expect(pathInput).toBeVisible();
}

async function importFixture(page) {
  await page.getByTestId("nav-reference").click();
  await expect(page.getByTestId("reference-learning-view")).toBeVisible();
  await page.waitForLoadState("networkidle");

  await openImportForm(page);
  await page.getByTestId("reference-import-path").fill(fixturePath);
  await expect(page.getByTestId("reference-import-submit")).toBeEnabled();
  await page.getByTestId("reference-import-submit").click();
  // 标题留空时后端从文件名推导（ingest title fallback）
  await expect(page.getByTestId("reference-book-list")).toContainText("reference-learning");
}

test("导入参考书 → 无 LLM 启动抽取得到明确引导（诚实降级，不出假 findings）", async ({ page }) => {
  test.skip(LLM_LIVE, "LLM 已启用的环境走完整链路用例");
  test.setTimeout(60000);

  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.reference.e2e" });
  await importFixture(page);

  await page.getByTestId("reference-start-run").click();
  await expect(page.locator(".view-error")).toContainText("LLM");
  await expect(page.locator('article[data-testid^="reference-finding-"]')).toHaveCount(0);
});

test("style_reference 完整链路 — 导入 → run → 审阅 → synthesize → apply MIXED → ReviewInbox → metrics", async ({ page }) => {
  test.skip(!LLM_LIVE, "完整抽取链路需要 NOVEL_SYSTEM_LLM_ENABLED=true 的环境");
  test.setTimeout(120000);

  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.reference.e2e" });
  await importFixture(page);

  // 3) 启动 run + 等 findings 出现（PR-23 后默认全 4 层 → 16 sub_dim）
  await page.getByTestId("reference-start-run").click();
  await expect(page.locator('article[data-testid^="reference-finding-"]'))
    .toHaveCount(16, { timeout: 60000 });

  // 4) 审阅:approve 前 8 个,reject 后 8 个
  const approveButtons = page.locator('[data-testid^="reference-approve-"]');
  const rejectButtons = page.locator('[data-testid^="reference-reject-"]');
  await expect(approveButtons).toHaveCount(16);
  for (let i = 0; i < 8; i++) await approveButtons.nth(0).click();
  for (let i = 0; i < 8; i++) await rejectButtons.nth(0).click();

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
