import { existsSync, readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";

const AUTHOR_VIEW_PATH = new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url);
const AUTHOR_STORE_PATH = new URL("../src/stores/authorWorkspace.js", import.meta.url);

describe("author workspace shell registration", () => {
  it("adds Author Workspace to the shell navigation", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(source).toContain("Author Workspace");
    expect(source).toContain("AuthorWorkspaceView");
    expect(source).toContain("activeView === 'author'");
    expect(routerSource).toContain('{ id: "author", label: "Author Workspace" }');
  });

  it("ships dedicated author workspace view and store files", () => {
    expect(existsSync(AUTHOR_VIEW_PATH)).toBe(true);
    expect(existsSync(AUTHOR_STORE_PATH)).toBe(true);
  });
});

describe("author workspace api helpers", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(async (url, options = {}) => ({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          url,
          method: options.method || "GET",
          body: options.body ? JSON.parse(options.body) : null,
        },
      }),
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls the dedicated author workspace endpoints", async () => {
    expect(typeof api.fetchChapters).toBe("function");
    expect(typeof api.fetchAuthorWorkspace).toBe("function");
    expect(typeof api.saveChapter).toBe("function");
    expect(typeof api.saveScene).toBe("function");
    expect(typeof api.reorderChapterScenes).toBe("function");

    await api.fetchChapters();
    await api.fetchAuthorWorkspace("CH900");
    await api.saveChapter({ chapter_id: "CH900", chapter_goal: "Author a new chapter" });
    await api.saveScene({ scene_id: "CH900_SC01", chapter_id: "CH900", scene_goal: "Write the opening scene" });
    await api.reorderChapterScenes("CH900", {
      scene_ids: ["CH900_SC02", "CH900_SC01"],
      last_scene_id: "CH900_SC02",
    });

    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/chapters");
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/chapters/CH900/author-workspace");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/scenes",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters/CH900/scene-order",
      expect.objectContaining({
        method: "POST",
      }),
    );
  });
});

