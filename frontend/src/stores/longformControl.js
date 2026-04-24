import { defineStore } from "pinia";

import { fetchLongformControl } from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function emptyDashboard() {
  return {
    summary: {},
    chapters: [],
    rhythm_map: [],
    character_arcs: [],
    foreshadow_debts: [],
    continuity_alerts: [],
    revision_pressure: [],
  };
}

export const useLongformControlStore = defineStore("longformControl", {
  state: () => ({
    dashboard: emptyDashboard(),
    loaded: false,
    stale: false,
    loading: false,
    error: "",
  }),
  getters: {
    summary: (state) => state.dashboard.summary || {},
    chapters: (state) => state.dashboard.chapters || [],
    rhythmMap: (state) => state.dashboard.rhythm_map || [],
    characterArcs: (state) => state.dashboard.character_arcs || [],
    foreshadowDebts: (state) => state.dashboard.foreshadow_debts || [],
    continuityAlerts: (state) => state.dashboard.continuity_alerts || [],
    revisionPressure: (state) => state.dashboard.revision_pressure || [],
    hasAlerts: (state) => Boolean((state.dashboard.continuity_alerts || []).length),
  },
  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchLongformControl();
        this.dashboard = snapshotPayload({
          summary: payload.summary || {},
          chapters: snapshotPayloadList(payload.chapters || []),
          rhythm_map: snapshotPayloadList(payload.rhythm_map || []),
          character_arcs: snapshotPayloadList(payload.character_arcs || []),
          foreshadow_debts: snapshotPayloadList(payload.foreshadow_debts || []),
          continuity_alerts: snapshotPayloadList(payload.continuity_alerts || []),
          revision_pressure: snapshotPayloadList(payload.revision_pressure || []),
        });
        this.markFresh();
      } catch (error) {
        this.dashboard = emptyDashboard();
        this.loaded = false;
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async refresh() {
      await this.initialize({ force: true });
    },
  },
});
