import { readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { actOnHumanReviewEvent, setOperatorRef } from "../src/lib/api";
import { useShellRouter } from "../src/router";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useKnowledgeConsoleStore } from "../src/stores/knowledgeConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";
import { useWorkbenchStore } from "../src/stores/workbench";

describe("workbench store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          scene_card: { scene_id: "CH001_SC01" },
          scene_run_state: { scene_status: "ready" },
          bundle: { bundle_id: "bundle_CH001_SC01" },
          attempts: [],
        },
      }),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads a scene workbench payload from the API envelope", async () => {
    const store = useWorkbenchStore();

    await store.load("CH001_SC01");

    expect(store.sceneId).toBe("CH001_SC01");
    expect(store.data.scene_card.scene_id).toBe("CH001_SC01");
  });

  it("runs a full scene and refreshes the workbench state", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/run/full")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_status: "archived",
              current_bundle_id: "bundle_CH001_SC01",
              current_bundle_hash: "hash_123",
              current_final_scene_row_id: "final_scene_CH001_SC01",
            },
          }),
        };
      }

      if (url.includes("/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_card: { scene_id: "CH001_SC01" },
              scene_run_state: { scene_status: "archived" },
              bundle: { bundle_id: "bundle_CH001_SC01" },
              attempts: [],
            },
          }),
        };
      }

      if (url.includes("/human-review-events")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    const message = await store.runScene("CH001_SC01");

    expect(message).toContain("CH001_SC01");
    expect(store.lastRunResult.current_final_scene_row_id).toBe("final_scene_CH001_SC01");
    expect(store.data.scene_run_state.scene_status).toBe("archived");
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
  });

  it("keeps the current scene context when a run request fails", async () => {
    const store = useWorkbenchStore();
    store.sceneId = "CH001_SC01";
    store.data = {
      scene_card: { scene_id: "CH001_SC01" },
      scene_run_state: { scene_status: "ready" },
      bundle: { bundle_id: "bundle_CH001_SC01" },
      attempts: [],
    };

    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/run/full")) {
        return {
          ok: false,
          json: async () => ({
            ok: false,
            error: { message: "Scene pipeline failed" },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    await expect(store.runScene("CH001_SC02")).rejects.toThrow("Scene pipeline failed");

    expect(store.sceneId).toBe("CH001_SC01");
    expect(store.data.scene_card.scene_id).toBe("CH001_SC01");
    expect(store.error).toBe("Scene pipeline failed");
    expect(store.actionId).toBe("");
    expect(store.lastRunResult).toBeNull();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("vue shell", () => {
  it("renders the three required views from the Vue shell", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

    expect(source).toContain("Scene Workbench");
    expect(source).toContain("Review Inbox");
    expect(source).toContain("Index Console");
    expect(source).toContain("Knowledge Console");
  });
});

describe("shell router", () => {
  it("opens a runtime target in the matching view and keeps focus", () => {
    const router = useShellRouter();

    router.reset();
    router.openTarget({
      target_type: "review_item",
      target_id: "review_style_pending",
      target_ref: "review_item:review_style_pending",
    });

    expect(router.activeView.value).toBe("review");
    expect(router.focusTarget.value).toEqual({
      target_type: "review_item",
      target_id: "review_style_pending",
      target_ref: "review_item:review_style_pending",
      source_type: null,
      source_id: null,
    });

    router.openTarget({
      target_type: "verify_job",
      target_id: "verify_review_style_pending",
      target_ref: "verify_job:verify_review_style_pending",
    });

    expect(router.activeView.value).toBe("index");
    expect(router.focusTarget.value).toEqual({
      target_type: "verify_job",
      target_id: "verify_review_style_pending",
      target_ref: "verify_job:verify_review_style_pending",
      source_type: null,
      source_id: null,
    });

    router.openTarget({
      target_type: "scene_card",
      target_id: "CH001_SC02",
      target_ref: "scene_card:CH001_SC02",
    });

    expect(router.activeView.value).toBe("workbench");
    expect(router.focusTarget.value).toEqual({
      target_type: "scene_card",
      target_id: "CH001_SC02",
      target_ref: "scene_card:CH001_SC02",
      source_type: null,
      source_id: null,
    });
  });

  it("keeps source context when a jump should stay inside the index console", () => {
    const router = useShellRouter();

    router.reset();
    router.openTarget(
      {
        target_type: "review_item",
        target_id: "review_style_released",
        target_ref: "review_item:review_style_released",
      },
      {
        view_id: "index",
        source_type: "system_activity",
        source_id: 12,
      },
    );

    expect(router.activeView.value).toBe("index");
    expect(router.focusTarget.value).toEqual({
      target_type: "review_item",
      target_id: "review_style_released",
      target_ref: "review_item:review_style_released",
      source_type: "system_activity",
      source_id: 12,
    });
  });
});

describe("api helpers", () => {
  const originalWindow = globalThis.window;

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  });

  it("includes the persisted operator ref in human review action requests", async () => {
    const storage = new Map();
    globalThis.window = {
      localStorage: {
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
      },
    };
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          event_id: "human_review_idempotency_recovery_approve-review-stale",
          action: "retry_request",
          status: "resolved",
        },
      }),
    });

    setOperatorRef("ops.duwei");
    await actOnHumanReviewEvent("human_review_idempotency_recovery_approve-review-stale", "retry_request");

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/human-review-events/human_review_idempotency_recovery_approve-review-stale/actions",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-Operator-Ref": "ops.duwei",
        }),
      }),
    );
  });
});

