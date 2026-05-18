import { expect, test } from "@playwright/test";

import { configureConnection, switchToAdvancedMode } from "./helpers.js";

test("runs chapter runtime ops end to end inside the scene workbench", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.chapter.e2e" });
  await switchToAdvancedMode(page);
  await page.getByTestId("nav-workbench").click();
  await expect(page.getByTestId("scene-workbench-view")).toBeVisible();

  await page.getByTestId("scene-id-input").fill("CH200_SC01");
  await page.getByTestId("scene-load-button").click();

  await expect(page.getByTestId("scene-workbench-view")).toContainText("旧信寄件人线索");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("待补写：1");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("聚合门控：等待补写");

  await expect(page.getByTestId("chapter-backfill-progressive-list")).toBeVisible();

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("pending staged backfill blocks final aggregate");

  const backfillItem = page.getByTestId(/chapter-backfill-item-/).first();
  const stageId = (await backfillItem.getAttribute("data-testid")).replace("chapter-backfill-item-", "");
  await page.getByTestId(`chapter-backfill-strategy-${stageId}`).selectOption("create_tracker_now");
  await page.getByTestId(`chapter-backfill-run-${stageId}`).click();

  await expect(page.getByTestId("chapter-action-receipt")).toContainText("执行补写");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("立即创建跟踪");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("待补写：0");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("聚合门控：无");
  await expect(page.getByTestId("chapter-backfill-empty")).toContainText("当前没有待处理的暂存补写。");

  await page.getByTestId("chapter-manual-hold-reason-input").fill("等待作者确认 backfill 处理策略");
  await page.getByTestId("chapter-manual-hold-set-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("设置人工挂起");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("聚合门控：人工挂起");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("chapter manual hold is active");

  await page.getByTestId("chapter-manual-hold-clear-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("清除人工挂起");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("聚合门控：无");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("运行最终聚合");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("chapter_memory_final_CH200");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("最终记忆行：chapter_memory_final_CH200");
});
