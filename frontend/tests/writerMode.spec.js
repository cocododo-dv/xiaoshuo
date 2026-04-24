// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

describe("writer mode", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("migrates old guided mode storage to writer mode", async () => {
    localStorage.setItem("novel-system:ui-mode", "guided");

    const { UI_MODE_STORAGE_KEY, useUiMode } = await import("../src/composables/useUiMode.js");
    const mode = useUiMode();

    expect(mode.uiMode.value).toBe("writer");
    expect(mode.isAdvancedMode.value).toBe(false);
    expect(localStorage.getItem(UI_MODE_STORAGE_KEY)).toBe("writer");

    mode.setUiMode("guided");
    expect(mode.uiMode.value).toBe("writer");
  });

  it("renames the visible mode switch to writer while keeping advanced available", () => {
    const source = readSource("src/components/UiModeSwitch.vue");

    expect(source).toContain('data-testid="ui-mode-writer"');
    expect(source).toContain("setUiMode('writer')");
    expect(source).toContain('data-testid="ui-mode-advanced"');
  });

  it("adds drama cards to the author workspace forms", () => {
    const source = readSource("src/views/AuthorWorkspaceView.vue");

    expect(source).toContain("chapterWriterBriefFields");
    expect(source).toContain("sceneWriterBriefFields");
    expect(source).toContain("writer_brief_json");
    expect(source).toContain("core_promise");
    expect(source).toContain("character_desire");
  });

  it("keeps engineering evidence behind advanced mode in the scene workbench and adds writer review", () => {
    const source = readSource("src/views/SceneWorkbenchView.vue");

    expect(source).toContain("WriterReviewCard");
    expect(source).toContain("writerReviewSummary");
    expect(source).toContain('v-if="isAdvancedMode"');
    expect(source).toContain("@run=\"runWriterReview\"");
  });

  it("exposes writer review endpoints through the frontend API layer", () => {
    const source = readSource("src/lib/api.js");

    expect(source).toContain("runSceneWriterReview");
    expect(source).toContain("/writer-review/run");
    expect(source).toContain("acceptRevisionCandidate");
    expect(source).toContain("rejectRevisionCandidate");
  });

  it("renders evidence-backed findings and professional revision metadata", () => {
    const source = readSource("src/components/WriterReviewCard.vue");

    expect(source).toContain("evidence_excerpt");
    expect(source).toContain("evidence_location");
    expect(source).toContain("why_it_matters");
    expect(source).toContain("candidate_kind");
    expect(source).toContain("changed_dimensions");
    expect(source).toContain("rewrite_strategy");
  });
});
