import { existsSync, readFileSync } from "node:fs";

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
        label: "声线档案",
        logicalId: "VOICE_CHAR_A",
        rowId: "voice_profile_VOICE_CHAR_A_v1",
        version: 1,
        digest: "short clipped lines; pressure makes the tone harder",
      },
      {
        key: "relation_profile",
        label: "关系档案",
        logicalId: "REL_CHAR_A_CHAR_B",
        rowId: "relation_profile_REL_CHAR_A_CHAR_B_v1",
        version: 1,
        digest: "reunion tension; B knows slightly more than A",
      },
      {
        key: "scene_memory_prev",
        label: "上一场景记忆",
        logicalId: "CH000_SC03",
        rowId: null,
        version: null,
        digest: "They last separated without resolving the letter",
      },
    ]);
    expect(provenance.injections[2]).toEqual({
      slot: "pov_voice",
      slotLabel: "视角声线",
      refId: "VOICE_CHAR_A",
      digestKey: "voice_card",
      digest: "short clipped lines; pressure makes the tone harder",
    });
    expect(provenance.injections[4]).toEqual({
      slot: "prev_scene_memory",
      slotLabel: "上一场景记忆",
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
        style_profile_contract: "STYLE_FEATURE_CONTRACT_v1",
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
        { slot: "style_profile", ref_id: "STYLE_FEATURE_CONTRACT_v1", digest_key: "style_profile" },
        { slot: "banned_rules", ref_id: "BAN_REUNION_V1", digest_key: "banned_rule" },
        { slot: "calibration_lines", ref_id: "CAL_002", digest_key: "calibration_line" },
        { slot: "world_rules", ref_id: "WR_GLOBAL_014", digest_key: "world_rule" },
        { slot: "foreshadow", ref_id: "F014", digest_key: "foreshadow" },
        { slot: "scene_summary", ref_id: "CH001_SC01", digest_key: "scene_summary" },
        { slot: "chapter_summary", ref_id: "CH001", digest_key: "chapter_summary" },
      ],
      inline_digests: {
        style_rule: "keep emotion in gesture and pause",
        style_profile: '{"features":{"rhythm":{"guidance":["pause before reveal"]}}}',
        banned_rule: "do not explain the whole backstory at reunion time",
        calibration_line: "the door closed like a sentence left unfinished",
        world_rule: "public spellcasting inside the city is forbidden",
        foreshadow: "the old letter sender clue is now in play",
        scene_summary: "scene summary for the first reunion beat",
        chapter_summary: "chapter summary for the first reunion chapter",
      },
    };

    const provenance = buildBundleProvenance(snapshot);

    expect(provenance.styleProfile).toEqual({
      contractVersion: "STYLE_FEATURE_CONTRACT_v1",
      featureRows: [
        {
          name: "rhythm",
          guidance: ["pause before reveal"],
        },
      ],
      calibrationLines: [],
      bannedMoves: [],
      raw: '{"features":{"rhythm":{"guidance":["pause before reveal"]}}}',
    });
    expect(provenance.sources).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "style_rule",
          label: "风格规则集",
          logicalId: "STYLE_GLOBAL_MAIN",
          digest: "keep emotion in gesture and pause",
        }),
        expect.objectContaining({
          key: "style_profile",
          label: "风格画像契约",
          logicalId: "STYLE_FEATURE_CONTRACT_v1",
          digest: '{"features":{"rhythm":{"guidance":["pause before reveal"]}}}',
        }),
        expect.objectContaining({
          key: "banned_rule",
          label: "禁忌规则簇",
          logicalId: "BAN_REUNION_V1",
          digest: "do not explain the whole backstory at reunion time",
        }),
        expect.objectContaining({
          key: "calibration_line",
          label: "校准句",
          logicalId: "CAL_002",
          digest: "the door closed like a sentence left unfinished",
        }),
        expect.objectContaining({
          key: "world_rule",
          label: "世界规则",
          logicalId: "WR_GLOBAL_014",
          digest: "public spellcasting inside the city is forbidden",
        }),
        expect.objectContaining({
          key: "foreshadow",
          label: "开放伏笔",
          logicalId: "F014",
          digest: "the old letter sender clue is now in play",
        }),
      ]),
    );
    expect(provenance.injections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ slot: "style_rules", slotLabel: "风格规则", digest: "keep emotion in gesture and pause" }),
        expect.objectContaining({ slot: "style_profile", slotLabel: "风格画像契约", digest: '{"features":{"rhythm":{"guidance":["pause before reveal"]}}}' }),
        expect.objectContaining({ slot: "world_rules", slotLabel: "世界规则", digest: "public spellcasting inside the city is forbidden" }),
        expect.objectContaining({ slot: "chapter_summary", slotLabel: "章节摘要", digest: "chapter summary for the first reunion chapter" }),
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

    expect(source).toContain("运行完整场景");
    expect(source).toContain("workbench.runScene");
    expect(source).toContain("lastRunResult");
    expect(source).toContain("focusTarget");
    expect(source).toContain("focused-card");
    expect(source).toContain('source_type: "scene_run_receipt"');
    expect(source).toContain("isFocusedRunReceipt");
    expect(source).toContain("打开场景卡片");
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

    expect(source).toContain("last_action_at");
    expect(source).toContain("action_history");
    expect(source).toContain("linked_target_ref");
    expect(source).toContain("resolution_reason");
    expect(source).toContain("toggleDetails");
    expect(source).toContain("toggleHistory");
    expect(source).toContain('defineEmits(["action", "open-target"])');
    expect(source).toContain("emit('open-target'");
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

    expect(source).toContain("HumanReviewDrawer");
    expect(source).toContain("reviewInbox.systemRecoveryItems");
    expect(source).toContain("focusTarget");
    expect(source).toContain("const shellRouter = useShellRouter();");
    expect(source).toContain("const { activeView, focusTarget, openTarget, clearFocus, pendingFocusView, settleFocusView } = shellRouter;");
    expect(source).toContain('@open-target="handleOpenTarget"');
    expect(source).toContain("reviewSourceActionLabel");
    expect(source).toContain("onActivated(() => {");
    expect(source).toContain("ensureReviewInboxLoaded()");
    expect(source).toContain("markDependentViewsStale");
    expect(source).toContain('source_type: "review_approve"');
    expect(source).toContain('source_type: "review_release"');
    expect(source).toContain('source_type: "review_card_open"');
    expect(source).toContain("openTarget");
    expect(cardSource).toContain("highlighted");
    expect(cardSource).toContain("sourceActionLabel");
    expect(cardSource).toContain("review-toggle-payload");
    expect(cardSource).toContain('defineEmits(["approve", "release", "open-target"])');
    expect(cardSource).toContain("payloadExpanded");
    expect(drawerSource).toContain("focusEventId");
  });

  it("wires retry actions for recovery-generated human review events", () => {
    const viewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const drawerSource = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");
    const storeSource = readFileSync(new URL("../src/stores/reviewInbox.js", import.meta.url), "utf8");

    expect(viewSource).toContain("actOnHumanReviewEvent");
    expect(viewSource).toContain("recordRecoveryAction");
    expect(viewSource).toContain('@action="handleHumanReviewAction"');
    expect(viewSource).toContain("markDependentViewsStale");
    expect(viewSource).not.toContain("indexConsole.load()");
    expect(drawerSource).not.toContain("formatAction");
    expect(drawerSource).toContain("allowed_actions_json");
    expect(drawerSource).toContain("emit('action'");
    expect(storeSource).toContain('item.status !== "resolved"');
  });
});

