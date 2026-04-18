// @vitest-environment jsdom

import { createApp, h, nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";

import ReviewCard from "../src/components/ReviewCard.vue";
import StyleProfileDiffSummary from "../src/components/StyleProfileDiffSummary.vue";
import StyleProfileRiskWarning from "../src/components/StyleProfileRiskWarning.vue";
import {
  buildStyleProfileSummary,
  buildStyleProfileDiffSummary,
  buildStyleProfileRiskSummary,
  buildReviewImpactSummary,
  styleProfileRiskFromKnowledgeDetail,
  styleProfileRiskFromReviewItem,
  styleProfileDiffFromKnowledgeDetail,
  styleProfileSummaryFromKnowledgeDetail,
} from "../src/lib/styleProfileSummary";

function styleProfile() {
  return {
    contract_version: "STYLE_FEATURE_CONTRACT_v1",
    features: {
      rhythm: { guidance: ["Use clipped beats before a longer release."] },
      syntax: { guidance: [] },
      imagery: { guidance: ["Keep tactile objects in frame."] },
      narrative_distance: { guidance: [] },
      emotion_curve: { guidance: [] },
      paragraph_density: { guidance: ["Use compact paragraphs."] },
      dialogue_ratio: { guidance: ["Keep dialogue sparse."] },
    },
    calibration_lines: ["The gate clicked shut like a verdict."],
    banned_moves: ["Do not copy named-author phrasing."],
  };
}

function activeStyleProfile() {
  return {
    contract_version: "STYLE_FEATURE_CONTRACT_v1",
    features: {
      rhythm: { guidance: ["Keep sentences slow and even."] },
      syntax: { guidance: [] },
      imagery: { guidance: ["Keep tactile objects in frame."] },
      narrative_distance: { guidance: [] },
      emotion_curve: { guidance: [] },
      paragraph_density: { guidance: [] },
      dialogue_ratio: { guidance: ["Keep dialogue sparse."] },
    },
    calibration_lines: ["The gate clicked shut like a verdict."],
    banned_moves: ["Do not copy named-author phrasing."],
  };
}

async function mount(component, props = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const app = createApp({
    render() {
      return h(component, props);
    },
  });
  app.mount(container);
  await nextTick();
  return {
    container,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

describe("style profile summary", () => {
  it("builds reviewer-facing feature rows from a structured style profile", () => {
    const summary = buildStyleProfileSummary(styleProfile());

    expect(summary.available).toBe(true);
    expect(summary.contractVersion).toBe("STYLE_FEATURE_CONTRACT_v1");
    expect(summary.featureRows.map((row) => row.key)).toEqual([
      "rhythm",
      "imagery",
      "paragraph_density",
      "dialogue_ratio",
    ]);
    expect(summary.featureRows[0].label).toBe("节奏");
    expect(summary.featureRows[1].guidance[0]).toContain("tactile");
    expect(summary.calibrationLines).toEqual(["The gate clicked shut like a verdict."]);
    expect(summary.bannedMoves).toEqual(["Do not copy named-author phrasing."]);
  });

  it("finds style profile metadata on a knowledge candidate version", () => {
    const summary = styleProfileSummaryFromKnowledgeDetail({
      candidate_version: {
        source: "style_profile_extract",
        style_profile: styleProfile(),
      },
    });

    expect(summary.available).toBe(true);
    expect(summary.source).toBe("candidate_version");
    expect(summary.featureRows.map((row) => row.label)).toContain("对白比例");
  });

  it("renders the style profile summary inside review cards", async () => {
    const mounted = await mount(ReviewCard, {
      item: {
        review_id: "review_style_profile_global_global_abc123",
        target_collection: "style_rules",
        status: "pending",
        materialize_status: "pending",
        candidate_text: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
        candidate_payload_json: {
          lineage_key: "style_profile_global_global",
          source: "style_profile_extract",
          style_profile: styleProfile(),
        },
      },
      onApprove: vi.fn(),
      onRelease: vi.fn(),
      onOpenTarget: vi.fn(),
    });

    try {
      const summary = mounted.container.querySelector('[data-testid="review-style-profile-summary"]');
      expect(summary).not.toBeNull();
      expect(summary.textContent).toContain("风格画像");
      expect(summary.textContent).toContain("节奏");
      expect(summary.textContent).toContain("意象");
      expect(summary.textContent).toContain("对白比例");
      expect(summary.textContent).toContain("Keep dialogue sparse.");
    } finally {
      mounted.unmount();
    }
  });

  it("summarizes source, target impact, and runtime release behavior for style profile reviews", async () => {
    const item = {
      review_id: "review_style_profile_global_global_abc123",
      item_type: "style_rule_set",
      target_collection: "style_rules",
      status: "pending",
      materialize_status: "pending",
      active_on_approve: 0,
      candidate_text: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
      candidate_payload_json: {
        scope: "global",
        scope_ref_id: "global",
        lineage_key: "style_profile_global_global",
        source: "style_profile_extract",
        contract_version: "STYLE_FEATURE_CONTRACT_v1",
        style_profile: styleProfile(),
      },
    };

    const impact = buildReviewImpactSummary(item);
    expect(impact.available).toBe(true);
    expect(impact.sourceLabel).toBe("样本文本提取");
    expect(impact.targetLabel).toBe("风格规则");
    expect(impact.targetDetail).toContain("style_profile_global_global");
    expect(impact.runtimeLabel).toBe("需发布后进入运行时");
    expect(impact.runtimeDetail).toContain("批准会先物化候选");

    const directRuntimeImpact = buildReviewImpactSummary({ ...item, active_on_approve: 1 });
    expect(directRuntimeImpact.runtimeLabel).toBe("批准后进入运行时");
    expect(directRuntimeImpact.runtimeDetail).toContain("后续 bundle 构建会读取");

    const mounted = await mount(ReviewCard, {
      item,
      onApprove: vi.fn(),
      onRelease: vi.fn(),
      onOpenTarget: vi.fn(),
    });

    try {
      const reviewImpact = mounted.container.querySelector('[data-testid="review-impact-summary"]');
      expect(reviewImpact).not.toBeNull();
      expect(reviewImpact.textContent).toContain("样本文本提取");
      expect(reviewImpact.textContent).toContain("风格规则");
      expect(reviewImpact.textContent).toContain("需发布后进入运行时");
    } finally {
      mounted.unmount();
    }
  });

  it("builds a reviewer-facing diff between active and candidate style profiles", () => {
    const summary = buildStyleProfileDiffSummary(activeStyleProfile(), styleProfile());

    expect(summary.available).toBe(true);
    expect(summary.baselineLabel).toBe("对比当前生效画像");
    expect(summary.counts).toEqual({ added: 1, changed: 1, removed: 0 });
    expect(summary.rows.map((row) => [row.key, row.status])).toEqual([
      ["rhythm", "changed"],
      ["paragraph_density", "added"],
    ]);
    expect(summary.rows[0].before).toEqual(["Keep sentences slow and even."]);
    expect(summary.rows[0].after).toEqual(["Use clipped beats before a longer release."]);
    expect(summary.rows[1].after).toEqual(["Use compact paragraphs."]);

    const removedSummary = buildStyleProfileDiffSummary(activeStyleProfile(), {
      ...styleProfile(),
      features: {
        ...styleProfile().features,
        dialogue_ratio: { guidance: [] },
      },
    });
    expect(removedSummary.rows.map((row) => [row.key, row.status])).toContainEqual(["dialogue_ratio", "removed"]);
  });

  it("finds style profile diffs on knowledge detail active and candidate versions", () => {
    const summary = styleProfileDiffFromKnowledgeDetail({
      active_version: { style_profile: activeStyleProfile() },
      candidate_version: { style_profile: styleProfile() },
    });

    expect(summary.available).toBe(true);
    expect(summary.rows.map((row) => row.key)).toEqual(["rhythm", "paragraph_density"]);
  });

  it("renders the style profile diff summary", async () => {
    const summary = buildStyleProfileDiffSummary(activeStyleProfile(), styleProfile());
    const mounted = await mount(StyleProfileDiffSummary, {
      summary,
      testId: "knowledge-style-profile-diff-summary",
    });

    try {
      const diff = mounted.container.querySelector('[data-testid="knowledge-style-profile-diff-summary"]');
      expect(diff).not.toBeNull();
      expect(diff.textContent).toContain("批准前差异");
      expect(diff.textContent).toContain("Keep sentences slow and even.");
      expect(diff.textContent).toContain("Use clipped beats before a longer release.");
      expect(diff.textContent).toContain("Use compact paragraphs.");
    } finally {
      mounted.unmount();
    }
  });

  it("flags removals and broad style profile diffs as approval risks", async () => {
    const removedSummary = buildStyleProfileDiffSummary(activeStyleProfile(), {
      ...styleProfile(),
      features: {
        ...styleProfile().features,
        dialogue_ratio: { guidance: [] },
      },
    });
    const removedRisk = buildStyleProfileRiskSummary(removedSummary);
    expect(removedRisk.available).toBe(true);
    expect(removedRisk.severity).toBe("high");
    expect(removedRisk.title).toBe("高风险风格替换");
    expect(removedRisk.reasons[0]).toContain("移除");

    const broadRisk = buildStyleProfileRiskSummary({
      available: true,
      counts: { added: 2, changed: 1, removed: 0 },
      rows: [
        { key: "rhythm", status: "changed" },
        { key: "syntax", status: "added" },
        { key: "imagery", status: "added" },
      ],
    });
    expect(broadRisk.available).toBe(true);
    expect(broadRisk.severity).toBe("medium");
    expect(broadRisk.title).toBe("大范围风格调整");

    const quietRisk = buildStyleProfileRiskSummary(buildStyleProfileDiffSummary(activeStyleProfile(), styleProfile()));
    expect(quietRisk.available).toBe(false);

    const mounted = await mount(StyleProfileRiskWarning, {
      risk: removedRisk,
      testId: "style-profile-risk-warning",
    });
    try {
      const risk = mounted.container.querySelector('[data-testid="style-profile-risk-warning"]');
      expect(risk).not.toBeNull();
      expect(risk.textContent).toContain("高风险风格替换");
      expect(risk.textContent).toContain("批准前请确认");
    } finally {
      mounted.unmount();
    }
  });

  it("requires an acknowledgement and reason before approving high-risk style profile reviews", async () => {
    const candidateProfile = {
      ...styleProfile(),
      features: {
        ...styleProfile().features,
        dialogue_ratio: { guidance: [] },
      },
    };
    const reviewId = "review_style_profile_global_global_risk";
    const item = {
      review_id: reviewId,
      item_type: "style_rule_set",
      target_collection: "style_rules",
      status: "pending",
      materialize_status: "pending",
      active_on_approve: 0,
      style_profile_baseline: activeStyleProfile(),
      candidate_text: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
      candidate_payload_json: {
        scope: "global",
        scope_ref_id: "global",
        lineage_key: "style_profile_global_global",
        source: "style_profile_extract",
        contract_version: "STYLE_FEATURE_CONTRACT_v1",
        style_profile: candidateProfile,
      },
    };
    const onApprove = vi.fn();
    const mounted = await mount(ReviewCard, {
      item,
      onApprove,
      onRelease: vi.fn(),
      onOpenTarget: vi.fn(),
    });

    try {
      const approveButton = mounted.container.querySelector(`[data-testid="review-approve-${reviewId}"]`);
      const checkbox = mounted.container.querySelector(`[data-testid="review-risk-confirm-${reviewId}"]`);
      const reason = mounted.container.querySelector(`[data-testid="review-risk-reason-${reviewId}"]`);

      expect(approveButton.disabled).toBe(true);
      expect(checkbox).not.toBeNull();
      expect(reason).not.toBeNull();

      checkbox.checked = true;
      checkbox.dispatchEvent(new Event("change"));
      reason.value = "Editorially approved reset after comparing sample output.";
      reason.dispatchEvent(new Event("input"));
      await nextTick();

      expect(approveButton.disabled).toBe(false);
      approveButton.click();

      expect(onApprove).toHaveBeenCalledWith(reviewId, {
        risk_confirmation: {
          acknowledged: true,
          reason: "Editorially approved reset after comparing sample output.",
          severity: "high",
        },
      });
    } finally {
      mounted.unmount();
    }
  });

  it("derives risk warnings from knowledge detail and review items", async () => {
    const candidateProfile = {
      ...styleProfile(),
      features: {
        ...styleProfile().features,
        dialogue_ratio: { guidance: [] },
      },
    };
    const knowledgeRisk = styleProfileRiskFromKnowledgeDetail({
      active_version: { style_profile: activeStyleProfile() },
      candidate_version: { style_profile: candidateProfile },
    });
    expect(knowledgeRisk.available).toBe(true);
    expect(knowledgeRisk.severity).toBe("high");

    const reviewItem = {
      review_id: "review_style_profile_global_global_abc123",
      item_type: "style_rule_set",
      target_collection: "style_rules",
      status: "pending",
      materialize_status: "pending",
      active_on_approve: 0,
      style_profile_baseline: activeStyleProfile(),
      candidate_text: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
      candidate_payload_json: {
        scope: "global",
        scope_ref_id: "global",
        lineage_key: "style_profile_global_global",
        source: "style_profile_extract",
        contract_version: "STYLE_FEATURE_CONTRACT_v1",
        style_profile: candidateProfile,
      },
    };
    const reviewRisk = styleProfileRiskFromReviewItem(reviewItem);
    expect(reviewRisk.available).toBe(true);

    const mounted = await mount(ReviewCard, {
      item: reviewItem,
      onApprove: vi.fn(),
      onRelease: vi.fn(),
      onOpenTarget: vi.fn(),
    });
    try {
      const risk = mounted.container.querySelector('[data-testid="review-style-profile-risk-warning"]');
      expect(risk).not.toBeNull();
      expect(risk.textContent).toContain("高风险风格替换");
    } finally {
      mounted.unmount();
    }
  });
});
