import { expect, test } from "@playwright/test";

test("runs chapter runtime ops end to end inside the scene workbench", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.chapter.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("scene-id-input").fill("CH200_SC01");
  await page.getByTestId("scene-load-button").click();

  await expect(page.getByTestId("scene-workbench-view")).toContainText("閺冄備繆鐎靛嫪娆㈡禍铏瑰殠缁?");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("瀵板懓藟閸愭瑱绱?");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("閼辨艾鎮庨梻銊﹀付閿涙氨鐡戝鍛八夐崘?");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("pending staged backfill blocks final aggregate");

  const backfillItem = page.getByTestId(/chapter-backfill-item-/).first();
  const stageId = (await backfillItem.getAttribute("data-testid")).replace("chapter-backfill-item-", "");
  await page.getByTestId(`chapter-backfill-strategy-${stageId}`).selectOption("create_tracker_now");
  await page.getByTestId(`chapter-backfill-run-${stageId}`).click();

  await expect(page.getByTestId("chapter-action-receipt")).toContainText("閹笛嗩攽鐞涖儱鍟?");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("缁斿宓嗛崚娑樼紦鐠虹喕閲?");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("瀵板懓藟閸愭瑱绱?");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("閼辨艾鎮庨梻銊﹀付閿涙碍妫?");
  await expect(page.getByTestId("chapter-backfill-progressive-list")).toBeVisible();
  await expect(page.getByTestId("chapter-backfill-empty")).toContainText("瑜版挸澧犲▽鈩冩箒瀵板懎顦╅悶鍡欐畱閺嗗倸鐡ㄧ悰銉ュ晸閵?");

  await page.getByTestId("chapter-manual-hold-reason-input").fill("缁涘绶熸担婊嗏偓鍛€樼拋?backfill 婢跺嫮鎮婄粵鏍殣");
  await page.getByTestId("chapter-manual-hold-set-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("鐠佸墽鐤嗘禍鍝勪紣閹稿倽鎹?");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("閼辨艾鎮庨梻銊﹀付閿涙矮姹夊銉﹀瘯鐠?");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("notice-stack")).toContainText("chapter manual hold is active");

  await page.getByTestId("chapter-manual-hold-clear-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("濞撳懘娅庢禍鍝勪紣閹稿倽鎹?");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("閼辨艾鎮庨梻銊﹀付閿涙碍妫?");

  await page.getByTestId("chapter-final-aggregate-button").click();
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("鏉╂劘顢戦張鈧紒鍫ｄ粵閸?");
  await expect(page.getByTestId("chapter-action-receipt")).toContainText("chapter_memory_final_CH200");
  await expect(page.getByTestId("scene-workbench-view")).toContainText("閺堚偓缂佸牐顔囪箛鍡氼攽閿涙瓭hapter_memory_final_CH200");
});
