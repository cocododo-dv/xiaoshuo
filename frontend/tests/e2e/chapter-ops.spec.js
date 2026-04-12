import { expect, test } from "@playwright/test";

test("runs chapter runtime ops end to end inside the scene workbench", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.chapter.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("scene-id-input").fill("CH200_SC01");
  await page.getByTestId("scene-load-button").click();

  await expect(page.getByTestId("scene-workbench-view")).toContainText("旧信寄件人线索");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Backfill pending: 1");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Aggregate gate: blocked_waiting_backfill");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("pending staged backfill blocks final aggregate");

  const backfillItem = page.getByTestId(/chapter-backfill-item-/).first();
  const stageId = (await backfillItem.getAttribute("data-testid")).replace("chapter-backfill-item-", "");
  await page.getByTestId(`chapter-backfill-strategy-${stageId}`).selectOption("create_tracker_now");
  await page.getByTestId(`chapter-backfill-run-${stageId}`).click();

  await expect(page.getByTestId("chapter-action-receipt")).toContainText("run_backfill");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("create_tracker_now");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Backfill pending: 0");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Aggregate gate: none");
  await expect(page.getByTestId("chapter-backfill-empty")).toContainText("No pending staged backfill.");

  await page.getByTestId("chapter-manual-hold-reason-input").fill("等待作者确认 backfill 处理策略");
  await page.getByTestId("chapter-manual-hold-set-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("set_manual_hold");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Aggregate gate: manual_hold");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("chapter manual hold is active");

  await page.getByTestId("chapter-manual-hold-clear-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("clear_manual_hold");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Aggregate gate: none");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("run_final_aggregate");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("chapter_memory_final_CH200");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("Final memory row: chapter_memory_final_CH200");
});