describe("review inbox store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    let recoveryStatus = "open";
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/review-items")) {
        if (url.includes("/approve")) {
          return {
            ok: true,
            json: async () => ({
              ok: true,
              data: {
                review_id: "review_style_pending",
                actor_ref: "ops.duwei",
              },
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  review_id: "review_style_pending",
                  candidate_text: "pending review",
                  materialize_status: "pending",
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/human-review-events/") && url.includes("/actions")) {
        recoveryStatus = "resolved";
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              event_id: "human_review_idempotency_recovery_approve-review-stale",
              action: "retry_request",
              status: "resolved",
              linked_target_ref: "review_item:review_style_pending",
              resolution_reason: "review action replay reached a terminal state",
              replay_result: {
                review_id: "review_style_pending",
                materialize_status: "succeeded",
              },
            },
          }),
        };
      }

      if (url.includes("/human-review-events")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_idempotency_recovery_approve-review-stale",
                  event_source: "idempotency_recovery",
                  object_ref: "approve-review-stale",
                  status: recoveryStatus,
                },
                {
                  event_id: "human_review_manual_scene",
                  event_source: "manual_scene_review",
                  object_ref: "CH001_SC01",
                  status: "open",
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads review items and groups recovery-generated human review events", async () => {
    const store = useReviewInboxStore();

    await store.load();

    expect(store.items).toHaveLength(1);
    expect(store.systemRecoveryItems).toEqual([
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_approve-review-stale",
        event_source: "idempotency_recovery",
      }),
    ]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("includes the operator ref in ordinary review approval notices", async () => {
    const store = useReviewInboxStore();

    const message = await store.approve("review_style_pending");

    expect(message).toContain("Approved review_style_pending");
    expect(message).toContain("ops.duwei");
  });

  it("retries a recovery event request and refreshes the inbox state", async () => {
    const store = useReviewInboxStore();

    const message = await store.actOnHumanReviewEvent(
      "human_review_idempotency_recovery_approve-review-stale",
      "retry_request",
    );

    expect(message).toContain("retry_request");
    expect(message).toContain("resolved");
    expect(store.systemRecoveryItems).toHaveLength(0);
    expect(store.lastActionResult).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_approve-review-stale",
        status: "resolved",
      }),
    );
    expect(store.actionId).toBe("");
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
  });
});

