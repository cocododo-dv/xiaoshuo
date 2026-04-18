import { expect, test } from "@playwright/test";

import { configureConnection } from "./helpers.js";

test("shows blockers for a preflight-failed scene and warnings for a runnable scene", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.preflight.e2e" });

  await page.getByTestId("scene-id-input").fill("CH210_SC01");
  await page.getByTestId("scene-load-button").click();

  const preflightCard = page.getByTestId("scene-run-preflight-card");
  await expect(page.getByTestId("scene-run-preflight-blocking-progressive-list")).toBeVisible();
  await expect(preflightCard).toContainText("缺少 POV 声线档案");
  await expect(preflightCard).toContainText("expected active voice profile: VOICE_CHAR_MISSING");
  await expect(page.getByTestId("run-full-scene-button")).toBeDisabled();

  await page.getByTestId("scene-id-input").fill("CH211_SC01");
  await page.getByTestId("scene-load-button").click();

  await expect(page.getByTestId("scene-run-preflight-warning-progressive-list")).toBeVisible();
  await expect(preflightCard).toContainText("场景目标为空");
  await expect(preflightCard).toContainText("scene_card.scene_goal is blank");
  await expect(page.getByTestId("run-full-scene-button")).toBeEnabled();
});
