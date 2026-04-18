import { expect, test } from "@playwright/test";

import { configureConnection } from "./helpers.js";

test("runs the runtime-ops seeded flow end to end", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.runtime.e2e" });

  await page.getByTestId("scene-id-input").fill("CH001_SC01");
  await page.getByTestId("scene-load-button").click();
  await expect(page.getByTestId("scene-id-input")).toHaveValue("CH001_SC01");

  await page.getByTestId("run-full-scene-button").click();
  await expect(page.getByTestId("scene-run-receipt")).toContainText("已归档");
  await expect(page.getByTestId("scene-run-receipt")).toContainText("final_scene_CH001_SC01");

  await page.getByTestId("nav-review").click();
  await page.getByTestId("review-filter-status").selectOption("pending");
  await page.getByTestId("review-filter-refresh").click();
  const baseReviewCard = page.getByTestId("review-card-review_demo_style_observation");
  await expect(baseReviewCard).toBeVisible();
  await baseReviewCard.getByTestId("review-approve-review_demo_style_observation").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已批准 review_demo_style_observation，操作员 ops.runtime.e2e");

  await page.getByTestId("nav-index").click();
  await page.getByTestId("index-job-filter-job-type").selectOption("verify");
  await page.getByTestId("index-job-filter-review-id").fill("review_demo_style_observation");
  await page.getByTestId("index-job-filter-refresh").click();
  const baseVerifyJob = page.getByTestId("verify-job-verify_review_demo_style_observation");
  await expect(baseVerifyJob).toBeVisible();
  await baseVerifyJob.getByTestId("retry-verify-job-verify_review_demo_style_observation").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已重试校验 verify_review_demo_style_observation，操作员 ops.runtime.e2e");

  await page.getByTestId("nav-review").click();
  await page.getByTestId("review-filter-status").selectOption("approved");
  await page.getByTestId("review-filter-refresh").click();
  await baseReviewCard.getByTestId("review-release-review_demo_style_observation").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已发布 review_demo_style_observation，操作员 ops.runtime.e2e");

  await page.getByTestId("nav-index").click();
  await page.getByTestId("index-ledger-filter-target-ref").fill("review_item:review_demo_due_promotion");
  await page.getByTestId("index-ledger-filter-source").selectOption("system_runtime");
  await page.getByTestId("index-ledger-filter-refresh").click();
  await page.getByTestId("run-due-promotions-button").click();
  await expect(page.getByTestId("promotion-receipt")).toContainText("review_demo_due_promotion");
  await expect(page.getByTestId("promotion-receipt")).toContainText("ops.runtime.e2e");
  await page.getByTestId("promotion-open-review-review_demo_due_promotion").click();
  await expect(page.getByTestId("target-activity-group-review_item:review_demo_due_promotion")).toContainText("review_demo_due_promotion");

  await page.getByTestId("run-recovery-sweep-button").click();
  await expect(page.getByTestId("recovery-receipt")).toContainText("人工审核事件");
  await expect(page.getByTestId("recovery-receipt")).toContainText("ops.runtime.e2e");
  await page.getByTestId("nav-review").click();
  await page.getByTestId("human-review-filter-event-source").selectOption("idempotency_recovery");
  await page.getByTestId("human-review-filter-refresh").click();
  const reviewInboxView = page.getByTestId("review-inbox-view");
  await expect(reviewInboxView).toContainText("系统恢复");
  const recoveryEvent = reviewInboxView.getByTestId(
    "human-review-event-human_review_idempotency_recovery_approve-review-demo-recovery-followup",
  );
  await recoveryEvent.getByTestId("human-review-action-human_review_idempotency_recovery_approve-review-demo-recovery-followup-retry_request").click();
  await expect(recoveryEvent).toContainText("retry_verify");
  await recoveryEvent.getByTestId("human-review-open-followup-human_review_idempotency_recovery_approve-review-demo-recovery-followup").click();

  await page.getByTestId("nav-index").click();
  await page.getByTestId("index-job-filter-job-type").selectOption("verify");
  await page.getByTestId("index-job-filter-review-id").fill("review_demo_recovery_followup");
  await page.getByTestId("index-job-filter-refresh").click();
  await expect(page.getByTestId("index-console-view")).toContainText("verify_review_demo_recovery_followup");
  await page.getByTestId("nav-review").click();
  await recoveryEvent.getByTestId("human-review-action-human_review_idempotency_recovery_approve-review-demo-recovery-followup-retry_verify").click();
  await expect(recoveryEvent).toContainText("release_review");
  await recoveryEvent.getByTestId("human-review-action-human_review_idempotency_recovery_approve-review-demo-recovery-followup-release_review").click();
  await expect(page.getByTestId("notice-stack")).toContainText("已对 human_review_idempotency_recovery_approve-review-demo-recovery-followup 执行动作 release_review");
  await page.getByTestId("human-review-filter-refresh").click();
  await expect(recoveryEvent).toHaveCount(0);

  await page.getByTestId("nav-index").click();
  await page.getByTestId("index-job-filter-clear").click();
  await page.getByTestId("index-ledger-filter-clear").click();
  await expect(page.getByTestId("recovery-followup-receipt")).toContainText("ops.runtime.e2e");
  const followupTargetActivity = page.getByTestId("target-activity-group-review_item:review_demo_recovery_followup");
  await followupTargetActivity.getByTestId("target-activity-toggle-review_item:review_demo_recovery_followup").click();
  await expect(followupTargetActivity).toContainText("ops.runtime.e2e");
  await page.getByTestId("recovery-followup-open-linked-target").click();
  await expect(page.getByTestId("review-card-review_demo_recovery_followup")).toHaveClass(/focused-card/);
});
