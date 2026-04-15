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
  await expect(firstGroupToggle).toBeVisible();
  await firstGroupToggle.click();
  await expect
    .poll(() =>
      requestedUrls.some(
        (url) => url.includes("/api/v1/target-activity-groups/") && url.includes("/items"),
      ),
    )
    .toBe(true);
});
