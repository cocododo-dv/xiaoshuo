import { expect } from "@playwright/test";

const defaultApiBase = `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;

export async function configureConnection(page, { apiBase = defaultApiBase, operatorRef = "operator" } = {}) {
  await page.evaluate(
    ({ nextApiBase, nextOperatorRef }) => {
      window.localStorage.setItem("novel-system-api-base", nextApiBase);
      window.localStorage.setItem("novel-system-operator-ref", nextOperatorRef);
    },
    { nextApiBase: apiBase, nextOperatorRef: operatorRef },
  );
}

// The console-style views (workbench / author / manuscripts / knowledge /
// interop / deepdesk / index) are only mounted in advanced UI mode. The app
// defaults to writer mode landing on the snowflake workbench, so any spec that
// drives those console surfaces must opt into advanced mode first. Mirrors the
// proven helper in smoothness-navigation.spec.js.
export async function switchToAdvancedMode(page) {
  const mode = await page.evaluate(() => window.localStorage.getItem("novel-system:ui-mode"));
  if (mode !== "advanced") {
    await page.getByTestId("ui-mode-advanced").click();
  }
  await expect
    .poll(() => page.evaluate(() => window.localStorage.getItem("novel-system:ui-mode")))
    .toBe("advanced");
}
