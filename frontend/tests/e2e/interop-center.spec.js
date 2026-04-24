import { expect, test } from "@playwright/test";

import { configureConnection } from "./helpers.js";

const WORKSHEET_YAML = `
bundle_id: bundle_interop_e2e
scene_id: CH001_SC03
chapter_id: CH001
hash_contract_version: BSHASH_v1
hash_alg: sha256
execution_mode: P1_scripted
created_by_action: bundle_worksheet_import
snapshot:
  contract_version: BSHASH_v1
  stage_allowlist_name: bundle_build_allowlist_v1
  scene_id: CH001_SC03
  chapter_id: CH001
  source_version_refs:
    chapter_goal: CH001
    scene_card: CH001_SC03
    style_rule_set_id: STYLE_INTEROP_E2E
  resolved_ref_ids:
    relation_ids: []
    world_rule_ids: []
    open_foreshadow_ids: []
  ordered_injections:
    - slot: chapter_goal
      ref_id: CH001
      digest_key: chapter_goal
    - slot: scene_card
      ref_id: CH001_SC03
      digest_key: scene_card
    - slot: style_rules
      ref_id: STYLE_INTEROP_E2E
      digest_key: style_rule
  inline_digests:
    chapter_goal: close the reunion chapter with a traceable knowledge bundle
    scene_card: carry the unresolved question into the dockside cliffhanger
    style_rule: keep the reunion tight and gesture-led
`.trim();

test("previews, imports, exports, and replays worksheet bundles from the interop center", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.interop.e2e" });

  await page.getByTestId("nav-interop").click();
  await expect(page.getByTestId("interop-center-view")).toBeVisible();

  await page.getByTestId("interop-worksheet-input").fill(WORKSHEET_YAML);
  await page.getByTestId("interop-preview-button").click();
  await expect(page.getByTestId("interop-preview-summary")).toContainText("bundle_interop_e2e");
  await expect(page.getByTestId("interop-preview-summary")).not.toContainText("BSHASH_v1");
  await page.getByTestId("ui-mode-advanced").click();
  await expect(page.getByTestId("interop-preview-summary")).toContainText("BSHASH_v1");
  await expect(page.getByTestId("interop-comparison-virtual-list")).toBeVisible();
  await expect(page.getByTestId("interop-source-comparison-style_rule-STYLE_INTEROP_E2E")).toBeVisible();

  await page.getByTestId("interop-import-button").click();
  await expect(page.getByTestId("interop-import-receipt")).toContainText("bundle_interop_e2e");
  await expect(page.getByTestId("interop-import-receipt")).toContainText("bundle_worksheet_import");

  await page.getByTestId("interop-export-bundle-id").fill("bundle_interop_e2e");
  await page.getByTestId("interop-export-button").click();
  await expect(page.getByTestId("interop-envelope-panel")).toContainText("bundle_interop_e2e");
  await expect(page.getByTestId("interop-envelope-panel")).toContainText("P1_scripted");
  await expect(page.getByTestId("interop-comparison-virtual-list")).toBeVisible();
  await expect(page.getByTestId("interop-source-comparison-style_rule-STYLE_INTEROP_E2E")).toContainText(
    "STYLE_INTEROP_E2E",
  );

  await page.getByTestId("nav-workbench").click();
  await page.getByTestId("scene-id-input").fill("CH001_SC03");
  await page.getByTestId("scene-load-button").click();
  await page.getByTestId("run-full-scene-button").click();
  const runReceipt = page.getByTestId("scene-run-receipt");
  await expect(runReceipt).toContainText("final_scene_CH001_SC03");
  const runReceiptText = (await runReceipt.textContent()) || "";
  const finalSceneRowId = runReceiptText.match(/final_scene_CH001_SC03_v\d+/)?.[0];
  const bundleId = runReceiptText.match(/bundle_CH001_SC03_v\d+/)?.[0];
  expect(finalSceneRowId).toBeTruthy();
  expect(bundleId).toBeTruthy();

  await page.getByTestId("nav-interop").click();
  await page.getByTestId("interop-replay-final-row-id").fill(finalSceneRowId);
  await page.getByTestId("interop-replay-final-button").click();
  await expect(page.getByTestId("interop-envelope-panel")).toContainText(bundleId);
  await expect(page.getByTestId("interop-replay-receipt")).toContainText("scene_replay_export");
});
