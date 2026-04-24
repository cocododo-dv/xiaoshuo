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

test("learns a reference book through review decisions and applies it to a chapter bundle", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.reference.e2e" });

  await page.getByTestId("nav-reference").click();
  await expect(page.getByTestId("reference-learning-view")).toBeVisible();
  await page.waitForLoadState("networkidle");

  await openImportForm(page);
  await page.getByTestId("reference-import-path").fill(fixturePath);
  await expect(page.getByTestId("reference-import-submit")).toBeEnabled();
  await page.getByTestId("reference-import-submit").click();
  await expect(page.getByTestId("reference-book-list")).toContainText("reference-learning");

  await page.getByTestId("reference-start-run").click();
  await page.getByTestId("reference-advance-run").click();
  await expect(page.locator('article[data-testid^="reference-finding-"]')).toHaveCount(8);
  await expect(page.getByTestId("reference-finding-list")).toContainText("叙事结构");

  const approveButtons = page.locator('[data-testid^="reference-approve-"]');
  const rejectButtons = page.locator('[data-testid^="reference-reject-"]');
  await expect(approveButtons).toHaveCount(8);
  await expect(rejectButtons).toHaveCount(8);
  await approveButtons.nth(0).click();
  const firstFindingCard = page.locator('article[data-testid^="reference-finding-"]').first();
  const firstRejectButton = firstFindingCard.locator('[data-testid^="reference-reject-"]').first();
  await expect(firstRejectButton).toBeEnabled();
  await expect(firstRejectButton).toHaveText("改为拒绝");
  await expect(firstRejectButton).toHaveClass(/is-reversal/);
  await firstRejectButton.click();
  await expect(firstFindingCard.getByTestId("flow-action-receipt")).toContainText("已拒绝");
  await firstFindingCard.locator('[data-testid^="reference-approve-"]').first().click();
  await approveButtons.nth(1).click();
  await approveButtons.nth(2).click();
  await approveButtons.nth(3).click();
  await rejectButtons.nth(4).click();
  await rejectButtons.nth(5).click();
  await rejectButtons.nth(6).click();
  await rejectButtons.nth(7).click();

  await page.getByTestId("reference-advance-run").click();
  await expect(page.locator('[data-testid^="reference-profile-refprofile_"]')).toHaveCount(1);

  await page.getByTestId("reference-apply-scope").selectOption("chapter");
  await page.getByTestId("reference-apply-scope-ref").fill("CH001");
  await page.locator('[data-testid^="reference-apply-refprofile_"]').first().click();
  const applyReceipt = page.getByTestId("reference-profile-apply-receipt").first();
  await expect(applyReceipt).toContainText("已创建");
  await expect(applyReceipt).toContainText("去审核收件箱");

  await page.getByTestId("nav-review").click();
  await page.getByTestId("review-filter-status").selectOption("pending");
  await page.getByTestId("review-filter-refresh").click();
  const applyCards = page.locator('[data-testid^="review-card-review_apply_"]');
  await expect(applyCards).toHaveCount(2);
  const reviewIds = await applyCards.evaluateAll((cards) =>
    cards.map((card) => card.getAttribute("data-testid").replace("review-card-", "")),
  );
  expect(reviewIds).toHaveLength(2);
  await page.getByTestId("human-review-filter-event-source").selectOption("manual_scene_review");
  await page.getByTestId("human-review-filter-refresh").click();
  await expect(page.getByTestId("human-review-pager")).toHaveCount(0);
  await expect(page.getByTestId("review-items-pager-summary")).toContainText("审核项：");
  await expect(applyCards.first()).toContainText("参考画像应用");
  await expect(applyCards.first()).not.toContainText(reviewIds[0]);
  await applyCards.first().getByTestId(`review-toggle-payload-${reviewIds[0]}`).click();
  await expect(applyCards.first()).toContainText(reviewIds[0]);

  for (const reviewId of reviewIds) {
    await page.getByTestId(`review-approve-${reviewId}`).click();
  }

  await page.getByTestId("review-filter-status").selectOption("approved");
  await page.getByTestId("review-filter-refresh").click();
  for (const reviewId of reviewIds) {
    await page.getByTestId(`review-release-${reviewId}`).click();
  }

  await page.getByTestId("nav-workbench").click();
  await page.getByTestId("scene-id-input").fill("CH001_SC02");
  await page.getByTestId("scene-load-button").click();
  await page.getByTestId("run-full-scene-button").click();
  await expect(page.getByTestId("scene-run-receipt")).toContainText("bundle_CH001_SC02");
  await page.getByTestId("scene-toggle-bundle-provenance").click();

  const workbench = page.getByTestId("scene-workbench-view");
  await expect(workbench).toContainText("STYLE_FEATURE_CONTRACT_v1");
  await expect(workbench).toContainText("叙事结构");
  await expect(workbench).toContainText("从意象片段提炼章节钩子结构");
});
