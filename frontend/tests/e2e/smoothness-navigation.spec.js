import { expect, test } from "@playwright/test";

import { configureConnection } from "./helpers.js";

const apiBase = `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;
const indexSectionContentTimeout = 20_000;

async function waitForIndexSectionContent(section, virtualListTestId) {
  await expect
    .poll(async () => {
      if ((await section.getByTestId(virtualListTestId).count()) > 0) {
        return true;
      }
      if ((await section.locator(".virtual-list-row").count()) > 0) {
        return true;
      }

      const emptyState = section.locator(".empty, .base-empty").first();
      if ((await emptyState.count()) === 0) {
        return false;
      }

      const emptyText = (await emptyState.textContent()) || "";
      return !emptyText.includes("加载") && !emptyText.includes("鍔犺浇");
    }, { timeout: indexSectionContentTimeout })
    .toBe(true);
}

function percentile(values, percentileValue) {
  if (!values.length) {
    return 0;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * percentileValue) - 1);
  return sorted[index];
}

async function measureVisibleNavigation(page, navTestId, viewTestId) {
  const start = Date.now();
  await page.getByTestId(navTestId).click();
  await expect(page.getByTestId(viewTestId)).toBeVisible();
  return Date.now() - start;
}

async function collectFrameMetricsDuring(page, action, duration = 700) {
  const metricsPromise = page.evaluate((sampleDuration) =>
    new Promise((resolve) => {
      const gaps = [];
      const longTasks = [];
      let observer = null;
      if ("PerformanceObserver" in window) {
        try {
          observer = new PerformanceObserver((list) => {
            list.getEntries().forEach((entry) => longTasks.push(entry.duration));
          });
          observer.observe({ type: "longtask", buffered: true });
        } catch {
          observer = null;
        }
      }

      const start = performance.now();
      let last = start;
      function frame(now) {
        gaps.push(now - last);
        last = now;
        if (now - start < sampleDuration) {
          requestAnimationFrame(frame);
          return;
        }
        observer?.disconnect();
        resolve({ gaps: gaps.slice(1), longTasks });
      }

      requestAnimationFrame(frame);
    }), duration);

  await action();
  return metricsPromise;
}

async function exerciseVirtualScroll(locator) {
  await locator.evaluate(
    (list) =>
      new Promise((resolve) => {
        const maxScrollTop = Math.max(list.scrollHeight - list.clientHeight, 0);
        let step = 0;
        function scrollStep() {
          step += 1;
          list.scrollTop = Math.round((maxScrollTop * step) / 12);
          list.dispatchEvent(new Event("scroll"));
          if (step < 12) {
            requestAnimationFrame(scrollStep);
            return;
          }
          resolve();
        }
        requestAnimationFrame(scrollStep);
      }),
  );
}

async function openIndexAdvancedEvidence(page) {
  const mode = await page.evaluate(() => window.localStorage.getItem("novel-system:ui-mode"));
  if (mode !== "advanced") {
    await page.getByTestId("ui-mode-advanced").click();
  }
  const reviewIdFilter = page.getByTestId("index-job-filter-review-id");
  if (!(await reviewIdFilter.isVisible().catch(() => false))) {
    await page.getByTestId("index-advanced-evidence-toggle").click();
  }
  await expect(reviewIdFilter).toBeVisible();
}

async function switchToAdvancedMode(page) {
  const mode = await page.evaluate(() => window.localStorage.getItem("novel-system:ui-mode"));
  if (mode !== "advanced") {
    await page.getByTestId("ui-mode-advanced").click();
  }
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem("novel-system:ui-mode"))).toBe("advanced");
}

test("keeps guided navigation compact and advanced mode usable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.addInitScript(({ nextApiBase }) => {
    window.localStorage.setItem("novel-system:ui-mode", "guided");
    window.localStorage.setItem("novel-system-api-base", nextApiBase);
    window.localStorage.setItem("novel-system-operator-ref", "ops.mobile-mode.e2e");
  }, { nextApiBase: apiBase });

  await page.goto("/");
  await expect(page.getByTestId("workflow-nav")).toBeVisible();
  await expect(page.getByTestId("workflow-nav-mobile-select")).toBeVisible();
  await expect(page.getByTestId("workflow-nav-desktop-list")).toBeHidden();
  await expect(page.getByTestId("nav-workbench-route")).toHaveCount(0);

  await page.getByTestId("ui-mode-advanced").click();
  await expect(page.getByTestId("workflow-nav-mobile-select")).toBeVisible();
  await expect(page.getByTestId("nav-workbench-route")).toBeHidden();

  await page.getByTestId("workflow-nav-mobile-select").selectOption("review");
  await expect(page.getByTestId("review-inbox-view")).toBeVisible();

  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    mode: window.localStorage.getItem("novel-system:ui-mode"),
  }));
  expect(metrics.mode).toBe("advanced");
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
});

test("defers unopened views and keeps heavy review payloads collapsed until expanded", async ({ page }) => {
  const requestedPaths = [];

  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/v1/")) {
      requestedPaths.push(url.pathname);
    }
  });

  await page.goto("/");
  await configureConnection(page, { apiBase, operatorRef: "ops.smoothness.e2e" });
  await switchToAdvancedMode(page);

  await expect.poll(() => requestedPaths.filter((path) => path === "/api/v1/knowledge-entries").length).toBe(0);

  await page.getByTestId("nav-knowledge").click();
  await expect(page.getByTestId("knowledge-console-view")).toBeVisible();
  await expect.poll(() => requestedPaths.filter((path) => path === "/api/v1/knowledge-entries").length).toBeGreaterThan(0);
  await expect(page.getByTestId("knowledge-detail-lineage")).toBeVisible();
  if ((await page.getByTestId("knowledge-runtime-refs-json").count()) === 0) {
    await page.getByTestId("knowledge-toggle-runtime-refs").click();
  }
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
  await configureConnection(page, { apiBase, operatorRef: "ops.smoothness.index.e2e" });
  await switchToAdvancedMode(page);

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

  const targetGroupsSection = page.getByTestId("index-target-groups-section");
  await waitForIndexSectionContent(targetGroupsSection, "index-target-groups-virtual-list");

  const firstGroupToggle = targetGroupsSection.getByTestId(/target-activity-toggle-/).first();
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
    await expect(targetGroupsSection.locator(".empty, .base-empty")).toBeVisible();
  }
});

test("keeps scroll-heavy list surfaces interactive after expansion across review-index-author navigation", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { apiBase, operatorRef: "ops.smoothness.scroll" });
  await switchToAdvancedMode(page);

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
  const targetGroupsSection = page.getByTestId("index-target-groups-section");
  const systemRuntimeSection = page.getByTestId("index-system-runtime-section");
  const operatorActionSection = page.getByTestId("index-operator-action-section");

  await page.getByTestId("index-toggle-target-groups").click();
  await page.getByTestId("index-toggle-system-runtime").click();
  await page.getByTestId("index-toggle-operator-action").click();

  await waitForIndexSectionContent(targetGroupsSection, "index-target-groups-virtual-list");
  if (await targetGroupsSection.getByTestId("index-target-groups-virtual-list").count()) {
    await expect(targetGroupsSection.getByTestId("index-target-groups-virtual-list")).toBeVisible();

    const firstGroupToggle = targetGroupsSection.getByTestId(/target-activity-toggle-/).first();
    if (await firstGroupToggle.count()) {
      await expect(firstGroupToggle).toBeVisible();
      await firstGroupToggle.click();
      await expect(targetGroupsSection.locator("[data-testid^='target-activity-item-']").first()).toBeVisible();
    }
  } else {
    await expect(targetGroupsSection.locator(".empty, .base-empty")).toBeVisible();
  }

  await waitForIndexSectionContent(systemRuntimeSection, "index-system-runtime-virtual-list");
  if (await systemRuntimeSection.getByTestId("index-system-runtime-virtual-list").count()) {
    await expect(systemRuntimeSection.getByTestId("index-system-runtime-virtual-list")).toBeVisible();
    const runtimeList = systemRuntimeSection.getByTestId("index-system-runtime-virtual-list");
    await runtimeList.evaluate((list) => {
      list.scrollTop = list.scrollHeight;
    });
    await runtimeList.dispatchEvent("scroll");
    await expect(systemRuntimeSection.locator("[data-activity-key^='system_runtime:']").first()).toBeVisible();
  } else {
    await expect(systemRuntimeSection.locator(".empty, .base-empty")).toBeVisible();
  }

  await waitForIndexSectionContent(operatorActionSection, "index-operator-action-virtual-list");
  if (await operatorActionSection.getByTestId("index-operator-action-virtual-list").count()) {
    await expect(operatorActionSection.getByTestId("index-operator-action-virtual-list")).toBeVisible();
    const operatorList = operatorActionSection.getByTestId("index-operator-action-virtual-list");
    await operatorList.evaluate((list) => {
      list.scrollTop = list.scrollHeight;
    });
    await operatorList.dispatchEvent("scroll");
    await expect(operatorActionSection.locator("[data-activity-key^='operator_action:']").first()).toBeVisible();
  } else {
    await expect(operatorActionSection.locator(".empty, .base-empty")).toBeVisible();
  }

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-workspace-view")).toBeVisible();
  await expect(page.getByTestId("author-chapter-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-scene-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-chapter-form")).toBeVisible();
  await expect(page.getByTestId("author-scene-form")).toBeVisible();
});

test("keeps cached navigation and virtual scrolling inside smoothness budgets", async ({ page }) => {
  await page.goto("/");
  await configureConnection(page, { apiBase, operatorRef: "ops.smoothness.budget" });
  await switchToAdvancedMode(page);

  const warmupRoutes = [
    ["nav-review", "review-inbox-view"],
    ["nav-index", "index-console-view"],
    ["nav-knowledge", "knowledge-console-view"],
    ["nav-author", "author-workspace-view"],
    ["nav-workbench", "scene-workbench-view"],
  ];
  for (const [navTestId, viewTestId] of warmupRoutes) {
    await page.getByTestId(navTestId).click();
    await expect(page.getByTestId(viewTestId)).toBeVisible();
  }

  const routeDurations = [];
  for (const [navTestId, viewTestId] of warmupRoutes) {
    routeDurations.push(await measureVisibleNavigation(page, navTestId, viewTestId));
  }
  expect(percentile(routeDurations, 0.95)).toBeLessThanOrEqual(200);

  await page.getByTestId("nav-review").click();
  await expect(page.getByTestId("review-inbox-virtual-list")).toBeVisible();
  const reviewList = page.getByTestId("review-inbox-virtual-list");
  const reviewMetrics = await collectFrameMetricsDuring(page, () => exerciseVirtualScroll(reviewList));
  expect(percentile(reviewMetrics.gaps, 0.95)).toBeLessThanOrEqual(32);
  expect(Math.max(...reviewMetrics.gaps)).toBeLessThanOrEqual(80);
  expect(reviewMetrics.longTasks.filter((duration) => duration > 100)).toHaveLength(0);
  expect(await reviewList.locator(".virtual-list-row").count()).toBeLessThanOrEqual(40);

  await page.getByTestId("nav-index").click();
  await expect(page.getByTestId("index-console-view")).toBeVisible();
  await page.getByTestId("index-toggle-target-groups").click();
  const targetGroupsSection = page.getByTestId("index-target-groups-section");
  await waitForIndexSectionContent(targetGroupsSection, "index-target-groups-virtual-list");
  if (await targetGroupsSection.getByTestId("index-target-groups-virtual-list").count()) {
    const targetGroupList = targetGroupsSection.getByTestId("index-target-groups-virtual-list");
    const targetMetrics = await collectFrameMetricsDuring(page, () => exerciseVirtualScroll(targetGroupList));
    expect(percentile(targetMetrics.gaps, 0.95)).toBeLessThanOrEqual(32);
    expect(Math.max(...targetMetrics.gaps)).toBeLessThanOrEqual(80);
    expect(targetMetrics.longTasks.filter((duration) => duration > 100)).toHaveLength(0);
    expect(await targetGroupList.locator(".virtual-list-row").count()).toBeLessThanOrEqual(40);
  }

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-scene-virtual-list")).toBeVisible();
  const authorSceneList = page.getByTestId("author-scene-virtual-list");
  const authorMetrics = await collectFrameMetricsDuring(page, () => exerciseVirtualScroll(authorSceneList));
  expect(percentile(authorMetrics.gaps, 0.95)).toBeLessThanOrEqual(32);
  expect(Math.max(...authorMetrics.gaps)).toBeLessThanOrEqual(80);
  expect(authorMetrics.longTasks.filter((duration) => duration > 100)).toHaveLength(0);
  expect(await authorSceneList.locator(".virtual-list-row").count()).toBeLessThanOrEqual(40);
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
  await configureConnection(page, { apiBase, operatorRef: "ops.smoothness.roundtrip" });
  await switchToAdvancedMode(page);
  await page.getByTestId("nav-workbench").click();

  await expect(page.getByTestId("scene-workbench-view")).toBeVisible();
  await page.getByTestId("scene-id-input").fill("CH001_SC01");
  await page.getByTestId("scene-load-button").click();
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
  await openIndexAdvancedEvidence(page);
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
  await openIndexAdvancedEvidence(page);
  await expect(page.getByTestId("index-job-filter-review-id")).toHaveValue("review_style_pending");
});
