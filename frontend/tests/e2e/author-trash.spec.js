import { expect, test } from "@playwright/test";

test("moves author records through trash, blocks ambiguous chapter delete, restores scenes, and purges clean chapters", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("api-base-input").fill("http://127.0.0.1:8000");
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.author.trash.e2e");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-workspace-view")).toBeVisible();

  await page.getByTestId("author-new-chapter-button").click();
  await page.getByTestId("author-chapter-id").fill("CH310");
  await page.getByTestId("author-chapter-scene-count").fill("2");
  await page.getByTestId("author-chapter-goal").fill("Lifecycle chapter");
  await page.getByTestId("author-save-chapter-button").click();

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH310_SC01");
  await page.getByTestId("author-scene-goal").fill("First scene");
  await page.getByTestId("author-save-scene-button").click();

  await page.getByTestId("author-new-scene-button").click();
  await page.getByTestId("author-scene-id").fill("CH310_SC02");
  await page.getByTestId("author-scene-goal").fill("Second scene");
  await page.getByTestId("author-save-scene-button").click();

  await page.getByTestId("author-scene-select-CH310_SC02").check();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("author-trash-selected-scenes-button").click();

  await expect(page.getByTestId("author-chapter-trash-block-CH310")).toContainText("trashed");
  await expect(page.getByTestId("author-chapter-select-for-trash-CH310")).toBeDisabled();

  await page.getByTestId("nav-trash").click();
  await expect(page.getByTestId("author-trash-view")).toBeVisible();
  await expect(page.getByTestId("author-trash-scene-row-CH310_SC02")).toContainText("CH310_SC02");

  await page.getByTestId("author-trash-scene-select-CH310_SC02").check();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("author-trash-restore-scenes-button").click();

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-scene-row-CH310_SC02")).toBeVisible();

  await page.getByTestId("author-chapter-select-for-trash-CH310").check();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("author-trash-selected-chapters-button").click();

  await page.getByTestId("nav-trash").click();
  await expect(page.getByTestId("author-trash-chapter-row-CH310")).toContainText("CH310");
  await page.getByTestId("author-trash-chapter-select-CH310").check();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("author-trash-purge-chapters-button").click();

  await expect(page.getByTestId("author-trash-empty")).toBeVisible();
});