describe("shell source", () => {
  it("persists an operator ref alongside the API base", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const configSource = readFileSync(new URL("../src/views/SystemConfigView.vue", import.meta.url), "utf8");
    const apiSource = readFileSync(new URL("../src/lib/api.js", import.meta.url), "utf8");

    expect(source).not.toContain("操作员标识");
    expect(source).not.toContain("setOperatorRef");
    expect(configSource).toContain("操作员标识");
    expect(configSource).toContain("updateOperatorRef");
    expect(apiSource).toContain("X-Operator-Ref");
    expect(apiSource).toContain("getOperatorRef");
  });
});

describe("index console source", () => {
  it("wires due promotions into the index console panel", () => {
    const source = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");

    expect(source).toContain("运行到期发布");
    expect(source).toContain("indexConsole.runDuePromotions");
    expect(source).toContain("lastPromotionResult");
  });

  it("renders a recovery receipt alongside recovery sweep controls", () => {
    const viewSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const groupCardSource = readFileSync(new URL("../src/components/TargetActivityGroupCard.vue", import.meta.url), "utf8");

    expect(viewSource).toContain("lastRecoveryResult");
    expect(viewSource).toContain("lastRecoveryActionResult");
    expect(viewSource).toContain("recoveryTimelineItems");
    expect(viewSource).toContain("systemRuntimeTimelineItems");
    expect(viewSource).toContain("operatorActionTimelineItems");
    expect(viewSource).toContain("targetActivityGroups");
    expect(viewSource).toContain("openTarget");
    expect(viewSource).toContain("linked_target");
    expect(viewSource).toContain("followup_target");
    expect(viewSource).toContain("replay_target");
    expect(viewSource).toContain("actor_ref");
    expect(viewSource).toContain("last_actor_ref");
    expect(viewSource).toContain("lastRecoveryResult.actor_ref");
    expect(viewSource).toContain("lastPromotionResult.actor_ref");
    expect(viewSource).toContain("lastRecoveryResult.reclaimed_jobs");
    expect(viewSource).toContain("lastRecoveryResult.failed_jobs");
    expect(viewSource).toContain("lastRecoveryResult.created_human_review_events");
    expect(viewSource).toContain("created_human_review_event_targets");
    expect(viewSource).toContain("promoted_review_targets");
    expect(viewSource).toContain("status_before");
    expect(viewSource).toContain("status_after");
    expect(viewSource).toContain("TargetActivityGroupCard");
    expect(viewSource).toContain("activeTargetGroupRef");
    expect(viewSource).toContain("toggleTargetGroup");
    expect(viewSource).toContain("focusedActivityKey");
    expect(viewSource).toContain("sourceLinkedActivityKey");
    expect(viewSource).toContain("scrollIntoView");
    expect(viewSource).toContain("withIndexFocusTarget");
    expect(viewSource).toContain("isFocusedSource");
    expect(viewSource).toContain("source_type");
    expect(viewSource).toContain("source_id");
    expect(viewSource).toContain("ensureTargetGroupItemsLoaded");
    expect(groupCardSource).toContain("activity_count");
    expect(groupCardSource).toContain("latest_at");
    expect(groupCardSource).toContain("target_refs");
    expect(groupCardSource).toContain("focused-activity-item");
    expect(groupCardSource).toContain("sourceLinkedActivityKey");
    expect(groupCardSource).toContain('defineEmits(["toggle", "open-target", "previous", "next"])');
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

describe("interop center source", () => {
  it("wires preview, import, export, replay, and diff panels into the interop center", () => {
    const viewPath = new URL("../src/views/InteropCenterView.vue", import.meta.url);

    expect(existsSync(viewPath)).toBe(true);

    if (!existsSync(viewPath)) {
      return;
    }

    const source = readFileSync(viewPath, "utf8");

    expect(source).toContain("worksheet_yaml");
    expect(source).toContain("预览工作表");
    expect(source).toContain("导入工作表");
    expect(source).toContain("包导出与回放");
    expect(source).toContain("回放终稿场景");
    expect(source).toContain("版本偏差");
    expect(source).toContain("文本偏差");
    expect(source).toContain("source_ref_comparisons");
  });
});
