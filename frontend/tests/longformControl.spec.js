// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { createApp, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";
import { useShellRouter } from "../src/router";

const SOURCE_ROOT = process.cwd();
const VIEW_PATH = path.join(SOURCE_ROOT, "src/views/LongformControlView.vue");
const STORE_PATH = path.join(SOURCE_ROOT, "src/stores/longformControl.js");

function okEnvelope(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

function dashboardPayload(overrides = {}) {
  return {
    summary: {
      chapter_count: 1,
      scene_count: 2,
      complete_chapter_count: 0,
      aggregate_missing_count: 1,
      open_revision_candidate_count: 1,
      human_review_count: 1,
      open_foreshadow_count: 1,
      continuity_alert_count: 4,
    },
    chapters: [
      {
        chapter_id: "LFC100",
        chapter_goal: "Keep the investigation moving",
        current_phase: "drafting",
        scene_count: 2,
        generated_scene_count: 1,
        missing_scene_ids: ["LFC100_SC02"],
        completion_status: "partial",
        comparison_status: "aggregate_missing",
        assembled_char_count: 41,
        final_aggregate_row_id: null,
        final_aggregate_char_count: 0,
        average_writer_score: 0.42,
        open_revision_candidate_count: 1,
        requires_human_review_count: 1,
      },
    ],
    rhythm_map: [
      {
        chapter_id: "LFC100",
        scene_count: 2,
        generated_scene_count: 1,
        assembled_char_count: 41,
        final_aggregate_char_count: 0,
        average_scene_char_count: 21,
        average_writer_score: 0.42,
        completion_status: "partial",
        comparison_status: "aggregate_missing",
        qc_blocker_count: 1,
      },
    ],
    character_arcs: [
      {
        character_id: "CHAR_A",
        chapters: ["LFC100"],
        pov_scene_count: 2,
        onstage_scene_count: 2,
        active_voice_profile_count: 1,
        relation_profile_count: 1,
        low_agency_finding_count: 1,
        power_shift_finding_count: 1,
      },
    ],
    promise_payoff: [
      {
        chapter_id: "LFC100",
        chapter_promise: "Find out why the witness lied",
        ending_question: "Who warned CHAR_B?",
        payoff_target: "The lie points to the archive key",
        reveal_or_reversal: "The witness is protecting CHAR_A",
        risk_flags: ["hook_open"],
      },
    ],
    character_arc_timeline: [
      {
        character_id: "CHAR_A",
        desire_changes: ["wants safety", "chooses the investigation"],
        low_agency_points: [{ chapter_id: "LFC100", scene_id: "LFC100_SC01" }],
        relationship_turns: [{ chapter_id: "LFC100", relation: "CHAR_A/CHAR_B" }],
      },
    ],
    relation_tension_matrix: [
      {
        pair_key: "CHAR_A/CHAR_B",
        tension_sources: ["shared secret", "unequal power"],
        secret_count: 1,
        misunderstanding_count: 1,
        unresolved_pressure_count: 1,
      },
    ],
    motif_tracking: [
      {
        motif: "blue umbrella",
        chapters: ["LFC100"],
        repeat_risk: true,
        transformation_note: "needs a changed meaning on the next use",
      },
    ],
    information_release_curve: [
      {
        chapter_id: "LFC100",
        explanation_count: 2,
        action_count: 1,
        turn_count: 1,
        balance_note: "exposition slightly ahead of action",
      },
    ],
    reader_hook_debts: [
      {
        hook_id: "hook_LFC100",
        chapter_id: "LFC100",
        question: "Who warned CHAR_B?",
        debt_state: "open",
      },
    ],
    debt_radar: [
      {
        promise_ref: "chapter_promise:LFC100",
        debt_type: "chapter_promise",
        chapter_id: "LFC100",
        scene_id: null,
        text: "Find out why the witness lied",
        opened_at: "chapter:LFC100",
        expected_payoff_window: "chapter:LFC100:ending",
        payoff_status: "open",
        deferral_reason: "Who warned CHAR_B?",
        risk_level: "major",
      },
      {
        promise_ref: "foreshadow:FS-LFC100",
        debt_type: "foreshadow",
        chapter_id: "LFC100",
        scene_id: "LFC100_SC01",
        text: "CHAR_B knows the missing name",
        opened_at: "scene:LFC100_SC01",
        expected_payoff_window: "chapter:LFC100",
        payoff_status: "open",
        deferral_reason: "still open",
        risk_level: "critical",
      },
    ],
    foreshadow_debts: [
      {
        row_id: "foreshadow_row_LFC100",
        foreshadow_id: "FS-LFC100",
        chapter_id: "LFC100",
        scene_id: "LFC100_SC01",
        text: "CHAR_B knows the missing name",
        tracker_status: "open",
        debt_state: "open",
      },
    ],
    continuity_alerts: [
      {
        alert_type: "missing_final_scene",
        severity: "blocker",
        chapter_id: "LFC100",
        scene_id: "LFC100_SC02",
        message: "scene is missing final text",
      },
    ],
    revision_pressure: [
      {
        chapter_id: "LFC100",
        latest_score: 0.42,
        open_candidate_count: 1,
        accepted_candidate_count: 0,
        rejected_candidate_count: 0,
        requires_human_review_count: 1,
        top_low_dimensions: [{ dimension: "power_shift", score: 0.39 }],
      },
    ],
    ...overrides,
  };
}

async function flushUi() {
  for (let index = 0; index < 4; index += 1) {
    await Promise.resolve();
    await nextTick();
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  }
}

describe("longform control shell registration", () => {
  it("registers a top-level longform control tower view and store", () => {
    const appSource = readFileSync(path.join(SOURCE_ROOT, "src/App.vue"), "utf8");
    const routerSource = readFileSync(path.join(SOURCE_ROOT, "src/router.js"), "utf8");

    expect(existsSync(VIEW_PATH)).toBe(true);
    expect(existsSync(STORE_PATH)).toBe(true);
    expect(appSource).toContain("LongformControlView");
    expect(routerSource).toContain('id: "longform"');
    expect(routerSource).toContain("长篇控制");
  });
});

describe("longform control api and store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the read-only dashboard from /api/v1/longform-control", async () => {
    globalThis.fetch = vi.fn(async (url) => okEnvelope({ url }));

    expect(typeof api.fetchLongformControl).toBe("function");
    await api.fetchLongformControl();

    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/longform-control");

    globalThis.fetch = vi.fn(async () => okEnvelope(dashboardPayload()));
    const { useLongformControlStore } = await import("../src/stores/longformControl.js");
    const store = useLongformControlStore();

    await store.initialize({ force: true });

    expect(store.dashboard.summary.chapter_count).toBe(1);
    expect(store.chapters[0].chapter_id).toBe("LFC100");
    expect(store.promisePayoff[0].chapter_promise).toContain("witness");
    expect(store.debtRadar[0].promise_ref).toBe("chapter_promise:LFC100");
    expect(store.relationTensionMatrix[0].pair_key).toBe("CHAR_A/CHAR_B");
    expect(store.readerHookDebts[0].question).toContain("CHAR_B");
    expect(store.hasAlerts).toBe(true);
  });
});

