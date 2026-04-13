import { existsSync, readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";

const AUTHOR_VIEW_PATH = new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url);
const AUTHOR_STORE_PATH = new URL("../src/stores/authorWorkspace.js", import.meta.url);
const AUTHOR_TRASH_VIEW_PATH = new URL("../src/views/AuthorTrashView.vue", import.meta.url);
const AUTHOR_TRASH_STORE_PATH = new URL("../src/stores/authorTrash.js", import.meta.url);

describe("author shell registration", () => {
  it("adds Author Workspace and Author Trash to the shell navigation", () => {
    const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(appSource).toContain("AuthorWorkspaceView");
    expect(appSource).toContain("AuthorTrashView");
    expect(appSource).toContain("activeView === 'author'");
    expect(appSource).toContain("activeView === 'trash'");
    expect(routerSource).toContain('{ id: "author", label: "浣滆€呭伐浣滃彴" }');
    expect(routerSource).toContain('{ id: "trash", label: "浣滆€呭洖鏀剁珯" }');
  });

  it("ships dedicated author workspace and author trash files", () => {
    expect(existsSync(AUTHOR_VIEW_PATH)).toBe(true);
    expect(existsSync(AUTHOR_STORE_PATH)).toBe(true);
    expect(existsSync(AUTHOR_TRASH_VIEW_PATH)).toBe(true);
    expect(existsSync(AUTHOR_TRASH_STORE_PATH)).toBe(true);
  });
});

describe("author lifecycle api helpers", () => {
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

  it("calls the dedicated author lifecycle endpoints", async () => {
    expect(typeof api.fetchChapters).toBe("function");
    expect(typeof api.fetchAuthorWorkspace).toBe("function");
    expect(typeof api.fetchAuthorTrash).toBe("function");
    expect(typeof api.saveChapter).toBe("function");
    expect(typeof api.saveScene).toBe("function");
    expect(typeof api.reorderChapterScenes).toBe("function");
    expect(typeof api.trashChapters).toBe("function");
    expect(typeof api.restoreChapters).toBe("function");
    expect(typeof api.purgeChapters).toBe("function");
    expect(typeof api.trashScenes).toBe("function");
    expect(typeof api.restoreScenes).toBe("function");
    expect(typeof api.purgeScenes).toBe("function");

    await api.fetchChapters();
    await api.fetchAuthorWorkspace("CH900");
    await api.fetchAuthorTrash();
    await api.saveChapter({ chapter_id: "CH900", chapter_goal: "Author a new chapter" });
    await api.saveScene({ scene_id: "CH900_SC01", chapter_id: "CH900", scene_goal: "Write the opening scene" });
    await api.reorderChapterScenes("CH900", {
      scene_ids: ["CH900_SC02", "CH900_SC01"],
      last_scene_id: "CH900_SC02",
    });
    await api.trashChapters(["CH900"]);
    await api.restoreChapters(["CH900"]);
    await api.purgeChapters(["CH900"]);
    await api.trashScenes(["CH900_SC01"]);
    await api.restoreScenes(["CH900_SC01"]);
    await api.purgeScenes(["CH900_SC01"]);

    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/chapters");
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/chapters/CH900/author-workspace");
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/author-trash");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters/trash",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters/restore",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters/purge",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/scenes/trash",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/scenes/restore",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/scenes/purge",
      expect.objectContaining({ method: "POST" }),
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

  it("loads chapters, saves author data, and moves selected rows into author trash", async () => {
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
          active_scene_count: 2,
          trashed_scene_count: 0,
          trash_allowed: 1,
          trash_block_reason: null,
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
      trash: {
        chapters: [],
        scenes: [],
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
            active_scene_count: state.workspace.scenes.length,
            trashed_scene_count: state.trash.scenes.length,
            trash_allowed: state.trash.scenes.length ? 0 : 1,
            trash_block_reason: state.trash.scenes.length ? "chapter contains individually trashed scenes" : null,
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
      if (url.endsWith("/api/v1/scenes/trash") && options.method === "POST") {
        const payload = JSON.parse(options.body);
        const trashedIds = new Set(payload.scene_ids);
        const removed = [];
        state.workspace.scenes = state.workspace.scenes.filter((scene) => {
          if (!trashedIds.has(scene.scene_id)) {
            return true;
          }
          removed.push({
            scene_id: scene.scene_id,
            chapter_id: scene.chapter_id,
            scene_seq: scene.scene_seq,
            scene_goal: scene.scene_goal,
            trashed_at: "2026-04-13T03:00:00+00:00",
            trashed_by: "ops.author",
            chapter_trashed: 0,
            restore_allowed: 1,
            restore_block_reason: null,
            purge_allowed: 1,
            purge_block_reason: null,
          });
          return false;
        });
        state.trash.scenes = [...state.trash.scenes, ...removed];
        state.chapters = state.chapters.map((chapter) => ({
          ...chapter,
          active_scene_count: state.workspace.scenes.length,
          trashed_scene_count: state.trash.scenes.length,
          trash_allowed: 0,
          trash_block_reason: "chapter contains individually trashed scenes",
        }));
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              processed: removed.map(({ scene_id }) => ({ scene_id })),
              blocked: [],
              actor_ref: "ops.author",
            },
          }),
        };
      }
      if (url.endsWith("/api/v1/chapters/trash") && options.method === "POST") {
        state.trash.chapters = [
          {
            chapter_id: "CH900",
            chapter_goal: "Updated chapter goal",
            trashed_at: "2026-04-13T04:00:00+00:00",
            trashed_by: "ops.author",
            scene_count: state.workspace.scenes.length,
            restore_allowed: 1,
            restore_block_reason: null,
            purge_allowed: 1,
            purge_block_reason: null,
          },
        ];
        state.trash.scenes = state.workspace.scenes.map((scene) => ({
          scene_id: scene.scene_id,
          chapter_id: scene.chapter_id,
          scene_seq: scene.scene_seq,
          scene_goal: scene.scene_goal,
          trashed_at: "2026-04-13T04:00:00+00:00",
          trashed_by: "ops.author",
          chapter_trashed: 1,
          restore_allowed: 0,
          restore_block_reason: "restore the chapter to recover this scene",
          purge_allowed: 0,
          purge_block_reason: "manage this scene from its trashed chapter",
        }));
        state.workspace.chapter = null;
        state.workspace.chapter_state = null;
        state.workspace.scenes = [];
        state.chapters = [];
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              processed: [{ chapter_id: "CH900", scene_ids: ["CH900_SC01"] }],
              blocked: [],
              actor_ref: "ops.author",
            },
          }),
        };
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
      if (url.endsWith("/api/v1/author-trash")) {
        return { ok: true, json: async () => ({ ok: true, data: state.trash }) };
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

    const sceneTrashMessage = await store.trashScenes(["CH900_SC02"]);
    expect(sceneTrashMessage).toContain("1");
    expect(store.chapters[0].trash_allowed).toBe(0);
    expect(store.chapters[0].trash_block_reason).toContain("trashed scenes");

    const chapterTrashMessage = await store.trashChapters(["CH900"]);
    expect(chapterTrashMessage).toContain("CH900");
    expect(store.chapters).toEqual([]);
    expect(store.chapter).toBeNull();
    expect(store.scenes).toEqual([]);
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/run/full"), expect.anything());
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/runtime/recovery/sweep"), expect.anything());
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/runtime/promotions/run-due"), expect.anything());
  });
});

