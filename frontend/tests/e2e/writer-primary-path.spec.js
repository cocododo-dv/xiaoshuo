import { expect, test } from "@playwright/test";

import { configureConnection } from "./helpers.js";

const VIEW_TARGETS = [
  ["home", "home-view"],
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
  await page.route("**/api/v2/style-reference/books**", async (route) => {
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
  if (viewId === "home") {
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
  const result = await page.evaluate(() => {
    const root = document.documentElement;
    const stage = document.querySelector(".stage");
    const view = document.querySelector(".view-frame");
    const overflow = {
      document: root.scrollWidth - root.clientWidth,
      body: document.body.scrollWidth - root.clientWidth,
      stage: stage ? stage.scrollWidth - stage.clientWidth : 0,
      view: view ? view.scrollWidth - view.clientWidth : 0,
    };
    const limit = root.clientWidth + 1;
    const offenders = [];
    for (const el of document.querySelectorAll("body *")) {
      const rect = el.getBoundingClientRect();
      if (rect.right > limit || rect.width > limit) {
        offenders.push({
          tag: el.tagName.toLowerCase(),
          cls: el.className && typeof el.className === "string" ? el.className : "",
          testid: el.getAttribute("data-testid") || "",
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        });
      }
    }
    return { overflow, offenders: offenders.slice(0, 8), clientWidth: root.clientWidth };
  });

  expect(
    Math.max(...Object.values(result.overflow)),
    `overflow=${JSON.stringify(result.overflow)} clientWidth=${result.clientWidth} offenders=${JSON.stringify(result.offenders)}`,
  ).toBeLessThanOrEqual(1);
}

test("writer primary path stays navigable and avoids horizontal overflow across key viewports", async ({ page }) => {
  await stubWriterPathApi(page);

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await configureConnection(page, { operatorRef: "ops.writer-primary-path.e2e" });
    await page.reload();

    await expect(page.getByTestId("home-view")).toBeVisible();

    for (const [viewId, testId] of VIEW_TARGETS) {
      await openView(page, viewId, testId);
      await expectNoHorizontalScroll(page);
    }
  }
});
