import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

function resolveVueImport(importerPath, specifier) {
  if (!specifier.startsWith(".") || !specifier.endsWith(".vue")) {
    return null;
  }
  return path.normalize(path.join(path.dirname(importerPath), specifier)).replace(/\\/g, "/");
}

function readVueImportGraphSource(entryPath) {
  const seen = new Set();
  const chunks = [];

  function visit(relativePath) {
    if (seen.has(relativePath)) {
      return;
    }
    seen.add(relativePath);

    const source = readSource(relativePath);
    chunks.push(source);

    for (const match of source.matchAll(/import\s+[^;]+?\s+from\s+["']([^"']+\.vue)["']/g)) {
      const resolved = resolveVueImport(relativePath, match[1]);
      if (resolved) {
        visit(resolved);
      }
    }
  }

  visit(entryPath);
  return chunks.join("\n");
}

function readDeepDeskViewSource() {
  return readVueImportGraphSource("src/views/WriterDeepDeskView.vue");
}

describe("current DB layout readability guards", () => {
  it("ships shared compact selectors and overflow utilities for dense writer pages", () => {
    const writerRoom = readSource("src/views/WriterRoomView.vue");
    const deepDesk = readDeepDeskViewSource();
    const css = readSource("src/styles/app.css");

    expect(writerRoom).toContain("CompactEntitySelect");
    expect(writerRoom).toContain("compactEntityOptions");
    expect(deepDesk).toContain("CompactEntitySelect");
    expect(css).toContain(".technical-ref");
    expect(css).toContain(".line-clamp-2");
    expect(css).toContain(".wrap-anywhere");
    expect(css).toContain(".compact-history-row");
  });

  it("uses shared readable rows for cramped chapter selectors and index jobs", () => {
    const manuscripts = readSource("src/views/ChapterManuscriptView.vue");
    const deepDesk = readDeepDeskViewSource();
    const indexConsole = readSource("src/views/IndexConsoleView.vue");
    const css = readSource("src/styles/app.css");

    expect(css).toContain(".readable-list");
    expect(css).toContain(".readable-selector-row");
    expect(css).toContain(".readable-row-main");
    expect(css).toContain(".readable-row-title");
    expect(css).toContain(".readable-row-copy");
    expect(css).toContain(".readable-row-meta");
    expect(css).toContain(".readable-tech-ref");
    expect(css).toContain(".readable-job-row");
    expect(css).toMatch(/\.readable-job-row[\s\S]*grid-template-columns/);

    expect(manuscripts).toContain("readable-list manuscript-chapter-list");
    expect(manuscripts).toContain("readable-selector-row manuscript-list-row");
    expect(manuscripts).toContain("readable-row-title");
    expect(manuscripts).toContain("readable-tech-ref");

    expect(deepDesk).toContain("readable-list deep-chapter-list");
    expect(deepDesk).toContain("readable-selector-row deep-chapter-row");
    expect(deepDesk).toContain("readable-row-copy");

    expect(indexConsole).toContain("readable-job-row");
    expect(indexConsole).toContain("readable-row-meta job-diagnostics");
    expect(indexConsole).toContain("readable-tech-ref");
  });

  it("keeps raw technical refs out of primary author-facing cards", () => {
    const author = readSource("src/views/AuthorWorkspaceView.vue");
    const quality = readSource("src/views/LiteraryQualityView.vue");
    const longform = readSource("src/views/LongformControlView.vue");
    const aliasCard = readSource("src/components/AliasScopeCard.vue");
    const knowledge = readSource("src/views/KnowledgeConsoleView.vue");

    expect(author).toContain("row.chapterLabel");
    expect(author).toContain("row.technicalRef");
    expect(quality).toContain("qualityObjectLabel");
    expect(quality).toContain("qualityTechnicalRef");
    expect(longform).toContain("formatChapterChoice");
    expect(longform).toContain("longform-card-grid readable-grid");
    expect(aliasCard).toContain("readableAliasScope.technical");
    expect(knowledge).toContain("compact-history-row");
  });

  it("keeps the LLM provider model editor compact until explicitly expanded", () => {
    const config = readSource("src/views/SystemConfigView.vue");
    const css = readSource("src/styles/app.css");

    expect(config).toContain("config-llm-provider-model-preview");
    expect(config).toContain("config-llm-provider-model-editor");
    expect(config).toContain("config-llm-provider-model-catalog-note");
    expect(css).toContain(".llm-model-raw-editor:not([open]) .llm-model-list-editor");
  });
});
