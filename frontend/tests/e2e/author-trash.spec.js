import { expect, test } from "@playwright/test";

import { configureConnection, switchToAdvancedMode } from "./helpers.js";

test("moves author records through trash, blocks ambiguous chapter delete, restores scenes, and purges clean chapters", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.author.trash.e2e" });
  await switchToAdvancedMode(page);

  await page.getByTestId("nav-author").click();
  const authorWorkspaceView = page.getByTestId("author-workspace-view");
  await expect(authorWorkspaceView).toBeVisible();
  await expect(authorWorkspaceView).toContainText("作者工作台");

  await page.getByTestId("author-new-chapter-button").click();
  await page.getByTestId("author-chapter-id").fill("CH310");
  await page.getByTestId("author-chapter-scene-count").fill("2");
  await page.getByTestId("author-chapter-goal").fill("作者回收站生命周期章节");
  await page.getByTestId("author-save-chapter-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH310");

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH310_SC01");
  await page.getByTestId("author-scene-goal").fill("第一场景");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH310_SC01");

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH310_SC02");
  await page.getByTestId("author-scene-goal").fill("第二场景");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH310_SC02");

  await page.getByTestId("author-scene-select-CH310_SC02").check();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("author-trash-selected-scenes-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已移入作者回收站");
  await expect(page.getByTestId("author-chapter-trash-block-CH310")).toContainText("章节下已有单独移入回收站的场景");
  await expect(page.getByTestId("author-chapter-select-for-trash-CH310")).toBeDisabled();

  await page.getByTestId("nav-trash").click();
  const authorTrashView = page.getByTestId("author-trash-view");
  await expect(authorTrashView).toBeVisible();
  await expect(authorTrashView).toContainText("作者回收站");
  await expect(page.getByTestId("author-trash-scene-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-trash-scene-row-CH310_SC02")).toContainText("CH310_SC02");
  await expect(page.getByTestId("author-trash-scene-row-CH310_SC02")).not.toContainText("请先恢复所属章节，再恢复该场景");
  await expect(page.getByTestId("author-trash-scene-row-CH310_SC02")).not.toContainText("该场景随章节一起回收，请在章节行中处理");

  await page.getByTestId("author-trash-scene-select-CH310_SC02").check();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("author-trash-restore-scenes-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已恢复");

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-scene-row-CH310_SC02")).toBeVisible();

  await page.getByTestId("author-chapter-select-for-trash-CH310").check();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("author-trash-selected-chapters-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已移入作者回收站");

  await page.getByTestId("nav-trash").click();
  await expect(page.getByTestId("author-trash-chapter-row-CH310")).toContainText("CH310");
  await expect(page.getByTestId("author-trash-chapter-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-trash-scene-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-trash-scene-row-CH310_SC02")).toContainText("请先恢复所属章节，再恢复该场景");
  await expect(page.getByTestId("author-trash-scene-row-CH310_SC02")).toContainText("该场景随章节一起回收，请在章节行中处理");
  await page.getByTestId("author-trash-chapter-select-CH310").check();
  await page.getByTestId("author-trash-purge-chapters-button").click();
  await page.getByTestId("author-trash-purge-chapters-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已彻底清理");

  const authorTrashEmpty = page.getByTestId("author-trash-empty");
  await expect(authorTrashEmpty).toBeVisible();
  await expect(authorTrashEmpty).toContainText("作者回收站为空。");
});
