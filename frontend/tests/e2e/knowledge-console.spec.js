import { expect, test } from "@playwright/test";

test("creates knowledge candidates and carries them through review, index, and provenance", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.knowledge.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("nav-knowledge").click();
  await expect(page.getByTestId("knowledge-console-view")).toBeVisible();

  await page.getByTestId("knowledge-review-id").fill("review_knowledge_style_rule");
  await page.getByTestId("knowledge-item-type").selectOption("style_rule_set");
  await page.getByTestId("knowledge-lineage-key").fill("STYLE_KNOWLEDGE_E2E");
  await page.getByTestId("knowledge-candidate-text").fill("keep the reunion tight and gesture-led");
  await page.getByTestId("knowledge-create-button").click();
  await page.getByTestId("knowledge-view-detail-style_rule-STYLE_KNOWLEDGE_E2E").click();
  await expect(page.getByTestId("knowledge-detail-lineage")).toContainText("STYLE_KNOWLEDGE_E2E");
  await page.getByTestId("knowledge-approve-review-review_knowledge_style_rule").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已批准 review_knowledge_style_rule，操作员 ops.knowledge.e2e");

  await page.getByTestId("knowledge-filter-select").selectOption("style_rule");
  await page.getByTestId("knowledge-scope-filter").fill("global");
  await page.getByTestId("knowledge-scope-ref-filter").fill("global");
  await page.getByTestId("knowledge-status-filter").selectOption("active");
  await page.getByTestId("knowledge-refresh-button").click();
  await expect(page.getByTestId("knowledge-card-style_rule-STYLE_KNOWLEDGE_E2E")).toContainText(
    "keep the reunion tight and gesture-led",
  );
  await page.getByTestId("knowledge-view-detail-style_rule-STYLE_KNOWLEDGE_E2E").click();
  await expect(page.getByTestId("knowledge-detail-lineage")).toContainText("STYLE_KNOWLEDGE_E2E");
  await expect(page.getByTestId("knowledge-open-review-ref-review_knowledge_style_rule")).toBeVisible();

  await page.getByTestId("knowledge-scope-ref-filter").fill("missing_scope");
  await page.getByTestId("knowledge-refresh-button").click();
  await expect(page.getByTestId("knowledge-detail-empty")).toBeVisible();

  await page.getByTestId("knowledge-scope-ref-filter").fill("global");
  await page.getByTestId("knowledge-refresh-button").click();
  await page.getByTestId("knowledge-view-detail-style_rule-STYLE_KNOWLEDGE_E2E").click();
  await page.getByTestId("knowledge-open-review-ref-review_knowledge_style_rule").click();
  await expect(page.getByTestId("review-card-review_knowledge_style_rule")).toHaveClass(/focused-card/);
  await page.getByTestId("nav-knowledge").click();
  await page.getByTestId("knowledge-filter-select").selectOption("");
  await page.getByTestId("knowledge-scope-filter").fill("");
  await page.getByTestId("knowledge-scope-ref-filter").fill("");
  await page.getByTestId("knowledge-status-filter").selectOption("");
  await page.getByTestId("knowledge-refresh-button").click();

  await page.getByTestId("knowledge-review-id").fill("review_knowledge_calibration");
  await page.getByTestId("knowledge-item-type").selectOption("calibration_candidate");
  await page.getByTestId("knowledge-lineage-key").fill("CAL_KNOWLEDGE_E2E");
  await page.getByTestId("knowledge-candidate-text").fill("the gate sighed shut on the unfinished question");
  await page.getByTestId("knowledge-active-on-approve").selectOption("0");
  await page.getByTestId("knowledge-create-button").click();
  await page.getByTestId("knowledge-view-detail-calibration_line-CAL_KNOWLEDGE_E2E").click();
  await page.getByTestId("knowledge-approve-review-review_knowledge_calibration").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已批准 review_knowledge_calibration，操作员 ops.knowledge.e2e");
  await page.getByTestId("knowledge-retry-verify-verify_review_knowledge_calibration").click();
  await expect(page.getByTestId("notice-stack")).toContainText(
    "已重试校验 verify_review_knowledge_calibration，操作员 ops.knowledge.e2e",
  );
  await page.getByTestId("knowledge-release-review-review_knowledge_calibration").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已发布 review_knowledge_calibration，操作员 ops.knowledge.e2e");

  await page.getByTestId("nav-workbench").click();
  await page.getByTestId("scene-id-input").fill("CH001_SC02");
  await page.getByTestId("scene-load-button").click();
  await page.getByTestId("run-full-scene-button").click();
  const workbench = page.getByTestId("scene-workbench-view");
  await expect(workbench).toContainText("构包溯源");
  await expect(workbench).toContainText("风格规则集");
  await expect(workbench).toContainText("校准句");
  await expect(workbench).toContainText("keep the reunion tight and gesture-led");
  await expect(workbench).toContainText("the gate sighed shut on the unfinished question");

  await page.getByTestId("nav-knowledge").click();
  await page.getByTestId("knowledge-filter-select").selectOption("style_rule");
  await page.getByTestId("knowledge-scope-filter").fill("global");
  await page.getByTestId("knowledge-scope-ref-filter").fill("global");
  await page.getByTestId("knowledge-status-filter").selectOption("active");
  await page.getByTestId("knowledge-refresh-button").click();
  await page.getByTestId("knowledge-view-detail-style_rule-STYLE_KNOWLEDGE_E2E").click();
  await page.getByTestId("knowledge-open-bundle-ref-bundle_CH001_SC02").click();
  await expect(page.getByTestId("scene-id-input")).toHaveValue("CH001_SC02");
  await expect(page.getByTestId("scene-workbench-scene-card")).toHaveClass(/focused-card/);
});
