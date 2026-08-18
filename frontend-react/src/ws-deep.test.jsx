import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
}));

import { apiGet, apiPatch } from "./lib/client.js";
import {
  wrDxApplyPreferences,
  wrDxLoadPreferences,
  wrDxMergePreferences,
  wrDxSavePreferences,
  wrDxSnapshot,
} from "./ws-deep.jsx";


describe("deep-review preference persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("merges logs without duplicates and preserves newest-first order", () => {
    const merged = wrDxMergePreferences(
      {
        decision_log: [{ at: 10, text: "远端" }, { at: 5, text: "重复" }],
        ignored_issue_keys: ["remote-key"],
      },
      {
        decision_log: [{ at: 20, text: "本地" }, { at: 5, text: "重复" }],
        ignored_issue_keys: ["local-key"],
      },
    );

    expect(merged.decision_log.map((entry) => entry.text)).toEqual(["本地", "远端", "重复"]);
    expect(merged.ignored_issue_keys).toEqual(["local-key", "remote-key"]);
  });

  it("can make an explicit local clear authoritative while rebasing a conflict", () => {
    const merged = wrDxMergePreferences(
      { decision_log: [], ignored_issue_keys: ["stale-remote-key"] },
      { decision_log: [], ignored_issue_keys: [] },
      { localIgnoredAuthoritative: true },
    );

    expect(merged.ignored_issue_keys).toEqual([]);
  });

  it("keeps a local backup and sends a revision-fenced server update", async () => {
    const snapshot = wrDxApplyPreferences("SC/01", {
      decision_log: [{ at: 123, text: "忽略 · 重复" }],
      ignored_issue_keys: ["echo:1", "echo:1"],
    });
    apiPatch.mockResolvedValue({ ...snapshot, revision_no: 4 });

    expect(wrDxSnapshot("SC/01")).toEqual({
      decision_log: [{ at: 123, text: "忽略 · 重复" }],
      ignored_issue_keys: ["echo:1"],
    });
    await expect(wrDxSavePreferences("SC/01", snapshot, 3)).resolves.toMatchObject({ revision_no: 4 });
    expect(apiPatch).toHaveBeenCalledWith("/api/v1/scenes/SC%2F01/deep-review/preferences", {
      decision_log: snapshot.decision_log,
      ignored_issue_keys: ["echo:1"],
      base_revision_no: 3,
    });
  });

  it("loads the authoritative scene preference resource", async () => {
    apiGet.mockResolvedValue({ decision_log: [], ignored_issue_keys: [], revision_no: 2 });

    await expect(wrDxLoadPreferences("SC 01")).resolves.toMatchObject({ revision_no: 2 });
    expect(apiGet).toHaveBeenCalledWith("/api/v1/scenes/SC%2001/deep-review/preferences");
  });
});
