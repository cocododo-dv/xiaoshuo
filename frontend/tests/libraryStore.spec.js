import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLibraryStore } from "../src/stores/library";

function ok(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

describe("library store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the project library overview and merges refs for relation pickers", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (String(url).includes("/api/v2/projects/PRJ_LIB/library")) {
        return ok({
          project_id: "PRJ_LIB",
          characters: [{ character_id: "CHAR_A", name: "苏怀梅", kind: "character", ref: "character:CHAR_A" }],
          entities: [{ entity_id: "ENT_1", name: "盐场", kind: "location", status: "active", ref: "entity:ENT_1" }],
          relations: [],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useLibraryStore();
    await store.load("PRJ_LIB");

    expect(store.projectId).toBe("PRJ_LIB");
    expect(store.characters).toHaveLength(1);
    expect(store.entitiesByKind("location")).toHaveLength(1);
    expect(store.allRefs.map((item) => item.ref)).toEqual(["character:CHAR_A", "entity:ENT_1"]);
  });

  it("creates entities and relations against the loaded project", async () => {
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const requestUrl = String(url);
      if (requestUrl.endsWith("/library/entities") && options.method === "POST") {
        return ok({ entity_id: "ENT_2", name: "旧工牌", kind: "item", status: "active", ref: "entity:ENT_2" });
      }
      if (requestUrl.endsWith("/library/relations") && options.method === "POST") {
        return ok({ relation_id: "REL_1", from_ref: "entity:ENT_2", to_ref: "character:CHAR_A", kind: "belongs_to" });
      }
      if (requestUrl.includes("/library/relations/REL_1")) {
        return ok({ relation_id: "REL_1", deleted: true });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useLibraryStore();
    store.projectId = "PRJ_LIB";

    await store.createEntity({ kind: "item", name: "旧工牌" });
    expect(store.entities.map((item) => item.entity_id)).toEqual(["ENT_2"]);

    await store.createRelation({ from_ref: "entity:ENT_2", to_ref: "character:CHAR_A", kind: "belongs_to" });
    expect(store.relations).toHaveLength(1);

    await store.removeRelation("REL_1");
    expect(store.relations).toEqual([]);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v2/projects/PRJ_LIB/library/entities",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps the inbox-style error contract on failures", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ ok: false, error: { code: "LIBRARY_ENTITY_NAME_REQUIRED", message: "entity name is required" } }),
    }));

    const store = useLibraryStore();
    store.projectId = "PRJ_LIB";

    await expect(store.createEntity({ kind: "item", name: "" })).rejects.toThrow("entity name is required");
    expect(store.error).toContain("entity name is required");
    expect(store.actionId).toBe("");
  });
});
