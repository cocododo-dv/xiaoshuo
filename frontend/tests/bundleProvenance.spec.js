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

  it("surfaces extended knowledge-family sources and injections from the bundle snapshot", () => {
    const snapshot = {
      source_version_refs: {
        style_rule_set_id: "STYLE_GLOBAL_MAIN",
        banned_cluster_id: "BAN_REUNION_V1",
        calibration_line_ids: ["CAL_002"],
        scene_summary_id: "CH001_SC01",
        chapter_summary_id: "CH001",
      },
      resolved_ref_ids: {
        relation_ids: ["REL_CHAR_A_CHAR_B"],
        world_rule_ids: ["WR_GLOBAL_014"],
        open_foreshadow_ids: ["F014"],
      },
      ordered_injections: [
        { slot: "style_rules", ref_id: "STYLE_GLOBAL_MAIN", digest_key: "style_rule" },
        { slot: "banned_rules", ref_id: "BAN_REUNION_V1", digest_key: "banned_rule" },
        { slot: "calibration_lines", ref_id: "CAL_002", digest_key: "calibration_line" },
        { slot: "world_rules", ref_id: "WR_GLOBAL_014", digest_key: "world_rule" },
        { slot: "foreshadow", ref_id: "F014", digest_key: "foreshadow" },
        { slot: "scene_summary", ref_id: "CH001_SC01", digest_key: "scene_summary" },
        { slot: "chapter_summary", ref_id: "CH001", digest_key: "chapter_summary" },
      ],
      inline_digests: {
        style_rule: "keep emotion in gesture and pause",
        banned_rule: "do not explain the whole backstory at reunion time",
        calibration_line: "the door closed like a sentence left unfinished",
        world_rule: "public spellcasting inside the city is forbidden",
        foreshadow: "the old letter sender clue is now in play",
        scene_summary: "scene summary for the first reunion beat",
        chapter_summary: "chapter summary for the first reunion chapter",
      },
    };

    const provenance = buildBundleProvenance(snapshot);

    expect(provenance.sources).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "style_rule",
          label: "Style rule set",
          logicalId: "STYLE_GLOBAL_MAIN",
          digest: "keep emotion in gesture and pause",
        }),
        expect.objectContaining({
          key: "banned_rule",
          label: "Banned rule cluster",
          logicalId: "BAN_REUNION_V1",
          digest: "do not explain the whole backstory at reunion time",
        }),
        expect.objectContaining({
          key: "calibration_line",
          label: "Calibration line",
          logicalId: "CAL_002",
          digest: "the door closed like a sentence left unfinished",
        }),
        expect.objectContaining({
          key: "world_rule",
          label: "World rule",
          logicalId: "WR_GLOBAL_014",
          digest: "public spellcasting inside the city is forbidden",
        }),
        expect.objectContaining({
          key: "foreshadow",
          label: "Open foreshadow",
          logicalId: "F014",
          digest: "the old letter sender clue is now in play",
        }),
      ]),
    );
    expect(provenance.injections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ slot: "style_rules", slotLabel: "Style rules", digest: "keep emotion in gesture and pause" }),
        expect.objectContaining({ slot: "world_rules", slotLabel: "World rules", digest: "public spellcasting inside the city is forbidden" }),
        expect.objectContaining({ slot: "chapter_summary", slotLabel: "Chapter summary", digest: "chapter summary for the first reunion chapter" }),
      ]),
    );
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
    expect(source).toContain("focusTarget");
    expect(source).toContain("focused-card");
    expect(source).toContain('source_type: "scene_run_receipt"');
    expect(source).toContain("isFocusedRunReceipt");
    expect(source).toContain("Open Scene Card");
  });

  it("keeps populated workbench content visible ahead of the error-only branch", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source.indexOf('v-else-if="hasData"')).toBeLessThan(source.indexOf('v-else-if="workbench.error"'));
    expect(source).toContain('v-if="workbench.error" class="paper inline-error"');
  });

  it("renders human review context fields for recovery-generated events", () => {
    const source = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(source).toContain("object_ref");
    expect(source).toContain("details_json");
    expect(source).toContain("request_path_template");
    expect(source).toContain("created_by_ref");
  });

  it("renders human review action audit details for recovery-generated events", () => {
    const source = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(source).toContain("Last action");
    expect(source).toContain("last_action_at");
    expect(source).toContain("action_history");
    expect(source).toContain("linked_target_ref");
    expect(source).toContain("resolution_reason");
    expect(source).toContain("Recommended next step");
    expect(source).toContain("Open Linked Target");
    expect(source).toContain("Open Follow-up Target");
    expect(source).toContain("Open Replay Result");
    expect(source).toContain('$emit("open-target"');
    expect(source).toContain("item.linked_target");
    expect(source).toContain("item.followup_target");
    expect(source).toContain("item.replay_target");
    expect(source).toContain("source_type");
    expect(source).toContain('view_id: "index"');
  });
});

