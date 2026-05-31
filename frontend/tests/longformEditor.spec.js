// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

function okEnvelope(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

function editorPayload() {
  return {
    dashboard: {
      summary: { chapter_count: 1, scene_count: 1, open_foreshadow_count: 1 },
      character_arcs: [{ character_id: "CHAR_A", chapters: ["LTE100"], pov_scene_count: 1 }],
      foreshadow_debts: [{ foreshadow_id: "FS-LTE100", chapter_id: "LTE100", text: "Archive key" }],
      information_release_curve: [{ chapter_id: "LTE100", scene_id: "LTE100_SC01", new_information: "copied key" }],
      promise_payoff: [{ chapter_id: "LTE100", chapter_promise: "Expose the leak", open_hook_count: 1 }],
    },
    cards: {
      summary: { open_count: 2, dismissed_count: 0, published_guidance_count: 0 },
      items: [
        {
          card_id: "lfcard_arc",
          card_type: "character_arc_gap",
          severity: "major",
          status: "open",
          object_type: "character",
          object_id: "CHAR_A",
          chapter_id: "LTE100",
          scene_id: "LTE100_SC01",
          evidence: { issue: "low agency", text_layer: "author_draft" },
          recommendation: { summary: "Force a visible choice." },
        },
      ],
    },
  };
}

describe("longform editor tower API and store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exposes longform editor and source safety API helpers", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchLongformEditorOverview();
    await api.runLongformEditorDiagnose();
    await api.fetchLongformEditorCards({ status: "open", cardType: "character_arc_gap" });
    await api.actOnLongformEditorCard("lfcard_arc", { action: "dismiss", note: "slow burn" });
    await api.publishLongformGuidance("lfcard_arc", {
      scope_type: "scene",
      scope_ref_id: "LTE100_SC01",
      content: "Force a visible choice.",
    });
    await api.fetchReferenceSafetyOverview();
    await api.extractReferenceSafetyProfile("refbook_safety");
    await api.scanSourceSafety({ text: "Professor Meridian", source_profile_ids: ["refprofile_safety"] });

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/longform-editor/overview");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/longform-editor/diagnose");
    expect(urls).toContain(
      "http://127.0.0.1:8000/api/v1/longform-editor/cards?status=open&card_type=character_arc_gap",
    );
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/longform-editor/cards/lfcard_arc/actions");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/longform-editor/cards/lfcard_arc/publish-guidance");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/reference-safety/overview");
    expect(urls).toContain("http://127.0.0.1:8000/api/v2/style-reference/books/refbook_safety/safety-profile/extract");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/source-safety/scan");
  });

  it("loads overview, cards, diagnosis, card actions, guidance, and reference safety", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (String(url).includes("/diagnose")) {
        return okEnvelope({ summary: { open_count: 3 }, cards: editorPayload().cards.items });
      }
      if (String(url).includes("/cards/lfcard_arc/actions")) {
        return okEnvelope({ card: { ...editorPayload().cards.items[0], status: "dismissed" } });
      }
      if (String(url).includes("/publish-guidance")) {
        return okEnvelope({ review: { review_id: "review_lfguidance" }, card: editorPayload().cards.items[0] });
      }
      if (String(url).includes("/reference-safety/overview")) {
        return okEnvelope({ summary: { profile_with_safety_count: 1 }, items: [] });
      }
      if (String(url).includes("/source-safety/scan")) {
        return okEnvelope({ safe: false, risk_count: 1, risks: [{ risk_type: "exact_term" }] });
      }
      return okEnvelope(editorPayload());
    });

    const { useLongformEditorStore } = await import("../src/stores/longformEditor.js");
    const store = useLongformEditorStore();

    await store.initialize({ force: true });
    expect(store.cardItems[0].card_type).toBe("character_arc_gap");
    expect(store.dailyFocusCards[0].card_type).toBe("character_arc_gap");
    expect(store.openCards.length).toBe(1);

    await store.runDiagnose();
    expect(store.cards.summary.open_count).toBe(3);

    const updated = await store.actOnCard("lfcard_arc", { action: "dismiss", note: "slow burn" });
    expect(updated.status).toBe("dismissed");

    const publishResult = await store.publishGuidance("lfcard_arc", {
      scope_type: "scene",
      scope_ref_id: "LTE100_SC01",
      content: "Force a visible choice.",
    });
    expect(publishResult.review.review_id).toBe("review_lfguidance");

    await store.loadReferenceSafety();
    expect(store.referenceSafety.summary.profile_with_safety_count).toBe(1);

    await store.scanSourceSafety({ text: "Professor Meridian" });
    expect(store.sourceSafetyScan.safe).toBe(false);
  });
});

describe("longform editor tower view contract", () => {
  it("keeps the longform route while adding editor tower tabs and card actions", () => {
    const routerSource = readSource("src/router.js");
    const viewSource = readSource("src/views/LongformControlView.vue");
    const appSource = readSource("src/App.vue");
    const storePath = path.join(SOURCE_ROOT, "src/stores/longformEditor.js");

    expect(existsSync(storePath)).toBe(true);
    expect(routerSource).toContain('id: "longform"');
    expect(appSource).toContain("LongformControlView");
    expect(viewSource).toContain("useLongformEditorStore");
    expect(viewSource).toContain('data-testid="longform-editor-tabs"');
    expect(viewSource).toContain('data-testid="longform-editor-cards"');
    expect(viewSource).toContain('data-testid="longform-card-open-deepdesk"');
    expect(viewSource).toContain("dailyFocusCards");
    expect(viewSource).toContain("结构诊断卡");
    expect(viewSource).toContain("人物弧线");
    expect(viewSource).toContain("伏笔债务");
    expect(viewSource).toContain("信息释放");
    expect(viewSource).toContain("承诺兑现");
    expect(viewSource).toContain("参考书安全");
    expect(viewSource).toContain("publishGuidance");
    expect(viewSource).toContain('navigate("review")');
    expect(viewSource).toContain('navigate("deepdesk")');
  });
});