describe("author trash store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads trash data and routes restore and purge actions through the dedicated store", async () => {
    const trashState = {
      chapters: [
        {
          chapter_id: "CH950",
          chapter_goal: "Archived chapter",
          trashed_at: "2026-04-13T05:00:00+00:00",
          trashed_by: "ops.author",
          scene_count: 1,
          restore_allowed: 1,
          restore_block_reason: null,
          purge_allowed: 1,
          purge_block_reason: null,
        },
      ],
      scenes: [
        {
          scene_id: "CH950_SC01",
          chapter_id: "CH950",
          scene_seq: 1,
          scene_goal: "Archived scene",
          trashed_at: "2026-04-13T05:00:00+00:00",
          trashed_by: "ops.author",
          chapter_trashed: 1,
          restore_allowed: 0,
          restore_block_reason: "restore the chapter to recover this scene",
          purge_allowed: 0,
          purge_block_reason: "manage this scene from its trashed chapter",
        },
      ],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/author-trash") && !options.method) {
        return { ok: true, json: async () => ({ ok: true, data: trashState }) };
      }
      if (url.endsWith("/api/v1/chapters") && !options.method) {
        return { ok: true, json: async () => ({ ok: true, data: { items: [] } }) };
      }
      if (url.endsWith("/api/v1/chapters/restore") && options.method === "POST") {
        trashState.chapters = [];
        trashState.scenes = [];
        return {
          ok: true,
          json: async () => ({ ok: true, data: { processed: [{ chapter_id: "CH950", scene_ids: ["CH950_SC01"] }], blocked: [] } }),
        };
      }
      if (url.endsWith("/api/v1/chapters/purge") && options.method === "POST") {
        trashState.chapters = [];
        return {
          ok: true,
          json: async () => ({ ok: true, data: { processed: [{ chapter_id: "CH950", scene_ids: ["CH950_SC01"] }], blocked: [] } }),
        };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const { useAuthorTrashStore } = await import("../src/stores/authorTrash.js");
    const store = useAuthorTrashStore();

    await store.load();
    expect(store.chapters).toHaveLength(1);
    expect(store.scenes).toHaveLength(1);

    const restoreMessage = await store.restoreChapters(["CH950"]);
    expect(restoreMessage).toContain("CH950");
    expect(store.chapters).toEqual([]);

    store.chapters = [
      {
        chapter_id: "CH950",
        chapter_goal: "Archived chapter",
        trashed_at: "2026-04-13T05:00:00+00:00",
        trashed_by: "ops.author",
        scene_count: 1,
        restore_allowed: 1,
        restore_block_reason: null,
        purge_allowed: 1,
        purge_block_reason: null,
      },
    ];
    const purgeMessage = await store.purgeChapters(["CH950"]);
    expect(purgeMessage).toContain("CH950");
  });
});

describe("author lifecycle source", () => {
  it("offers batch trash actions and an explicit handoff to Scene Workbench", () => {
    const source = readFileSync(AUTHOR_VIEW_PATH, "utf8");
    expect(source).toContain("author-trash-selected-chapters-button");
    expect(source).toContain("author-trash-selected-scenes-button");
    expect(source).toContain("chapter.trash_block_reason");
    expect(source).toContain("scene_card");
  });

  it("ships a dedicated author trash view with restore and purge actions", () => {
    const source = readFileSync(AUTHOR_TRASH_VIEW_PATH, "utf8");
    expect(source).toContain("author-trash-view");
    expect(source).toContain("author-trash-restore-chapters-button");
    expect(source).toContain("author-trash-purge-chapters-button");
    expect(source).toContain("author-trash-restore-scenes-button");
    expect(source).toContain("author-trash-purge-scenes-button");
  });
});