describe("knowledge console store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/api/v1/knowledge/voice_card/VOICE_CHAR_A")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              object_type: "voice_card",
              lineage_key: "VOICE_CHAR_A",
              active_version: {
                row_id: "voice_card_VOICE_CHAR_A_v1",
                version: 1,
                text: "short clipped lines; pressure makes the tone harder",
              },
              candidate_version: {
                review_id: "review_voice_card_candidate",
                text: "candidate voice update",
              },
              versions: [
                {
                  row_id: "voice_card_VOICE_CHAR_A_v1",
                  version: 1,
                  text: "short clipped lines; pressure makes the tone harder",
                },
              ],
              runtime_refs: {
                mode: "direct_read",
              },
              review_refs: ["review_voice_card_candidate"],
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  object_type: "voice_card",
                  lineage_key: "VOICE_CHAR_A",
                  status: "active",
                  active_version: {
                    row_id: "voice_card_VOICE_CHAR_A_v1",
                    version: 1,
                    text: "short clipped lines; pressure makes the tone harder",
                  },
                  candidate_version: null,
                  versions: [
                    {
                      row_id: "voice_card_VOICE_CHAR_A_v1",
                      version: 1,
                      text: "short clipped lines; pressure makes the tone harder",
                    },
                  ],
                  runtime_refs: {
                    mode: "direct_read",
                  },
                  review_refs: [],
                },
              ],
              supported_object_types: ["voice_card", "style_rule", "calibration_line"],
            },
          }),
        };
      }

      if (url.includes("/api/v1/review-items") && options.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_voice_card_candidate",
              item_type: "voice_card_candidate",
              candidate_text: "candidate voice update",
              candidate_payload_json: {
                lineage_key: "VOICE_CHAR_A",
                character_id: "CHAR_A",
                text: "candidate voice update",
              },
              status: "pending",
              target_collection: "voice_cards",
            },
          }),
        };
      }

      if (url.includes("/api/v1/review-items")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  review_id: "review_voice_card_candidate",
                  item_type: "voice_card_candidate",
                  candidate_text: "candidate voice update",
                  candidate_payload_json: {
                    lineage_key: "VOICE_CHAR_A",
                    character_id: "CHAR_A",
                    text: "candidate voice update",
                  },
                  status: "pending",
                  materialize_status: "pending",
                  target_collection: "voice_cards",
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("merges pending review candidates into the knowledge catalog and loads detail", async () => {
    const store = useKnowledgeConsoleStore();

    await store.load();
    await store.selectItem("voice_card", "VOICE_CHAR_A");

    expect(store.items).toEqual([
      expect.objectContaining({
        object_type: "voice_card",
        lineage_key: "VOICE_CHAR_A",
        candidate_version: expect.objectContaining({
          review_id: "review_voice_card_candidate",
          text: "candidate voice update",
        }),
      }),
    ]);
    expect(store.detail).toEqual(
      expect.objectContaining({
        object_type: "voice_card",
        lineage_key: "VOICE_CHAR_A",
        runtime_refs: expect.objectContaining({
          mode: "direct_read",
        }),
      }),
    );
  });

  it("creates a candidate review item from the knowledge console form", async () => {
    const store = useKnowledgeConsoleStore();

    const message = await store.createCandidate({
      reviewId: "review_voice_card_candidate",
      itemType: "voice_card_candidate",
      lineageKey: "VOICE_CHAR_A",
      candidateText: "candidate voice update",
      characterId: "CHAR_A",
      activeOnApprove: 0,
    });

    expect(message).toContain("review_voice_card_candidate");
    expect(store.lastCreateResult).toEqual(
      expect.objectContaining({
        review_id: "review_voice_card_candidate",
        target_collection: "voice_cards",
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/review-items",
      expect.objectContaining({
        method: "POST",
      }),
    );
  });
});

describe("index console store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/runtime/recovery/sweep")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              reclaimed_jobs: 1,
              reclaimed_job_summaries: [
                {
                  job_id: "verify_job_reclaimable",
                  job_type: "verify",
                  alias_scope: "style_observation:global:global",
                  previous_worker_id: "verify-worker-stale",
                  attempt_no: 2,
                  previous_lease_expires_at: "2000-01-01T00:00:00+00:00",
                },
              ],
              failed_jobs: 1,
              failed_job_summaries: [
                {
                  job_id: "verify_job_failed_recent",
                  job_type: "verify",
                  alias_scope: "style_observation:global:global",
                  error_text: "candidate alias verify failed",
                  finished_at: "2026-04-09T16:05:00+00:00",
                },
              ],
              reclaimed_idempotency_keys: 1,
              failed_idempotency_keys: 1,
              reclaimed_idempotency_key_summaries: [
                {
                  idempotency_key: "approve-review-stale",
                  previous_worker_id: "http",
                  attempt_no: 2,
                  previous_lease_expires_at: "2000-01-01T00:00:00+00:00",
                },
              ],
              created_human_review_events: 1,
              created_human_review_event_ids: [
                "human_review_idempotency_recovery_approve-review-stale",
              ],
              actor_ref: "ops.duwei",
            },
          }),
        };
      }

      if (url.includes("/runtime/promotions/run-due")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              promoted: 1,
              promoted_review_ids: ["review_style_due_promotion"],
              promoted_alias_scopes: ["style_observation:global:global"],
              actor_ref: "ops.duwei",
            },
          }),
        };
      }

      if (url.includes("/index/alias-scopes")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  alias_scope: "style_observation:global:global",
                  active_alias: "style_observation_global_global_candidate_v1",
                  candidate_alias: null,
                  verify_status: "succeeded",
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/index/jobs")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }

      if (url.includes("/index/runtime-ledger")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              latest_recovery_action_receipt: {
                event_id: "human_review_idempotency_recovery_release-review-stale",
                event_source: "idempotency_recovery",
                status: "resolved",
                action: "release_review",
                action_at: "2026-04-10T01:35:00+00:00",
                actor_ref: "ops.duwei",
                linked_target_ref: "review_item:review_style_released",
                resolution_reason: "review released and active alias promoted",
                followup_action: null,
                followup_target_ref: null,
                replay_result: {
                  review_id: "review_style_released",
                  released: true,
                },
                replay_target: {
                  target_type: "review_item",
                  target_id: "review_style_released",
                  target_ref: "review_item:review_style_released",
                },
              },
              recovery_timeline_items: [
                {
                  event_id: "human_review_idempotency_recovery_approve-review-stale",
                  event_source: "idempotency_recovery",
                  status: "needs_followup",
                  last_action: "retry_request",
                  last_action_at: "2026-04-10T01:30:00+00:00",
                  last_actor_ref: "ops.duwei",
                  linked_target_ref: "review_item:review_style_pending",
                  resolution_reason: "review approved; verify job is ready to run",
                  followup_action: "retry_verify",
                  followup_target_ref: "verify_job:verify_review_style_pending",
                  default_action: "retry_verify",
                  details_json: {
                    linked_target_ref: "review_item:review_style_pending",
                    resolution_reason: "review approved; verify job is ready to run",
                    last_action: "retry_request",
                    last_action_at: "2026-04-10T01:30:00+00:00",
                  },
                },
                {
                  event_id: "human_review_idempotency_recovery_release-review-stale",
                  event_source: "idempotency_recovery",
                  status: "resolved",
                  last_action: "release_review",
                  last_action_at: "2026-04-10T01:35:00+00:00",
                  last_actor_ref: "ops.duwei",
                  linked_target_ref: "review_item:review_style_released",
                  resolution_reason: "review released and active alias promoted",
                  default_action: "inspect",
                  replay_target: {
                    target_type: "review_item",
                    target_id: "review_style_released",
                    target_ref: "review_item:review_style_released",
                  },
                  details_json: {
                    linked_target_ref: "review_item:review_style_released",
                    resolution_reason: "review released and active alias promoted",
                    last_action: "release_review",
                    last_action_at: "2026-04-10T01:35:00+00:00",
                  },
                },
              ],
              system_runtime_timeline_items: [
                {
                  operation_id: 12,
                  event_type: "runtime_due_promotion",
                  object_ref: "style_observation_STY_RELEASED_v1",
                  actor_ref: "system/due_promotion",
                  summary: "promoted verified future-effective candidate",
                  created_at: "2026-04-10T01:40:00+00:00",
                  target_refs: [
                    {
                      target_type: "review_item",
                      target_id: "review_style_released",
                      target_ref: "review_item:review_style_released",
                    },
                  ],
                  payload_json: {
                    actor_ref: "system/due_promotion",
                    review_id: "review_style_released",
                  },
                },
                {
                  operation_id: 11,
                  event_type: "runtime_job_reclaimed",
                  object_ref: "verify_job_reclaimable",
                  actor_ref: "system/recovery_sweep",
                  summary: "reclaimed stale verify lease",
                  created_at: "2026-04-10T01:20:00+00:00",
                  target_refs: [
                    {
                      target_type: "verify_job",
                      target_id: "verify_job_reclaimable",
                      target_ref: "verify_job:verify_job_reclaimable",
                    },
                  ],
                  payload_json: {
                    actor_ref: "system/recovery_sweep",
                    job_id: "verify_job_reclaimable",
                  },
                },
              ],
              operator_action_timeline_items: [
                {
                  operation_id: 13,
                  event_type: "human_review_action",
                  event_id: "human_review_idempotency_recovery_approve-review-stale",
                  object_ref: "human_review_idempotency_recovery_approve-review-stale",
                  actor_ref: "ops.duwei",
                  action: "retry_verify",
                  status_before: "needs_followup",
                  status_after: "needs_followup",
                  resolution_reason: "verify succeeded but review still awaits manual release",
                  created_at: "2026-04-10T01:32:00+00:00",
                  target_refs: [
                    {
                      target_type: "human_review_event",
                      target_id: "human_review_idempotency_recovery_approve-review-stale",
                      target_ref: "human_review_event:human_review_idempotency_recovery_approve-review-stale",
                    },
                    {
                      target_type: "review_item",
                      target_id: "review_style_pending",
                      target_ref: "review_item:review_style_pending",
                    },
                    {
                      target_type: "verify_job",
                      target_id: "verify_review_style_pending",
                      target_ref: "verify_job:verify_review_style_pending",
                    },
                  ],
                  payload_json: {
                    actor_ref: "ops.duwei",
                    action: "retry_verify",
                  },
                },
              ],
              target_activity_groups: [
                {
                  target: {
                    target_type: "review_item",
                    target_id: "review_style_released",
                    target_ref: "review_item:review_style_released",
                  },
                  latest_at: "2026-04-10T01:40:00+00:00",
                  activity_count: 2,
                  sources: ["system_runtime", "recovery_timeline"],
                  activity_items: [
                    {
                      activity_key: "system_runtime:12",
                      source: "system_runtime",
                      timestamp: "2026-04-10T01:40:00+00:00",
                      actor_ref: "system/due_promotion",
                      label: "runtime_due_promotion",
                      status: null,
                      summary: "promoted verified future-effective candidate",
                      object_ref: "style_observation_STY_RELEASED_v1",
                      target_refs: [
                        {
                          target_type: "review_item",
                          target_id: "review_style_released",
                          target_ref: "review_item:review_style_released",
                        },
                      ],
                    },
                    {
                      activity_key: "recovery_timeline:human_review_idempotency_recovery_release-review-stale",
                      source: "recovery_timeline",
                      timestamp: "2026-04-10T01:35:00+00:00",
                      actor_ref: "ops.duwei",
                      label: "release_review",
                      status: "resolved",
                      summary: "review released and active alias promoted",
                      object_ref: "release-review-stale",
                      target_refs: [
                        {
                          target_type: "review_item",
                          target_id: "review_style_released",
                          target_ref: "review_item:review_style_released",
                        },
                      ],
                    },
                  ],
                },
                {
                  target: {
                    target_type: "review_item",
                    target_id: "review_style_pending",
                    target_ref: "review_item:review_style_pending",
                  },
                  latest_at: "2026-04-10T01:32:00+00:00",
                  activity_count: 2,
                  sources: ["operator_action", "recovery_timeline"],
                  activity_items: [],
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("runs due promotions and refreshes the index console state", async () => {
    const store = useIndexConsoleStore();

    const message = await store.runDuePromotions();

    expect(message).toContain("1");
    expect(message).toContain("ops.duwei");
    expect(store.lastPromotionResult.promoted).toBe(1);
    expect(store.lastPromotionResult.actor_ref).toBe("ops.duwei");
    expect(store.aliasScopes).toHaveLength(1);
    expect(store.recoveryTimelineItems).toHaveLength(2);
    expect(store.systemRuntimeTimelineItems).toHaveLength(2);
    expect(store.operatorActionTimelineItems).toHaveLength(1);
    expect(store.targetActivityGroups).toHaveLength(2);
    expect(store.targetActivityGroups[0]).toEqual(
      expect.objectContaining({
        target: expect.objectContaining({
          target_type: "review_item",
          target_id: "review_style_released",
        }),
        activity_count: 2,
      }),
    );
    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        action: "release_review",
        status: "resolved",
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledTimes(4);
  });

  it("runs recovery sweep, keeps the latest receipt, and refreshes the index console state", async () => {
    const store = useIndexConsoleStore();

    const message = await store.runRecovery();

    expect(message).toContain("recovery sweep");
    expect(message).toContain("ops.duwei");
    expect(store.lastRecoveryResult.reclaimed_jobs).toBe(1);
    expect(store.lastRecoveryResult.actor_ref).toBe("ops.duwei");
    expect(store.lastRecoveryResult.failed_job_summaries).toHaveLength(1);
    expect(store.lastRecoveryResult.failed_job_summaries[0].job_id).toBe("verify_job_failed_recent");
    expect(store.lastRecoveryResult.reclaimed_idempotency_key_summaries).toHaveLength(1);
    expect(store.lastRecoveryResult.created_human_review_event_ids).toEqual([
      "human_review_idempotency_recovery_approve-review-stale",
    ]);
    expect(store.aliasScopes).toHaveLength(1);
    expect(store.recoveryTimelineItems[0]).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_release-review-stale",
        status: "resolved",
      }),
    );
    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_release-review-stale",
        action: "release_review",
        replay_target: expect.objectContaining({
          target_type: "review_item",
          target_id: "review_style_released",
        }),
      }),
    );
    expect(store.systemRuntimeTimelineItems[0]).toEqual(
      expect.objectContaining({
        event_type: "runtime_due_promotion",
        actor_ref: "system/due_promotion",
        target_refs: [
          expect.objectContaining({
            target_type: "review_item",
            target_id: "review_style_released",
          }),
        ],
      }),
    );
    expect(store.operatorActionTimelineItems[0]).toEqual(
      expect.objectContaining({
        action: "retry_verify",
        actor_ref: "ops.duwei",
        target_refs: expect.arrayContaining([
          expect.objectContaining({
            target_type: "verify_job",
            target_id: "verify_review_style_pending",
          }),
        ]),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledTimes(4);
  });

  it("rehydrates the latest recovery follow-up receipt from the backend runtime ledger", async () => {
    const store = useIndexConsoleStore();

    await store.load();

    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_release-review-stale",
        action: "release_review",
        actor_ref: "ops.duwei",
        linked_target_ref: "review_item:review_style_released",
        replay_target: expect.objectContaining({
          target_type: "review_item",
          target_id: "review_style_released",
        }),
      }),
    );
    expect(store.recoveryTimelineItems).toHaveLength(2);
    expect(store.systemRuntimeTimelineItems).toHaveLength(2);
    expect(store.operatorActionTimelineItems).toHaveLength(1);
    expect(store.targetActivityGroups).toHaveLength(2);
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
  });

  it("records the latest recovery follow-up action receipt", () => {
    const store = useIndexConsoleStore();

    store.recordRecoveryAction({
      event_id: "human_review_idempotency_recovery_approve-review-stale",
      action: "retry_verify",
      status: "needs_followup",
      resolution_reason: "verify succeeded but review still awaits manual release",
      followup_action: "release_review",
      followup_target_ref: "review_item:review_style_pending",
      replay_target: {
        target_type: "verify_job",
        target_id: "verify_review_style_pending",
        target_ref: "verify_job:verify_review_style_pending",
      },
    });

    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        action: "retry_verify",
        followup_action: "release_review",
        replay_target: expect.objectContaining({
          target_type: "verify_job",
          target_id: "verify_review_style_pending",
        }),
      }),
    );
  });

  it("includes the operator ref in verify retry notices", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/index/verify/verify_job_actor/retry")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              job_id: "verify_job_actor",
              status: "succeeded",
              actor_ref: "ops.duwei",
            },
          }),
        };
      }
      if (url.includes("/index/alias-scopes")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }
      if (url.includes("/index/jobs")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }
      if (url.includes("/index/runtime-ledger")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              latest_recovery_action_receipt: null,
              recovery_timeline_items: [],
            },
          }),
        };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    const store = useIndexConsoleStore();

    const message = await store.retryVerifyJob("verify_job_actor");

    expect(message).toContain("verify_job_actor");
    expect(message).toContain("ops.duwei");
  });
});
