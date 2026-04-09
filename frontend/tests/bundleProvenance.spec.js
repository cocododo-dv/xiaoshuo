import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { buildBundleProvenance } from "../src/lib/bundleProvenance";

describe("buildBundleProvenance", () => {
  it("normalizes traceable source rows and ordered injections from a bundle snapshot", () => {
    const snapshot = {
      source_version_refs: {
        chapter_goal: "CH001",
        scene_card: "CH001_SC01",
        voice_profile_id: "VOICE_CHAR_A",
        voice_profile_row_id: "voice_profile_VOICE_CHAR_A_v1",
        voice_profile_version: 1,
        relation_profile_id: "REL_CHAR_A_CHAR_B",
        relation_profile_row_id: "relation_profile_REL_CHAR_A_CHAR_B_v1",
        relation_profile_version: 1,
        scene_memory_prev: "CH000_SC03",
      },
      ordered_injections: [
        { slot: "chapter_goal", ref_id: "CH001", digest_key: "chapter_goal" },
        { slot: "scene_card", ref_id: "CH001_SC01", digest_key: "scene_card" },
        { slot: "pov_voice", ref_id: "VOICE_CHAR_A", digest_key: "voice_card" },
        { slot: "relation", ref_id: "REL_CHAR_A_CHAR_B", digest_key: "relation_card" },
        { slot: "prev_scene_memory", ref_id: "CH000_SC03", digest_key: "scene_memory" },
      ],
      inline_digests: {
        chapter_goal: "Reunion under pressure",
        scene_card: "Force the pair to talk without resolving the conflict",
        voice_card: "short clipped lines; pressure makes the tone harder",
        relation_card: "reunion tension; B knows slightly more than A",
        scene_memory: "They last separated without resolving the letter",
      },
    };

    const provenance = buildBundleProvenance(snapshot);

    expect(provenance.available).toBe(true);
    expect(provenance.sources).toEqual([
      {
        key: "voice_profile",
        label: "Voice profile",
        logicalId: "VOICE_CHAR_A",
        rowId: "voice_profile_VOICE_CHAR_A_v1",
        version: 1,
        digest: "short clipped lines; pressure makes the tone harder",
      },
      {
        key: "relation_profile",
        label: "Relation profile",
        logicalId: "REL_CHAR_A_CHAR_B",
        rowId: "relation_profile_REL_CHAR_A_CHAR_B_v1",
        version: 1,
        digest: "reunion tension; B knows slightly more than A",
      },
      {
        key: "scene_memory_prev",
        label: "Previous scene memory",
        logicalId: "CH000_SC03",
        rowId: null,
        version: null,
        digest: "They last separated without resolving the letter",
      },
    ]);
    expect(provenance.injections[2]).toEqual({
      slot: "pov_voice",
      slotLabel: "POV voice",
      refId: "VOICE_CHAR_A",
      digestKey: "voice_card",
      digest: "short clipped lines; pressure makes the tone harder",
    });
    expect(provenance.injections[4]).toEqual({
      slot: "prev_scene_memory",
      slotLabel: "Previous scene memory",
      refId: "CH000_SC03",
      digestKey: "scene_memory",
      digest: "They last separated without resolving the letter",
    });
  });

  it("returns empty provenance when no snapshot is available yet", () => {
    expect(buildBundleProvenance(null)).toEqual({
      available: false,
      sources: [],
      injections: [],
    });
  });
});

describe("scene workbench source", () => {
  it("mounts a provenance card for the current bundle snapshot", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source).toContain("BundleProvenanceCard");
    expect(source).toContain("workbench.data.bundle?.snapshot");
  });

  it("wires a run action and receipt section into the scene workbench", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source).toContain("Run Full Scene");
    expect(source).toContain("workbench.runScene");
    expect(source).toContain("lastRunResult");
  });

  it("keeps populated workbench content visible ahead of the error-only branch", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source.indexOf('v-else-if="hasData"')).toBeLessThan(source.indexOf('v-else-if="workbench.error"'));
    expect(source).toContain('v-if="workbench.error" class="paper inline-error"');
  });
});
