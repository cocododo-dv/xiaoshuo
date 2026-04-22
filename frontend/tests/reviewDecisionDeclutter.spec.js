// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createApp, h, nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";

import CursorPager from "../src/components/CursorPager.vue";
import ReviewCard from "../src/components/ReviewCard.vue";

const SOURCE_ROOT = process.cwd();

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

describe("decision review decluttering", () => {
  it("labels cursor pagers, keeps disabled direction visible, and can hide empty pagers", async () => {
    const mounted = await mount(CursorPager, {
      label: "审核项",
      pagination: {
        mode: "cursor",
        returned: 25,
        total: 70,
        has_next: true,
        next_cursor: "review-next",
      },
      canPrevious: false,
      canNext: true,
    });

    try {
      expect(mounted.container.textContent).toContain("审核项");
      expect(mounted.container.textContent).toContain("25 / 共 70");
      expect(mounted.container.querySelector('[data-testid="cursor-pager-previous"]').disabled).toBe(true);
      expect(mounted.container.querySelector('[data-testid="cursor-pager-next"]').disabled).toBe(false);
    } finally {
      mounted.unmount();
    }

    const emptyMounted = await mount(CursorPager, {
      label: "人工事件",
      hideWhenEmpty: true,
      pagination: {
        mode: "cursor",
        returned: 0,
        total: 0,
        has_next: false,
      },
    });

    try {
      expect(emptyMounted.container.textContent).toBe("");
    } finally {
      emptyMounted.unmount();
    }
  });

  it("shows reference profile application reviews as user-facing summaries before technical details", async () => {
    const reviewId = "review_apply_refprofile_refbook_d4ae8e00eea8_c172c96ee5_narra";
    const lineageKey = "REF_STYLE_refprofile_refbook_d4ae8e00eea8_c172c96ee5_scene_CH001";
    const openReference = vi.fn();
    const mounted = await mount(ReviewCard, {
      item: {
        review_id: reviewId,
        item_type: "narrative_pattern",
        target_collection: "narrative_patterns",
        status: "pending",
        materialize_status: "pending",
        active_on_approve: 0,
        candidate_text: `narrative_patterns ${reviewId}`,
        candidate_payload_json: {
          source: "reference_profile_apply",
          scope: "chapter",
          scope_ref_id: "CH001",
          lineage_key: lineageKey,
          profile_title: "龙族[1-3部全].txt reference profile",
          narrative_patterns: ["Use chapter hook escalation."],
          style_profile: {
            contract_version: "STYLE_FEATURE_CONTRACT_v1",
            features: {
              rhythm: { guidance: ["Use compact pressure beats."] },
            },
          },
        },
      },
      onApprove: vi.fn(),
      onRelease: vi.fn(),
      onOpenTarget: vi.fn(),
      onOpenReference: openReference,
    });

    try {
      const card = mounted.container.querySelector(".review-card");
      expect(card.textContent).toContain("参考画像应用");
      expect(card.textContent).toContain("回到参考书学习");
      expect(card.textContent).toContain("CH001");
      expect(card.textContent).not.toContain(reviewId);
      expect(card.textContent).not.toContain(lineageKey);

      card.querySelector(`[data-testid="review-open-reference-${reviewId}"]`).click();
      await nextTick();
      expect(openReference).toHaveBeenCalledWith(reviewId);

      card.querySelector(`[data-testid="review-toggle-payload-${reviewId}"]`).click();
      await nextTick();
      expect(card.textContent).toContain(reviewId);
      expect(card.textContent).toContain(lineageKey);
    } finally {
      mounted.unmount();
    }
  });

  it("blocks release for approved vector reviews until verify succeeds", async () => {
    const release = vi.fn();
    const openVerifyJob = vi.fn();
    const reviewId = "review_style_waiting_verify";
    const mounted = await mount(ReviewCard, {
      item: {
        review_id: reviewId,
        item_type: "style_observation",
        target_collection: "style_observations",
        status: "approved",
        materialize_status: "succeeded",
        active_on_approve: 0,
        candidate_text: "hold the image until the final line snaps shut",
        release_state: {
          state: "blocked",
          blocked_reason: "not_verified",
          message: "候选尚未通过索引校验，请先在索引控制台重试校验，成功后再发布。",
          recommended_action: "retry_verify",
          verify_job_id: `verify_${reviewId}`,
        },
        candidate_payload_json: {
          source: "knowledge_console",
          scope: "global",
          scope_ref_id: "global",
          lineage_key: "STY_WAITING_VERIFY",
        },
      },
      onApprove: vi.fn(),
      onRelease: release,
      onOpenTarget: vi.fn(),
      onOpenVerifyJob: openVerifyJob,
    });

    try {
      const card = mounted.container.querySelector(".review-card");
      const releaseButton = card.querySelector(`[data-testid="review-release-${reviewId}"]`);
      expect(releaseButton.disabled).toBe(true);
      expect(card.textContent).toContain("候选尚未通过索引校验");
      expect(card.textContent).toContain("批准：确认候选");
      expect(card.textContent).toContain("发布：将已批准且校验通过的候选切换为运行时生效版本");

      releaseButton.click();
      await nextTick();
      expect(release).not.toHaveBeenCalled();

      card.querySelector(`[data-testid="review-open-verify-${reviewId}"]`).click();
      await nextTick();
      expect(openVerifyJob).toHaveBeenCalledWith(`verify_${reviewId}`, reviewId);
    } finally {
      mounted.unmount();
    }
  });

  it("keeps reference candidate reversal controls visible after approval", () => {
    const viewSource = readFileSync(path.join(SOURCE_ROOT, "src/views/ReferenceLearningView.vue"), "utf8");
    const styleSource = readFileSync(path.join(SOURCE_ROOT, "src/styles/app.css"), "utf8");

    expect(viewSource).toContain("rejectionHint");
    expect(viewSource).toContain("reference-reject-button");
    expect(viewSource).toContain('placeholder="可选原因"');
    expect(styleSource).toContain(".reference-reject-button");
    expect(styleSource).toContain(".reference-reject-button.is-reversal");
  });

  it("separates human-review and review-item pagination in the inbox source", () => {
    const source = readFileSync(path.join(SOURCE_ROOT, "src/views/ReviewInboxView.vue"), "utf8");

    expect(source).toContain("shouldShowHumanReviewPager");
    expect(source).toContain("review-inbox-section");
    expect(source).toContain('label="人工事件"');
    expect(source).toContain('label="审核项"');
    expect(source).toContain(":hide-when-empty=\"true\"");
    expect(source).toContain("@open-reference");
    expect(source).toContain("handleReviewOpenReference");
    expect(source).toContain('navigate("reference")');
  });
});
