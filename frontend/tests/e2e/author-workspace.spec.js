import { expect, test } from "@playwright/test";

test("creates and edits author source-of-truth before handing a scene off to the workbench", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.author.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("nav-author").click();
  const authorWorkspaceView = page.getByTestId("author-workspace-view");
  await expect(authorWorkspaceView).toBeVisible();
  await expect(authorWorkspaceView).toContainText("作者工作台");

  await page.getByTestId("author-new-chapter-button").click();
  await page.getByTestId("author-chapter-id").fill("CH300");
  await page.getByTestId("author-chapter-scene-count").fill("2");
  await page.getByTestId("author-chapter-goal").fill("作者工作台初始章节目标");
  await page.getByTestId("author-save-chapter-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH300");

  await page.getByTestId("author-chapter-goal").fill("作者工作台更新后的章节目标");
  await page.getByTestId("author-save-chapter-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH300");

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH300_SC01");
  await page.getByTestId("author-scene-goal").fill("重排前的开场场景");
  await page.getByLabel("地点").last().fill("北档案室");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC01");

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH300_SC02");
  await page.getByTestId("author-scene-goal").fill("作者编辑前的第二场景");
  await page.getByLabel("地点").last().fill("钟楼桥");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC02");

  await page.getByTestId("author-scene-goal").fill("作者编辑后的第二场景");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC02");

  await page.getByTestId("author-scene-mark-last-CH300_SC02").click();
  await expect(page.getByTestId("author-scene-mark-last-CH300_SC02")).toBeDisabled();

  await page.getByTestId("author-scene-move-up-CH300_SC02").click();
  await expect(page.locator('[data-testid^="author-scene-row-"]').first()).toContainText("CH300_SC02");

  await page.getByTestId("author-open-workbench-CH300_SC02").click();
  await expect(page.getByTestId("scene-id-input")).toHaveValue("CH300_SC02");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("作者工作台更新后的章节目标");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("作者编辑后的第二场景");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("地点：钟楼桥");
});
