import { expect, test } from "@playwright/test";

import { configureConnection } from "./helpers.js";

test("creates and edits author source-of-truth before handing a scene off to the workbench", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.author.e2e" });

  await page.getByTestId("nav-author").click();
  const authorWorkspaceView = page.getByTestId("author-workspace-view");
  await expect(authorWorkspaceView).toBeVisible();
  await expect(authorWorkspaceView).toContainText("作者工作台");

  await page.getByTestId("author-new-chapter-button").click();
  await page.getByTestId("author-chapter-id").fill("CH300");
  await page.getByTestId("author-chapter-scene-count").fill("2");
  await page.getByTestId("author-chapter-goal").fill("作者工作台初始章节目标");
  await page.getByLabel("主线推进").fill("Updated push");
  await page.getByLabel("情绪目标").fill("Updated emotion");
  await page.getByLabel("结尾效果").fill("Updated ending");
  await page.getByLabel("禁止包含").fill("Updated must not");
  await page.getByTestId("author-save-chapter-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH300");

  await page.getByTestId("author-chapter-goal").fill("作者工作台更新后的章节目标");
  await page.getByTestId("author-save-chapter-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存章节 CH300");

  await page.getByTestId("author-quick-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已生成智能草稿 CH300_SC01");
  await expect(page.getByTestId("author-scene-id")).toHaveValue("CH300_SC01");
  await expect(page.getByTestId("author-scene-goal")).toHaveValue("推进本章目标：Updated push");
  await expect(page.getByLabel("禁用文本").last()).toHaveValue("Updated must not");
  await expect(page.getByLabel("钩子").last()).toHaveValue("朝向本章结尾效果：Updated ending");
  await page.getByTestId("author-scene-goal").fill("重排前的开场场景");
  await page.getByLabel("视角角色").last().fill("CHAR_B");
  await page.getByLabel("地点").last().fill("北档案室");
  await page.getByLabel("离场变化").last().fill("旧钟楼重逢后的紧张升级");
  await page.getByLabel("目标篇幅档位").last().fill("long");
  await page.getByLabel("场景类型").last().fill("bridge");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC01");

  await page.getByTestId("author-quick-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已生成智能草稿 CH300_SC02");
  await expect(page.getByTestId("author-scene-id")).toHaveValue("CH300_SC02");
  await expect(page.getByLabel("视角角色").last()).toHaveValue("CHAR_B");
  await expect(page.getByLabel("地点").last()).toHaveValue("北档案室");
  await expect(page.getByLabel("目标篇幅档位").last()).toHaveValue("long");
  await expect(page.getByLabel("场景类型").last()).toHaveValue("bridge");
  await expect(page.getByTestId("author-scene-goal")).toHaveValue(
    "承接上一场景变化：旧钟楼重逢后的紧张升级；推进本章目标：Updated push",
  );
  await expect(page.getByLabel("禁用文本").last()).toHaveValue("Updated must not");
  await expect(page.getByLabel("钩子").last()).toHaveValue("朝向本章结尾效果：Updated ending");
  await page.getByTestId("author-scene-goal").fill("作者编辑前的第二场景");
  await page.getByLabel("地点").last().fill("钟楼桥");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC02");

  await page.getByTestId("author-scene-goal").fill("作者编辑后的第二场景");
  await page.getByTestId("author-save-scene-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已保存场景 CH300_SC02");

  await page.getByTestId("author-new-scene-button").click();
  await expect(page.getByTestId("author-scene-id")).toHaveValue("");
  await expect(page.getByTestId("author-scene-goal")).toHaveValue("");
  await expect(page.getByLabel("地点").last()).toHaveValue("");
  await expect(page.getByLabel("钩子").last()).toHaveValue("");

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
