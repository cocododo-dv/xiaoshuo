import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchActivityEvents,
  fetchJobs,
  fetchKnowledgeEntries,
  fetchKnowledgeEntryDetail,
  fetchKnowledgeEntryWorkflow,
  fetchTargetActivityGroups,
  fetchVectorAliasScopes,
} from "../src/lib/api";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useKnowledgeConsoleStore } from "../src/stores/knowledgeConsole";

describe("domain api helpers", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { items: [], supported_object_types: [] } }),
    });
  });

  it("serializes shared domain query urls", async () => {
    await fetchKnowledgeEntries({
      objectType: "style_rule",
      scope: "global",
      scopeRefId: "global",
      status: "candidate",
    });
    await fetchKnowledgeEntryDetail("style_rule", "STYLE_DOMAIN_PENDING");
    await fetchKnowledgeEntryWorkflow("style_rule", "STYLE_DOMAIN_PENDING");
    await fetchVectorAliasScopes({
      objectType: "style_observation",
      scope: "global",
      scopeRefId: "global",
      verifyStatus: "succeeded",
    });
    await fetchJobs({
      jobType: "verify",
      status: "failed",
      reviewId: "review_scene_pending",
      aliasScope: "style_observation:global:global",
    });
    await fetchActivityEvents({
      stream: "operator_action",
      targetRef: "review_item:review_scene_pending",
      actorRef: "ops.duwei",
    });
    await fetchTargetActivityGroups({
      targetRef: "review_item:review_scene_pending",
      source: "operator_action",
      actorRef: "ops.duwei",
    });

    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/v1/knowledge-entries?object_type=style_rule&scope=global&scope_ref_id=global&status=candidate",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/knowledge-entries/style_rule/STYLE_DOMAIN_PENDING",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8000/api/v1/knowledge-entries/style_rule/STYLE_DOMAIN_PENDING/workflow",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      4,
      "http://127.0.0.1:8000/api/v1/vector-alias-scopes?object_type=style_observation&scope=global&scope_ref_id=global&verify_status=succeeded",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      5,
      "http://127.0.0.1:8000/api/v1/jobs?job_type=verify&status=failed&review_id=review_scene_pending&alias_scope=style_observation%3Aglobal%3Aglobal",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      6,
      "http://127.0.0.1:8000/api/v1/activity-events?stream=operator_action&target_ref=review_item%3Areview_scene_pending&actor_ref=ops.duwei",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      7,
      "http://127.0.0.1:8000/api/v1/target-activity-groups?target_ref=review_item%3Areview_scene_pending&source=operator_action&actor_ref=ops.duwei",
    );
  });
});

describe("knowledge console domain reads", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/api/v1/knowledge-entries/style_rule/STYLE_DOMAIN_PENDING/workflow")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_items: [{ review_id: "review_pending_style_rule_domain", status: "pending" }],
              jobs: [],
              human_review_events: [],
              target_activity_groups: [],
              recommended_primary_action: {
                kind: "review",
                action: "approve_review",
                review_id: "review_pending_style_rule_domain",
                label: "Approve",
                target_ref: "review_item:review_pending_style_rule_domain",
              },
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries/style_rule/STYLE_DOMAIN_PENDING")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              object_type: "style_rule",
              lineage_key: "STYLE_DOMAIN_PENDING",
              status: "candidate",
              active_version: null,
              candidate_version: {
                review_id: "review_pending_style_rule_domain",
                text: "keep the reunion clipped and gesture-led",
                scope: "global",
                scope_ref_id: "global",
              },
              versions: [],
              runtime_refs: { mode: "pending_review" },
              review_refs: ["review_pending_style_rule_domain"],
              bundle_refs: [],
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  object_type: "style_rule",
                  lineage_key: "STYLE_DOMAIN_PENDING",
                  status: "candidate",
                  active_version: null,
                  candidate_version: {
                    review_id: "review_pending_style_rule_domain",
                    text: "keep the reunion clipped and gesture-led",
                    scope: "global",
                    scope_ref_id: "global",
                  },
                  versions: [],
                  runtime_refs: { mode: "pending_review" },
                  review_refs: ["review_pending_style_rule_domain"],
                  bundle_refs: [],
                },
              ],
              supported_object_types: ["style_rule", "voice_card"],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  it("loads catalog and detail from domain endpoints without fetching review-items", async () => {
    const store = useKnowledgeConsoleStore();

    await store.load({
      objectType: "style_rule",
      scope: "global",
      scopeRefId: "global",
      status: "candidate",
    });
    await store.selectItem("style_rule", "STYLE_DOMAIN_PENDING");

    expect(store.items).toHaveLength(1);
    expect(store.detail.workflow.recommended_primary_action.review_id).toBe("review_pending_style_rule_domain");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/knowledge-entries?object_type=style_rule&scope=global&scope_ref_id=global&status=candidate",
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/knowledge-entries/style_rule/STYLE_DOMAIN_PENDING",
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/knowledge-entries/style_rule/STYLE_DOMAIN_PENDING/workflow",
    );
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/review-items"));
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/knowledge?"));
  });
});

