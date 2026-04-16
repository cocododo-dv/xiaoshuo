import { expect, test } from "@playwright/test";

test("runs chapter runtime ops end to end inside the scene workbench", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.chapter.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("scene-id-input").fill("CH200_SC01");
  await page.getByTestId("scene-load-button").click();

  await expect(page.getByTestId("scene-workbench-view")).toContainText("鏃т俊瀵勪欢浜虹嚎绱?");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("寰呰ˉ鍐欙細1");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("鑱氬悎闂ㄦ帶锛氱瓑寰呰ˉ鍐?");
  await expect(page.getByTestId("chapter-backfill-progressive-list")).toBeVisible();

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("pending staged backfill blocks final aggregate");

  const backfillItem = page.getByTestId(/chapter-backfill-item-/).first();
  const stageId = (await backfillItem.getAttribute("data-testid")).replace("chapter-backfill-item-", "");
  await page.getByTestId(`chapter-backfill-strategy-${stageId}`).selectOption("create_tracker_now");
  await page.getByTestId(`chapter-backfill-run-${stageId}`).click();

  await expect(page.getByTestId("chapter-action-receipt")).toContainText("鎵ц琛ュ啓");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("绔嬪嵆鍒涘缓璺熻釜");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("寰呰ˉ鍐欙細0");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("鑱氬悎闂ㄦ帶锛氭棤");
  await expect(page.getByTestId("chapter-backfill-empty")).toContainText("褰撳墠娌℃湁寰呭鐞嗙殑鏆傚瓨琛ュ啓銆?");

  await page.getByTestId("chapter-manual-hold-reason-input").fill("绛夊緟浣滆€呯‘璁?backfill 澶勭悊绛栫暐");
  await page.getByTestId("chapter-manual-hold-set-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("璁剧疆浜哄伐鎸傝捣");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("鑱氬悎闂ㄦ帶锛氫汉宸ユ寕璧?");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("chapter manual hold is active");

  await page.getByTestId("chapter-manual-hold-clear-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("娓呴櫎浜哄伐鎸傝捣");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("鑱氬悎闂ㄦ帶锛氭棤");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("杩愯鏈€缁堣仛鍚?");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("chapter_memory_final_CH200");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("鏈€缁堣蹇嗚锛歝hapter_memory_final_CH200");
});
