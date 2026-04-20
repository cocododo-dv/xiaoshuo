// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createApp, h, nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeConsoleView from "../src/views/KnowledgeConsoleView.vue";
import { setOperatorRef } from "../src/lib/api";
import { useKnowledgeConsoleStore } from "../src/stores/knowledgeConsole";

const SOURCE_ROOT = process.cwd();

function activeStyleProfile() {
  return {
    contract_version: "STYLE_FEATURE_CONTRACT_v1",
    features: {
      rhythm: { guidance: ["Keep sentences slow and even."] },
      imagery: { guidance: ["Keep tactile objects in frame."] },
      dialogue_ratio: { guidance: ["Keep dialogue sparse."] },
    },
  };
}

function candidateStyleProfile() {
  return {
    contract_version: "STYLE_FEATURE_CONTRACT_v1",
    features: {
      rhythm: { guidance: ["Use clipped beats before a longer release."] },
      imagery: { guidance: ["Keep tactile objects in frame."] },
      dialogue_ratio: { guidance: [] },
    },
  };
}

function highRiskKnowledgeDetail(reviewId = "review_style_profile_global_global_risk") {
  const candidateProfile = candidateStyleProfile();
  return {
    object_type: "style_rule",
    lineage_key: "style_profile_global_global",
    status: "candidate",
    active_version: {
      row_id: "style_profile_active",
      text: "active style profile",
      style_profile: activeStyleProfile(),
    },
    candidate_version: {
      row_id: "style_profile_candidate",
      review_id: reviewId,
      text: "candidate style profile",
      style_profile: candidateProfile,
    },
    workflow: {
      review_items: [
        {
          review_id: reviewId,
          item_type: "style_rule_set",
          target_collection: "style_rules",
          status: "pending",
          materialize_status: "pending",
          active_on_approve: 1,
          style_profile_baseline: activeStyleProfile(),
          candidate_payload_json: {
            lineage_key: "style_profile_global_global",
            source: "style_profile_extract",
            style_profile: candidateProfile,
          },
        },
      ],
      jobs: [],
      human_review_events: [],
      target_activity_groups: [],
      recommended_primary_action: null,
    },
  };
}

async function mountKnowledgeConsole({ detail = highRiskKnowledgeDetail(), approveAction } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useKnowledgeConsoleStore();
  store.$patch({
    loaded: true,
    selectedObjectType: detail.object_type,
    selectedLineageKey: detail.lineage_key,
    items: [detail],
    detail,
    supportedObjectTypes: ["style_rule"],
  });
  if (approveAction) {
    store.approveReview = approveAction;
  }

  const container = document.createElement("div");
  document.body.appendChild(container);
  const notices = [];
  const app = createApp({
    render() {
      return h(KnowledgeConsoleView, {
        onNotice(message) {
          notices.push(message);
        },
      });
    },
  });
  app.use(pinia);
  app.mount(container);
  await nextTick();
  await nextTick();

  return {
    container,
    store,
    notices,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

describe("knowledge console risk approval", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    setOperatorRef("operator");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("requires acknowledgement and reason before approving high-risk style profile reviews", async () => {
    const reviewId = "review_style_profile_global_global_risk";
    const approveAction = vi.fn(async () => "已批准");
    const mounted = await mountKnowledgeConsole({
      detail: highRiskKnowledgeDetail(reviewId),
      approveAction,
    });

    try {
      const approveButton = mounted.container.querySelector(`[data-testid="knowledge-approve-review-${reviewId}"]`);
      const confirmation = mounted.container.querySelector(`[data-testid="knowledge-risk-confirmation-${reviewId}"]`);
      const checkbox = mounted.container.querySelector(`[data-testid="knowledge-risk-confirm-${reviewId}"]`);
      const reason = mounted.container.querySelector(`[data-testid="knowledge-risk-reason-${reviewId}"]`);

      expect(confirmation).not.toBeNull();
      expect(approveButton.disabled).toBe(true);
      expect(checkbox).not.toBeNull();
      expect(reason).not.toBeNull();

      checkbox.checked = true;
      checkbox.dispatchEvent(new Event("change"));
      reason.value = "Approved after comparing the replacement style profile with sample output.";
      reason.dispatchEvent(new Event("input"));
      await nextTick();

      expect(approveButton.disabled).toBe(false);
      approveButton.click();
      await nextTick();

      expect(approveAction).toHaveBeenCalledWith(reviewId, {
        risk_confirmation: {
          acknowledged: true,
          reason: "Approved after comparing the replacement style profile with sample output.",
          severity: "high",
        },
      });
    } finally {
      mounted.unmount();
    }
  });

  it("passes risk confirmation payload through the knowledge console store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useKnowledgeConsoleStore();
    store.refreshSelection = vi.fn(async () => null);

    let approveBody = null;
    let approveHeaders = null;
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url === "http://127.0.0.1:8000/api/v1/review-items/review_style_profile_global_global_risk/approve") {
        approveBody = JSON.parse(options.body);
        approveHeaders = options.headers;
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_style_profile_global_global_risk",
              actor_ref: "operator",
            },
          }),
        };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    await store.approveReview("review_style_profile_global_global_risk", {
      risk_confirmation: {
        acknowledged: true,
        reason: "Approved after comparing sample output.",
        severity: "high",
      },
    });

    expect(approveBody).toEqual({
      risk_confirmation: {
        acknowledged: true,
        reason: "Approved after comparing sample output.",
        severity: "high",
      },
    });
    expect(approveHeaders["X-Operator-Ref"]).toBe("operator");
  });

  it("surfaces safe reference-learning source labels and return links in the knowledge console source", () => {
    const source = readFileSync(path.join(SOURCE_ROOT, "src/views/KnowledgeConsoleView.vue"), "utf8");

    expect(source).toContain("referenceSourceForItem");
    expect(source).toContain("referenceKnowledgeSummary");
    expect(source).toContain("openReferenceLearning");
    expect(source).toContain("来自参考书学习");
    expect(source).toContain("参考书候选已抽象化，源书片段隐藏。");
    expect(source).toContain("knowledge-open-reference");
    expect(source).toContain("回到参考书学习");
  });
});
