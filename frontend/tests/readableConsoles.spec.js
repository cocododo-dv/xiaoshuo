// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkbenchStore } from "../src/stores/workbench";

const LAST_SCENE_KEY = "novel-system:last-workbench-scene-id";
const SOURCE_ROOT = process.cwd();

function scenePayload(sceneId) {
  return {
    scene_card: { scene_id: sceneId, scene_goal: "Make the workbench readable" },
    chapter_goal: { chapter_id: sceneId.split("_")[0], chapter_goal: "Readable author flow" },
    scene_run_state: {
      scene_status: "archived",
      current_final_scene_row_id: `final_scene_${sceneId}`,
    },
    run_preflight: {
      can_run: true,
      overall_status: "ready",
      blocking_items: [],
      warning_items: [],
      context_items: [],
    },
    bundle: { bundle_id: `bundle_${sceneId}` },
    chapter_state: {
      staged_backfill_items: [],
      chapter_backfill_pending_count: 0,
      aggregate_block_reason: "none",
      manual_hold_reason: "",
      last_final_memory_row_id: "",
    },
    attempts: [],
  };
}

function okEnvelope(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

function emptyCursorEnvelope() {
  return okEnvelope({
    items: [],
    pagination: {
      mode: "cursor",
      limit: 25,
      returned: 0,
      has_next: false,
      next_cursor: null,
    },
  });
}

describe("readable scene workbench", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("starts without forcing the old CH001_SC01 default scene", () => {
    const store = useWorkbenchStore();

    expect(store.sceneId).toBe("");
    expect(store.attemptSceneId).toBe("");
  });

  it("remembers the last successfully loaded scene and does not overwrite it after a failed load", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/scenes/CHQA01_SC01/workbench")) {
        return okEnvelope(scenePayload("CHQA01_SC01"));
      }
      if (url.includes("/human-review-events?scene_id=CHQA01_SC01")) {
        return okEnvelope({ items: [] });
      }
      if (url.includes("/scenes/CHQA01_SC01/attempts")) {
        return emptyCursorEnvelope();
      }
      if (url.includes("/scenes/MISSING_SC01/workbench")) {
        return {
          ok: false,
          json: async () => ({ ok: false, error: { message: "scene not found" } }),
        };
      }
      if (url.includes("/human-review-events?scene_id=MISSING_SC01")) {
        return okEnvelope({ items: [] });
      }
      if (url.includes("/scenes/MISSING_SC01/attempts")) {
        return emptyCursorEnvelope();
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    await store.refreshAll("CHQA01_SC01", { force: true });

    expect(localStorage.getItem(LAST_SCENE_KEY)).toBe("CHQA01_SC01");

    await store.refreshAll("MISSING_SC01", { force: true });

    expect(store.error).toBe("scene not found");
    expect(localStorage.getItem(LAST_SCENE_KEY)).toBe("CHQA01_SC01");

    setActivePinia(createPinia());
    const restored = useWorkbenchStore();
    expect(restored.sceneId).toBe("CHQA01_SC01");
  });

  it("clears a stale stored scene id when the remembered scene no longer exists", async () => {
    localStorage.setItem(LAST_SCENE_KEY, "MISSING_SC01");
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/scenes/MISSING_SC01/workbench")) {
        return {
          ok: false,
          json: async () => ({ ok: false, error: { message: "scene not found" } }),
        };
      }
      if (url.includes("/human-review-events?scene_id=MISSING_SC01")) {
        return okEnvelope({ items: [] });
      }
      if (url.includes("/scenes/MISSING_SC01/attempts")) {
        return emptyCursorEnvelope();
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    expect(store.sceneId).toBe("MISSING_SC01");

    await store.ensureLoaded({ force: true });

    expect(store.sceneId).toBe("");
    expect(store.data).toBeNull();
    expect(localStorage.getItem(LAST_SCENE_KEY)).toBeNull();
    expect(store.error).toContain("scene not found");
  });

  it("surfaces purpose, status evidence, and missing-scene recovery guidance in the workbench view", () => {
    const source = readFileSync(path.join(SOURCE_ROOT, "src/views/SceneWorkbenchView.vue"), "utf8");

    expect(source).toContain("本页用于生成与验收单场景");
    expect(source).toContain("workbench-purpose-strip");
    expect(source).toContain("scene-missing-guidance");
    expect(source).toContain("从作者工作台选择场景");
    expect(source).toContain("回到作者工作台");
  });
});

describe("user-facing Chinese readability guard", () => {
  it("keeps common shell, pager, and workbench strings out of mojibake", () => {
    const files = [
      "src/router.js",
      "src/components/CursorPager.vue",
      "src/stores/workbench.js",
      "src/views/ReferenceLearningView.vue",
      "src/views/AuthorWorkspaceView.vue",
      "src/views/SceneWorkbenchView.vue",
      "src/views/ReviewInboxView.vue",
      "src/views/IndexConsoleView.vue",
      "src/views/KnowledgeConsoleView.vue",
      "src/views/InteropCenterView.vue",
      "src/views/AuthorTrashView.vue",
      "src/views/SystemConfigView.vue",
    ];
    const mojibakeFingerprints = [
      "浣滆",
      "鍦烘",
      "瀹℃",
      "鏆傛",
      "涓婁竴",
      "鐭ヨ",
      "绱㈠",
      "鍙傝",
      "鎿嶄",
      "鍚",
    ];
    const offenders = [];

    for (const file of files) {
      const source = readFileSync(path.join(SOURCE_ROOT, file), "utf8");
      const lines = source.split(/\r?\n/);
      lines.forEach((line, index) => {
        if (mojibakeFingerprints.some((fingerprint) => line.includes(fingerprint))) {
          offenders.push(`${file}:${index + 1}:${line.trim()}`);
        }
      });
    }

    expect(offenders).toEqual([]);
  });
});

describe("readable index console", () => {
  it("explains index operations, summarizes action status, and formats internal target refs", () => {
    const source = readFileSync(path.join(SOURCE_ROOT, "src/views/IndexConsoleView.vue"), "utf8");

    expect(source).toContain("发布、校验、恢复知识与审核结果");
    expect(source).toContain("index-summary-strip");
    expect(source).toContain("formatReadableTargetRef");
    expect(source).toContain("校准句 / 全局 / 全局");
    expect(source).toContain("高级详情");
    expect(source).toContain("历史校验记录");
  });
});

describe("readable knowledge console", () => {
  it("explains knowledge purpose, candidate workflow, and evidence-first detail sections", () => {
    const source = readFileSync(path.join(SOURCE_ROOT, "src/views/KnowledgeConsoleView.vue"), "utf8");

    expect(source).toContain("长期设定与风格知识库");
    expect(source).toContain("创建候选 -> 批准 -> 必要时校验 -> 发布/生效");
    expect(source).toContain("知识名称");
    expect(source).toContain('isAdvancedMode ? "血缘 key" : "知识名称"');
    expect(source).toContain("生效范围与证据");
    expect(source).toContain("高级引用");
  });
});

describe("three-chapter QA report evidence", () => {
  it("answers the user comments about whether console pages were used", () => {
    const report = readFileSync(
      path.resolve(SOURCE_ROOT, "../output/playwright/three-chapter-qa/report.md"),
      "utf8",
    );

    expect(report).toContain("用户标注回应");
    expect(report).toContain("Comment 1");
    expect(report).toContain("场景工作台");
    expect(report).toContain("run-scenes-workbench.js");
    expect(report).toContain("Comment 4");
    expect(report).toContain("知识控制台");
    expect(report).toContain("knowledge-bootstrap.js");
  });
});
