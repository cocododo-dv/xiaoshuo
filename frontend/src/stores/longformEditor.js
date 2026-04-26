import { defineStore } from "pinia";

import {
  actOnLongformEditorCard,
  fetchLongformEditorCards,
  fetchLongformEditorOverview,
  fetchReferenceSafetyOverview,
  publishLongformGuidance,
  runLongformEditorDiagnose,
  scanSourceSafety,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function emptyCards() {
  return {
    summary: {
      total_count: 0,
      open_count: 0,
      resolved_count: 0,
      dismissed_count: 0,
      published_guidance_count: 0,
      critical_count: 0,
      major_count: 0,
    },
    items: [],
  };
}

function emptyReferenceSafety() {
  return {
    summary: {
      profile_count: 0,
      ready_profile_count: 0,
      profile_with_safety_count: 0,
    },
    items: [],
  };
}

export const useLongformEditorStore = defineStore("longformEditor", {
  state: () => ({
    dashboard: {},
    cards: emptyCards(),
    referenceSafety: emptyReferenceSafety(),
    sourceSafetyScan: null,
    loaded: false,
    stale: false,
    loading: false,
    actionLoading: false,
    referenceSafetyLoading: false,
    error: "",
    referenceSafetyError: "",
  }),
  getters: {
    cardSummary: (state) => state.cards.summary || {},
    cardItems: (state) => state.cards.items || [],
    openCards: (state) => (state.cards.items || []).filter((card) => card.status === "open"),
    characterCards: (state) =>
      (state.cards.items || []).filter((card) => card.card_type === "character_arc_gap"),
    foreshadowCards: (state) => (state.cards.items || []).filter((card) => card.card_type === "foreshadow_debt"),
    informationCards: (state) =>
      (state.cards.items || []).filter((card) => card.card_type === "information_congestion"),
    promiseCards: (state) =>
      (state.cards.items || []).filter((card) => card.card_type === "promise_without_payoff"),
    referenceRiskCards: (state) =>
      (state.cards.items || []).filter((card) => card.card_type === "reference_leakage_risk"),
    dailyFocusCards: (state) => {
      const priorityTypes = new Set([
        "character_arc_gap",
        "foreshadow_debt",
        "promise_without_payoff",
        "information_congestion",
        "relationship_turn_stall",
      ]);
      const severityRank = { critical: 0, major: 1, minor: 2, info: 3 };
      return (state.cards.items || [])
        .filter((card) => card.status === "open" && priorityTypes.has(card.card_type))
        .sort((left, right) => {
          const severityDelta = (severityRank[left.severity] ?? 9) - (severityRank[right.severity] ?? 9);
          if (severityDelta) {
            return severityDelta;
          }
          return String(left.card_id || "").localeCompare(String(right.card_id || ""));
        });
    },
  },
  actions: {
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    markStale() {
      this.stale = true;
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchLongformEditorOverview();
        this.dashboard = snapshotPayload(payload.dashboard || {});
        this.cards = snapshotPayload({
          summary: payload.cards?.summary || emptyCards().summary,
          items: snapshotPayloadList(payload.cards?.items || []),
        });
        this.markFresh();
      } catch (error) {
        this.dashboard = {};
        this.cards = emptyCards();
        this.loaded = false;
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async loadCards(filters = {}) {
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchLongformEditorCards(filters);
        this.cards = snapshotPayload({
          summary: payload.summary || emptyCards().summary,
          items: snapshotPayloadList(payload.items || []),
        });
        return this.cards;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async runDiagnose() {
      this.actionLoading = true;
      this.error = "";
      try {
        const payload = await runLongformEditorDiagnose();
        this.cards = snapshotPayload({
          summary: payload.summary || emptyCards().summary,
          items: snapshotPayloadList(payload.cards || []),
        });
        this.stale = true;
        return this.cards;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionLoading = false;
      }
    },
    async actOnCard(cardId, payload) {
      this.actionLoading = true;
      this.error = "";
      try {
        const result = await actOnLongformEditorCard(cardId, payload);
        this._mergeCard(result.card);
        return result.card;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionLoading = false;
      }
    },
    async publishGuidance(cardId, payload) {
      this.actionLoading = true;
      this.error = "";
      try {
        const result = await publishLongformGuidance(cardId, payload);
        this._mergeCard(result.card);
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionLoading = false;
      }
    },
    async loadReferenceSafety() {
      this.referenceSafetyLoading = true;
      this.referenceSafetyError = "";
      try {
        const payload = await fetchReferenceSafetyOverview();
        this.referenceSafety = snapshotPayload({
          summary: payload.summary || emptyReferenceSafety().summary,
          items: snapshotPayloadList(payload.items || []),
        });
        return this.referenceSafety;
      } catch (error) {
        this.referenceSafety = emptyReferenceSafety();
        this.referenceSafetyError = error.message;
        throw error;
      } finally {
        this.referenceSafetyLoading = false;
      }
    },
    async scanSourceSafety(payload) {
      this.referenceSafetyLoading = true;
      this.referenceSafetyError = "";
      try {
        this.sourceSafetyScan = snapshotPayload(await scanSourceSafety(payload));
        return this.sourceSafetyScan;
      } catch (error) {
        this.sourceSafetyScan = null;
        this.referenceSafetyError = error.message;
        throw error;
      } finally {
        this.referenceSafetyLoading = false;
      }
    },
    _mergeCard(card) {
      if (!card?.card_id) {
        return;
      }
      const items = this.cards.items || [];
      const index = items.findIndex((item) => item.card_id === card.card_id);
      let nextItems;
      if (index >= 0) {
        nextItems = items.map((item) => (item.card_id === card.card_id ? snapshotPayload(card) : item));
      } else {
        nextItems = [snapshotPayload(card), ...items];
      }
      const nextSnapshotItems = snapshotPayloadList(nextItems);
      this.cards = snapshotPayload({
        summary: {
          ...this.cards.summary,
          total_count: nextSnapshotItems.length,
          open_count: nextSnapshotItems.filter((item) => item.status === "open").length,
          resolved_count: nextSnapshotItems.filter((item) => item.status === "resolved").length,
          dismissed_count: nextSnapshotItems.filter((item) => item.status === "dismissed").length,
          published_guidance_count: nextSnapshotItems.filter((item) => item.status === "published_guidance").length,
        },
        items: nextSnapshotItems,
      });
    },
  },
});
