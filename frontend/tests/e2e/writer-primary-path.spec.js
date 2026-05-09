import { expect, test } from "@playwright/test";

import { configureConnection } from "./helpers.js";

const VIEW_TARGETS = [
  ["snowflake-workbench", "snowflake-workbench-view"],
  ["reference", "reference-learning-view"],
  ["review", "review-inbox-view"],
  ["writer-room", "writer-room-view"],
];

const VIEWPORTS = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
];

async function fulfill(route, data) {
  await route.fulfill({ json: { ok: true, data } });
}

async function stubWriterPathApi(page) {
  await page.route("**/api/v2/projects", async (route) => {
    await fulfill(route, { items: [] });
  });
  await page.route("**/api/v1/reference-books", async (route) => {
    await fulfill(route, { items: [] });
  });
  await page.route("**/api/v1/review-items**", async (route) => {
    await fulfill(route, { items: [], total: 0, next_cursor: null });
  });
  await page.route("**/api/v1/human-review-events**", async (route) => {
    await fulfill(route, { items: [], total: 0, next_cursor: null });
  });
  await page.route("**/api/v1/chapter-manuscripts", async (route) => {
    await fulfill(route, { items: [] });
  });
}

async function openView(page, viewId, testId) {
  if (viewId === "snowflake-workbench") {
    await expect(page.getByTestId(testId)).toBeVisible();
    return;
  }

  const mobileSelect = page.getByTestId("workflow-nav-mobile-select");
  if (await mobileSelect.isVisible()) {
    await mobileSelect.selectOption(viewId);
  } else {
    await page.getByTestId(`nav-${viewId}`).click();
  }
  await expect(page.getByTestId(testId)).toBeVisible();
}

async function expectNoHorizontalScroll(page) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const stage = document.querySelector(".stage");
    const view = document.querySelector(".view-frame");
    return {
      document: root.scrollWidth - root.clientWidth,
      body: document.body.scrollWidth - root.clientWidth,
      stage: stage ? stage.scrollWidth - stage.clientWidth : 0,
      view: view ? view.scrollWidth - view.clientWidth : 0,
    };
  });

  expect(Math.max(...Object.values(overflow))).toBeLessThanOrEqual(1);
}

test("writer primary path stays navigable and avoids horizontal overflow across key viewports", async ({ page }) => {
  await stubWriterPathApi(page);

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await configureConnection(page, { operatorRef: "ops.writer-primary-path.e2e" });
    await page.reload();

    await expect(page.getByTestId("workflow-writer-brief-snowflake-workbench")).toBeVisible();
    await expect(page.getByTestId("writer-path-progress")).toBeVisible();
    await expect(page.getByTestId("writer-path-active-summary")).toHaveAttribute("role", "status");

    for (const [viewId, testId] of VIEW_TARGETS) {
      await openView(page, viewId, testId);
      await expect(page.getByTestId(`writer-path-item-${viewId}`)).toHaveAttribute("aria-current", "step");
      await expectNoHorizontalScroll(page);
    }

    await page.getByTestId("writer-path-item-reference").click();
    await expect(page.getByTestId("reference-learning-view")).toBeVisible();
    await expect(page.getByTestId("writer-path-item-reference")).toHaveAttribute("aria-current", "step");
    await expectNoHorizontalScroll(page);
  }
});