describe("author workspace store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads chapters, saves author data, and reorders scenes without touching runtime mutation endpoints", async () => {
    const hasStore = existsSync(AUTHOR_STORE_PATH);
    expect(hasStore).toBe(true);
    if (!hasStore) {
      return;
    }

    const state = {
      chapters: [
        {
          chapter_id: "CH900",
          planned_scene_count: 2,
          chapter_goal: "Original chapter goal",
          main_plot_push: "Original push",
          emotional_target: "Original emotion",
          ending_effect: "Original ending",
          must_not: "Original must not",
          notes: "Original notes",
          current_phase: "drafting",
          chapter_passed_scene_count: 0,
          chapter_backfill_pending_count: 0,
        },
      ],
      workspace: {
        chapter: {
          chapter_id: "CH900",
          planned_scene_count: 2,
          mid_aggregate_enabled: 0,
          chapter_goal: "Original chapter goal",
          main_plot_push: "Original push",
          emotional_target: "Original emotion",
          ending_effect: "Original ending",
          must_not: "Original must not",
          notes: "Original notes",
        },
        chapter_state: {
          chapter_id: "CH900",
          current_phase: "drafting",
          chapter_passed_scene_count: 0,
          chapter_backfill_pending_count: 0,
        },
        scenes: [
          {
            scene_id: "CH900_SC01",
            chapter_id: "CH900",
            scene_seq: 1,
            pov_character_id: "CHAR_A",
            onstage_chars_json: ["CHAR_A"],
            resolved_relation_id: null,
            location: "North gate",
            scene_goal: "Opening encounter",
            beats_json: ["enter", "recognize"],
            must_include_text: "an old letter",
            forbidden_text: "",
            exit_change: "",
            hook: "",
            target_length_band: "short",
            scene_type: "reunion",
            is_chapter_last: 0,
            scene_status: "ready",
            current_bundle_id: null,
            current_final_scene_row_id: null,
          },
          {
            scene_id: "CH900_SC02",
            chapter_id: "CH900",
            scene_seq: 2,
            pov_character_id: "CHAR_B",
            onstage_chars_json: ["CHAR_B"],
            resolved_relation_id: null,
            location: "Clock tower",
            scene_goal: "Pressure rises",
            beats_json: ["pressure", "withhold"],
            must_include_text: "a coded reply",
            forbidden_text: "",
            exit_change: "",
            hook: "",
            target_length_band: "medium",
            scene_type: "bridge",
            is_chapter_last: 1,
            scene_status: "ready",
            current_bundle_id: null,
            current_final_scene_row_id: null,
          },
        ],
      },
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/chapters") && !options.method) {
        return { ok: true, json: async () => ({ ok: true, data: { items: state.chapters } }) };
      }
      if (url.endsWith("/api/v1/chapters") && options.method === "POST") {
        const payload = JSON.parse(options.body);
        state.chapters = [
          {
            ...state.chapters[0],
            ...payload,
            current_phase: "drafting",
            chapter_passed_scene_count: 0,
            chapter_backfill_pending_count: 0,
          },
        ];
        state.workspace.chapter = {
          ...state.workspace.chapter,
          ...payload,
        };
        return { ok: true, json: async () => ({ ok: true, data: { chapter_id: payload.chapter_id } }) };
      }
      if (url.endsWith("/api/v1/chapters/CH900/author-workspace")) {
        return { ok: true, json: async () => ({ ok: true, data: state.workspace }) };
      }
      if (url.endsWith("/api/v1/scenes") && options.method === "POST") {
        const payload = JSON.parse(options.body);
        const existingIndex = state.workspace.scenes.findIndex((scene) => scene.scene_id === payload.scene_id);
        const nextScene = {
          ...state.workspace.scenes[existingIndex] ?? {
            scene_seq: state.workspace.scenes.length + 1,
            is_chapter_last: 0,
            scene_status: "ready",
            current_bundle_id: null,
            current_final_scene_row_id: null,
          },
          ...payload,
          chapter_id: "CH900",
        };
        if (existingIndex >= 0) {
          state.workspace.scenes.splice(existingIndex, 1, nextScene);
        } else {
          state.workspace.scenes.push(nextScene);
        }
        return { ok: true, json: async () => ({ ok: true, data: { scene_id: payload.scene_id } }) };
      }
      if (url.endsWith("/api/v1/chapters/CH900/scene-order") && options.method === "POST") {
        const payload = JSON.parse(options.body);
        state.workspace.scenes = payload.scene_ids.map((sceneId, index) => {
          const scene = state.workspace.scenes.find((item) => item.scene_id === sceneId);
          return {
            ...scene,
            scene_seq: index + 1,
            is_chapter_last: Number(sceneId === payload.last_scene_id),
          };
        });
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              chapter_id: "CH900",
              scenes: state.workspace.scenes.map(({ scene_id, scene_seq, is_chapter_last }) => ({
                scene_id,
                scene_seq,
                is_chapter_last,
              })),
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const { useAuthorWorkspaceStore } = await import("../src/stores/authorWorkspace.js");
    const store = useAuthorWorkspaceStore();

    await store.loadChapters();
    await store.loadWorkspace("CH900");
    await store.saveChapter({
      chapter_id: "CH900",
      planned_scene_count: 2,
      mid_aggregate_enabled: 1,
      chapter_goal: "Updated chapter goal",
      main_plot_push: "Updated push",
      emotional_target: "Updated emotion",
      ending_effect: "Updated ending",
      must_not: "Updated must not",
      notes: "Updated notes",
    });
    await store.saveScene({
      scene_id: "CH900_SC01",
      chapter_id: "CH900",
      pov_character_id: "CHAR_A",
      onstage_chars_json: ["CHAR_A", "CHAR_B"],
      location: "North gate",
      scene_goal: "Updated opening encounter",
      beats_json: ["enter", "turn"],
      must_include_text: "an updated old letter",
      forbidden_text: "no confession",
      exit_change: "tension rises",
      hook: "follow the coded reply",
      target_length_band: "medium",
      scene_type: "reunion",
    });
    await store.reorderScenes(["CH900_SC02", "CH900_SC01"], "CH900_SC01");

    expect(store.chapters[0].chapter_goal).toBe("Updated chapter goal");
    expect(store.chapter.chapter_goal).toBe("Updated chapter goal");
    expect(store.scenes[0].scene_id).toBe("CH900_SC02");
    expect(store.scenes[1].scene_id).toBe("CH900_SC01");
    expect(store.scenes[1].is_chapter_last).toBe(1);
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/run/full"), expect.anything());
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/runtime/recovery/sweep"), expect.anything());
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/runtime/promotions/run-due"), expect.anything());
  });
});

describe("author workspace source", () => {
  it("offers an explicit handoff to Scene Workbench", () => {
    const hasView = existsSync(AUTHOR_VIEW_PATH);
    expect(hasView).toBe(true);
    if (!hasView) {
      return;
    }

    const source = readFileSync(AUTHOR_VIEW_PATH, "utf8");
    expect(source).toContain("Open in Scene Workbench");
    expect(source).toContain("scene_card");
  });
});
