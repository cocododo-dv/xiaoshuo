import { expect, test } from "@playwright/test";

const apiBase = `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;

test("defers unopened views and keeps heavy review payloads collapsed until expanded", async ({ page }) => {
  const requestedPaths = [];

  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/v1/")) {
      requestedPaths.push(url.pathname);
    }
  });

  await page.goto("/");
  await page.getByTestId("api-base-input").fill(apiBase);
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.smoothness.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await expect.poll(() => requestedPaths.filter((path) => path === "/api/v1/knowledge-entries").length).toBe(0);

  await page.getByTestId("nav-knowledge").click();
  await expect(page.getByTestId("knowledge-console-view")).toBeVisible();
  await expect.poll(() => requestedPaths.filter((path) => path === "/api/v1/knowledge-entries").length).toBeGreaterThan(0);
  await expect(page.getByTestId("knowledge-detail-lineage")).toBeVisible();
  await expect(page.getByTestId("knowledge-runtime-refs-json")).toHaveCount(0);
  await page.getByTestId("knowledge-toggle-runtime-refs").click();
  await expect(page.getByTestId("knowledge-runtime-refs-json")).toBeVisible();

  await page.getByTestId("nav-review").click();
  await page.getByTestId("review-filter-status").selectOption("pending");
  await page.getByTestId("review-filter-refresh").click();

  const firstReviewCard = page.locator("[data-testid^='review-card-']").first();
  await expect(firstReviewCard.locator("pre")).toHaveCount(0);
  await firstReviewCard.getByTestId(/review-toggle-payload-/).click();
  await expect(firstReviewCard.locator("pre")).toBeVisible();
});

test("loads index activity sections and target-group items only after explicit expansion", async ({ page }) => {
  const requestedUrls = [];

  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v1/")) {
      requestedUrls.push(url);
    }
  });

  await page.goto("/");
  await page.getByTestId("api-base-input").fill(apiBase);
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.smoothness.index.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("nav-index").click();
  await expect(page.getByTestId("index-console-view")).toBeVisible();

  await expect(page.getByTestId("index-toggle-operator-action")).toBeVisible();
  await expect(page.getByTestId("index-toggle-target-groups")).toBeVisible();
  await expect
    .poll(() => requestedUrls.some((url) => url.includes("/api/v1/activity-events?stream=operator_action")))
    .toBe(false);
  await expect
    .poll(() => requestedUrls.some((url) => url.includes("/api/v1/target-activity-groups?")))
    .toBe(false);

  await page.getByTestId("index-toggle-operator-action").click();
  await expect
    .poll(() => requestedUrls.some((url) => url.includes("/api/v1/activity-events?stream=operator_action")))
    .toBe(true);

  await page.getByTestId("index-toggle-target-groups").click();
  await expect
    .poll(() => requestedUrls.some((url) => url.includes("/api/v1/target-activity-groups?")))
    .toBe(true);

  const firstGroupToggle = page.getByTestId(/target-activity-toggle-/).first();
  if (await firstGroupToggle.count()) {
    await expect(firstGroupToggle).toBeVisible();
    await firstGroupToggle.click();
    await expect
      .poll(() =>
        requestedUrls.some(
          (url) => url.includes("/api/v1/target-activity-groups/") && url.includes("/items"),
        ),
      )
      .toBe(true);
  } else {
    await expect(page.getByText("当前没有目标活动摘要。")).toBeVisible();
  }
});

test("keeps scroll-heavy list surfaces interactive after expansion across review-index-author navigation", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("api-base-input").fill(apiBase);
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.smoothness.scroll");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("nav-review").click();
  await expect(page.getByTestId("review-inbox-view")).toBeVisible();
  await page.getByTestId("review-filter-status").selectOption("pending");
  await page.getByTestId("review-filter-refresh").click();
  await expect(page.getByTestId("review-inbox-virtual-list")).toBeVisible();

  const firstReviewCard = page.locator("[data-testid^='review-card-']").first();
  await expect(firstReviewCard).toBeVisible();
  await firstReviewCard.getByTestId(/review-toggle-payload-/).click();
  await expect(firstReviewCard.locator("pre")).toBeVisible();

  await page.getByTestId("nav-index").click();
  await expect(page.getByTestId("index-console-view")).toBeVisible();
  await page.getByTestId("index-toggle-target-groups").click();
  const targetGroupsSection = page.getByTestId("index-target-groups-section");
  await expect
    .poll(async () => {
      const hasVirtualList = await targetGroupsSection.getByTestId("index-target-groups-virtual-list").count();
      const hasEmptyState = await targetGroupsSection.locator(".empty").count();
      return hasVirtualList + hasEmptyState;
    })
    .toBeGreaterThan(0);

  if (await targetGroupsSection.getByTestId("index-target-groups-virtual-list").count()) {
    await expect(targetGroupsSection.getByTestId("index-target-groups-virtual-list")).toBeVisible();

    const firstGroupToggle = targetGroupsSection.getByTestId(/target-activity-toggle-/).first();
    if (await firstGroupToggle.count()) {
      await firstGroupToggle.click();
      await expect(targetGroupsSection.locator("[data-testid^='target-activity-item-']").first()).toBeVisible();
    }
  } else {
    await expect(targetGroupsSection.locator(".empty")).toBeVisible();
  }

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-workspace-view")).toBeVisible();
  await expect(page.getByTestId("author-chapter-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-scene-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-chapter-form")).toBeVisible();
  await expect(page.getByTestId("author-scene-form")).toBeVisible();
});

test("preserves view state across a workbench-review-index-workbench round trip without hidden-page reloads", async ({ page }) => {
  const requestedUrls = [];

  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v1/")) {
      requestedUrls.push(url);
    }
  });

  const requestCount = (fragment) => requestedUrls.filter((url) => url.includes(fragment)).length;

  await page.goto("/");
  await page.getByTestId("api-base-input").fill(apiBase);
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.smoothness.roundtrip");
  await page.getByTestId("operator-ref-input").press("Tab");

  await expect(page.getByTestId("scene-workbench-view")).toBeVisible();
  await expect(page.getByTestId("scene-id-input")).toHaveValue("CH001_SC01");

  await page.getByTestId("nav-review").click();
  await expect(page.getByTestId("review-inbox-view")).toBeVisible();
  await page.getByTestId("review-filter-status").selectOption("pending");
  await page.getByTestId("review-filter-refresh").click();
  await expect(page.getByTestId("review-filter-status")).toHaveValue("pending");
  const reviewRequestsBeforeHide = requestCount("/api/v1/review-items");

  await page.getByTestId("nav-index").click();
  await expect(page.getByTestId("index-console-view")).toBeVisible();
  await expect(page.getByTestId("review-filter-status")).toHaveCount(0);
  await page.getByTestId("index-job-filter-review-id").fill("review_style_pending");
  await expect(page.getByTestId("index-job-filter-review-id")).toHaveValue("review_style_pending");
  const indexActivityRequestsBeforeHide =
    requestCount("/api/v1/activity-events") + requestCount("/api/v1/target-activity-groups");

  await page.getByTestId("nav-workbench").click();
  await expect(page.getByTestId("scene-workbench-view")).toBeVisible();
  await expect(page.getByTestId("scene-id-input")).toHaveValue("CH001_SC01");
  await page.waitForTimeout(250);

  expect(requestCount("/api/v1/review-items")).toBe(reviewRequestsBeforeHide);
  expect(requestCount("/api/v1/activity-events") + requestCount("/api/v1/target-activity-groups")).toBe(
    indexActivityRequestsBeforeHide,
  );

  await page.getByTestId("nav-review").click();
  await expect(page.getByTestId("review-inbox-view")).toBeVisible();
  await expect(page.getByTestId("review-filter-status")).toHaveValue("pending");

  await page.getByTestId("nav-index").click();
  await expect(page.getByTestId("index-console-view")).toBeVisible();
  await expect(page.getByTestId("index-job-filter-review-id")).toHaveValue("review_style_pending");
});
