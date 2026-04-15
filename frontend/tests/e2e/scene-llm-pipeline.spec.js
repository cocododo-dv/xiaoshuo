import { expect, test } from "@playwright/test";

test("runs a deterministic scene llm pipeline from generation evidence through archive", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.scene-llm.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("scene-id-input").fill("CH001_SC01");
  await page.getByTestId("scene-load-button").click();
  await expect(page.getByTestId("scene-id-input")).toHaveValue("CH001_SC01");

  await page.getByTestId("run-full-scene-button").click();

  const runReceipt = page.getByTestId("scene-run-receipt");
  await expect(runReceipt).toContainText("final_scene_CH001_SC01");
  await expect(runReceipt).toContainText("bundle_CH001_SC01");
  await expect(page.getByTestId("operator-ref-input")).toHaveValue("ops.scene-llm.e2e");

  const generationCard = page.getByTestId("scene-generation-summary-card");
  await expect(generationCard).toContainText("style_draft");
  await expect(generationCard).toContainText("offline_deterministic");
  await expect(generationCard).toContainText("gpt-5");
  await expect(generationCard).toContainText(/Prompt Hash[\s\S]*[a-f0-9]{64}/);
  await expect(generationCard).toContainText("Finish Reason");
  await expect(generationCard).toContainText("offline_fallback");

  const qcCard = page.getByTestId("scene-qc-report-card");
  await expect(qcCard).toContainText("Hard QC");
  await expect(qcCard).toContainText("Soft QC");
  await expect(qcCard).toContainText("hard_pass");
  await expect(qcCard).toContainText("soft_pass");
  await expect(qcCard).toContainText("PASS");

  await expect(page.getByTestId("scene-workbench-view")).toContainText("Offline style draft for CH001_SC01.");

  const attemptsPanel = page.getByTestId("attempt-timeline");
  await expect(attemptsPanel).toContainText("hard_qc");
  await expect(attemptsPanel).toContainText("style_draft");
  await expect(attemptsPanel).toContainText("soft_qc");
  await expect(attemptsPanel).toContainText("finalize");
  await expect(attemptsPanel).toContainText("archive");
});