describe("index console domain reads", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/api/v1/vector-alias-scopes")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [{ alias_scope: "style_observation:global:global", verify_status: "succeeded" }],
            },
          }),
        };
      }

      if (url.includes("/api/v1/jobs")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [{ job_id: "verify_job_domain", job_type: "verify", status: "failed" }],
            },
          }),
        };
      }

      if (url.includes("/api/v1/activity-events?stream=recovery_timeline")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_runtime_match",
                  event_source: "idempotency_recovery",
                  status: "needs_followup",
                  last_action: "retry_verify",
                  last_action_at: "2026-04-11T09:00:00+00:00",
                  last_actor_ref: "ops.duwei",
                  linked_target_ref: "review_item:review_scene_pending",
                  linked_target: {
                    target_type: "review_item",
                    target_id: "review_scene_pending",
                    target_ref: "review_item:review_scene_pending",
                  },
                  followup_action: null,
                  followup_target: null,
                  followup_target_ref: null,
                  resolution_reason: "retry verify is ready",
                  replay_target: null,
                  last_replay_result: null,
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/api/v1/activity-events?stream=system_runtime")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [{ operation_id: 11, event_type: "runtime_due_promotion", created_at: "2026-04-11T09:05:00+00:00" }] },
          }),
        };
      }

      if (url.includes("/api/v1/activity-events?stream=operator_action")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [{ operation_id: 12, action: "retry_verify", created_at: "2026-04-11T09:03:00+00:00" }] },
          }),
        };
      }

      if (url.includes("/api/v1/target-activity-groups")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  target: {
                    target_type: "review_item",
                    target_id: "review_scene_pending",
                    target_ref: "review_item:review_scene_pending",
                  },
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

  it("loads index panels from domain endpoints and derives the latest recovery receipt locally", async () => {
    const store = useIndexConsoleStore();

    await store.load();

    expect(store.aliasScopes).toHaveLength(1);
    expect(store.jobs).toHaveLength(1);
    expect(store.recoveryEvents).toHaveLength(1);
    expect(store.systemRuntimeEvents).toHaveLength(1);
    expect(store.operatorActionEvents).toHaveLength(1);
    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        event_id: "human_review_runtime_match",
        action: "retry_verify",
        actor_ref: "ops.duwei",
        linked_target_ref: "review_item:review_scene_pending",
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/vector-alias-scopes"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/jobs"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=recovery_timeline"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=system_runtime"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=operator_action"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/target-activity-groups"));
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/index/runtime-ledger"));
  });

  it("requests only the selected activity stream when a source filter is active", async () => {
    const store = useIndexConsoleStore();
    store.ledgerFilters.source = "operator_action";

    await store.load();

    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=operator_action"));
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=recovery_timeline"));
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=system_runtime"));
  });
});
