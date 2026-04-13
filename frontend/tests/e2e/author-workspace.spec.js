import { expect, test } from "@playwright/test";

test("creates and edits author source-of-truth before handing a scene off to the workbench", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.author.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-workspace-view")).toContainText("作者工作台");

  await page.getByTestId("author-new-chapter-button").click();
  await page.getByTestId("author-chapter-id").fill("CH300");
  await page.getByTestId("author-chapter-scene-count").fill("2");
  await page.getByTestId("author-chapter-goal").fill("Initial chapter goal for the author workspace test");
  await page.getByTestId("author-save-chapter-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH300");

  await page.getByTestId("author-chapter-goal").fill("Updated chapter goal for the author workspace test");
  await page.getByTestId("author-save-chapter-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH300");

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH300_SC01");
  await page.getByTestId("author-scene-goal").fill("Opening scene before the reorder");
  await page.getByLabel("地点").last().fill("North archive");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC01");

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH300_SC02");
  await page.getByTestId("author-scene-goal").fill("Second scene before author edits");
  await page.getByLabel("地点").last().fill("Clock bridge");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC02");

  await page.getByTestId("author-scene-goal").fill("Updated second scene after author edits");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC02");

  await page.getByTestId("author-scene-mark-last-CH300_SC02").click();
  await expect(page.getByTestId("author-scene-mark-last-CH300_SC02")).toBeDisabled();

  await page.getByTestId("author-scene-move-up-CH300_SC02").click();
  await expect(page.locator('[data-testid^="author-scene-row-"]').first()).toContainText("CH300_SC02");

  await page.getByTestId("author-open-workbench-CH300_SC02").click();
  await expect(page.getByTestId("scene-id-input")).toHaveValue("CH300_SC02");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Updated chapter goal for the author workspace test");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Updated second scene after author edits");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("地点：Clock bridge");
});