describe("longform control view", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    setActivePinia(createPinia());
    useShellRouter().reset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("renders rhythm, character arcs, foreshadow debts, continuity alerts, and revision pressure", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope(dashboardPayload()));

    const { default: LongformControlView } = await import("../src/views/LongformControlView.vue");
    const pinia = createPinia();
    setActivePinia(pinia);
    const container = document.createElement("div");
    document.body.appendChild(container);
    const app = createApp(LongformControlView);
    app.use(pinia);
    app.mount(container);

    try {
      await flushUi();

      expect(container.querySelector('[data-testid="longform-control-view"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-rhythm-map"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-character-arcs"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-promise-payoff"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-debt-radar"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-literary-signals"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-foreshadow-debts"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-continuity-alerts"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="longform-revision-pressure"]')).not.toBeNull();
      expect(container.textContent).toContain("LFC100");
      expect(container.textContent).toContain("CHAR_A");
      expect(container.textContent).toContain("Find out why the witness lied");
      expect(container.textContent).toContain("chapter_promise:LFC100");
      expect(container.textContent).toContain("foreshadow:FS-LFC100");
      expect(container.textContent).toContain("blue umbrella");
      expect(container.textContent).toContain("shared secret");
      expect(container.textContent).toContain("CHAR_B knows the missing name");
      expect(container.textContent).toContain("power_shift");
    } finally {
      app.unmount();
      container.remove();
    }
  });
});