describe("review inbox source", () => {
  it("surfaces recovery-generated human review events inside the inbox", () => {
    const source = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const cardSource = readFileSync(new URL("../src/components/ReviewCard.vue", import.meta.url), "utf8");
    const drawerSource = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(source).toContain("System Recovery");
    expect(source).toContain("HumanReviewDrawer");
    expect(source).toContain("reviewInbox.systemRecoveryItems");
    expect(source).toContain("focusTarget");
    expect(source).toContain("const { activeView, focusTarget, openTarget } = useShellRouter()");
    expect(source).toContain('@open-target="handleOpenTarget"');
    expect(source).toContain("reviewSourceActionLabel");
    expect(source).toContain('if (nextView === "review" && previousView !== "review")');
    expect(source).toContain("refreshReviews()");
    expect(source).toContain('source_type: "review_approve"');
    expect(source).toContain('source_type: "review_release"');
    expect(source).toContain('source_type: "review_card_open"');
    expect(source).toContain("openTarget");
    expect(cardSource).toContain("highlighted");
    expect(cardSource).toContain("sourceActionLabel");
    expect(cardSource).toContain("Open In Index");
    expect(cardSource).toContain('$emit("open-target"');
    expect(drawerSource).toContain("focusEventId");
  });

  it("wires retry actions for recovery-generated human review events", () => {
    const viewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const drawerSource = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");
    const storeSource = readFileSync(new URL("../src/stores/reviewInbox.js", import.meta.url), "utf8");

    expect(viewSource).toContain("actOnHumanReviewEvent");
    expect(viewSource).toContain("recordRecoveryAction");
    expect(viewSource).toContain('@action="handleHumanReviewAction"');
    expect(drawerSource).toContain("retry_request");
    expect(drawerSource).toContain("retry_verify");
    expect(drawerSource).toContain("release_review");
    expect(drawerSource).toContain('$emit("action"');
    expect(storeSource).toContain('item.status !== "resolved"');
  });
});

describe("shell source", () => {
  it("persists an operator ref alongside the API base", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const apiSource = readFileSync(new URL("../src/lib/api.js", import.meta.url), "utf8");

    expect(source).toContain("Operator Ref");
    expect(source).toContain("setOperatorRef");
    expect(apiSource).toContain("X-Operator-Ref");
    expect(apiSource).toContain("getOperatorRef");
  });
});

describe("index console source", () => {
  it("wires due promotions into the index console panel", () => {
    const source = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");

    expect(source).toContain("Run Due Promotions");
    expect(source).toContain("indexConsole.runDuePromotions");
    expect(source).toContain("lastPromotionResult");
  });

  it("renders a recovery receipt alongside recovery sweep controls", () => {
    const source = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");

    expect(source).toContain("Recovery Sweep");
    expect(source).toContain("Recovery Receipt");
    expect(source).toContain("Recovery Follow-up");
    expect(source).toContain("System Activity");
    expect(source).toContain("Operator Activity");
    expect(source).toContain("Target Activity");
    expect(source).toContain("lastRecoveryResult");
    expect(source).toContain("lastRecoveryActionResult");
    expect(source).toContain("recoveryTimelineItems");
    expect(source).toContain("systemRuntimeTimelineItems");
    expect(source).toContain("operatorActionTimelineItems");
    expect(source).toContain("targetActivityGroups");
    expect(source).toContain("activity_items");
    expect(source).toContain("activity_count");
    expect(source).toContain("latest_at");
    expect(source).toContain("target_refs");
    expect(source).toContain("openTarget");
    expect(source).toContain("Open Linked Target");
    expect(source).toContain("Open Follow-up Target");
    expect(source).toContain("Open Replay Result");
    expect(source).toContain("linked_target");
    expect(source).toContain("followup_target");
    expect(source).toContain("replay_target");
    expect(source).toContain("actor_ref");
    expect(source).toContain("last_actor_ref");
    expect(source).toContain("lastRecoveryResult.actor_ref");
    expect(source).toContain("lastPromotionResult.actor_ref");
    expect(source).toContain("reclaimed_job_summaries");
    expect(source).toContain("failed_job_summaries");
    expect(source).toContain("reclaimed_idempotency_key_summaries");
    expect(source).toContain("created_human_review_event_ids");
    expect(source).toContain("created_human_review_event_targets");
    expect(source).toContain("promoted_review_targets");
    expect(source).toContain("Open Job");
    expect(source).toContain("Open Review");
    expect(source).toContain("Open Recovery Event");
    expect(source).toContain("status_before");
    expect(source).toContain("status_after");
    expect(source).toContain("expandedTargetRefs");
    expect(source).toContain("toggleTargetGroup");
    expect(source).toContain("isTargetGroupExpanded");
    expect(source).toContain("Show Activity");
    expect(source).toContain("Hide Activity");
    expect(source).toContain("focusedActivityKey");
    expect(source).toContain("orderedActivityItems");
    expect(source).toContain("focusedActivityKeyForGroup");
    expect(source).toContain("scrollIntoView");
    expect(source).toContain("Latest linked activity");
    expect(source).toContain("withSourceFocusTarget");
    expect(source).toContain("source_type");
    expect(source).toContain("source_id");
    expect(source).toContain("isFocusedRecoveryTimelineItem");
    expect(source).toContain("isFocusedSystemActivityItem");
    expect(source).toContain("isFocusedOperatorActionItem");
    expect(source).toContain("Source-linked activity");
  });

  it("renders job diagnostics and stale-fault summaries in the index console", () => {
    const viewSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const cardSource = readFileSync(new URL("../src/components/AliasScopeCard.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(viewSource).toContain("target_snapshot_version");
    expect(viewSource).toContain("target_embedding_version");
    expect(viewSource).toContain("lease_expires_at");
    expect(viewSource).toContain("error_text");
    expect(viewSource).toContain("focused-card");
    expect(cardSource).toContain("recent_fault_summary");
    expect(cardSource).toContain("collection_family");
    expect(cardSource).toContain("sample_query_success");
    expect(routerSource).toContain("focusTarget");
    expect(routerSource).toContain("openTarget");
    expect(routerSource).toContain("scene_card");
  });
});
