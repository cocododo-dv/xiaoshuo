// @vitest-environment jsdom

import { createApp, h, nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TargetActivityGroupCard from "../src/components/TargetActivityGroupCard.vue";
import { useUiMode } from "../src/composables/useUiMode";

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

describe("TargetActivityGroupCard", () => {
  beforeEach(() => {
    localStorage.clear();
    useUiMode().setUiMode("guided");
  });

  it("shows the high-risk approval confirmation reason on operator activity rows", async () => {
    const activityKey = "operator_action:77";
    const reason = "Editorially approved reset of dialogue-ratio guidance.";
    const mounted = await mount(TargetActivityGroupCard, {
      group: {
        target: {
          target_type: "review_item",
          target_id: "review_style_profile_risk",
          target_ref: "review_item:review_style_profile_risk",
        },
        latest_at: "2026-04-18T11:30:00+00:00",
        activity_count: 1,
        sources: ["operator_action"],
      },
      expanded: true,
      items: [
        {
          activity_key: activityKey,
          source: "operator_action",
          timestamp: "2026-04-18T11:30:00+00:00",
          actor_ref: "style.reviewer",
          label: "approve_review",
          status: "succeeded",
          summary: "review approved and candidate materialized",
          risk_confirmation: {
            acknowledged: true,
            reason,
            severity: "high",
          },
          target_refs: [],
        },
      ],
      onToggle: vi.fn(),
      onOpenTarget: vi.fn(),
      onPrevious: vi.fn(),
      onNext: vi.fn(),
    });

    try {
      const audit = mounted.container.querySelector(
        `[data-testid="target-activity-risk-confirmation-${activityKey}"]`,
      );
      expect(audit).not.toBeNull();
      expect(audit.textContent).toContain("高风险确认");
      expect(audit.textContent).toContain(reason);
    } finally {
      mounted.unmount();
    }
  });

  it("keeps raw target refs out of guided mode and restores them in advanced mode", async () => {
    const targetRef = "review_item:review_style_profile_risk";
    const mode = useUiMode();
    mode.setUiMode("guided");

    const mounted = await mount(TargetActivityGroupCard, {
      group: {
        target: {
          target_type: "review_item",
          target_id: "review_style_profile_risk",
          target_ref: targetRef,
        },
        latest_at: "2026-04-18T11:30:00+00:00",
        activity_count: 1,
        sources: ["operator_action"],
      },
      expanded: false,
      onToggle: vi.fn(),
      onOpenTarget: vi.fn(),
      onPrevious: vi.fn(),
      onNext: vi.fn(),
    });

    try {
      expect(mounted.container.textContent).toContain("审核");
      expect(mounted.container.textContent).not.toContain(targetRef);
      expect(mounted.container.querySelector('[data-testid="index-target-technical-ref"]')).toBeNull();

      mode.setUiMode("advanced");
      await nextTick();

      expect(mounted.container.textContent).toContain(targetRef);
      expect(mounted.container.querySelector('[data-testid="index-target-technical-ref"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });
});
