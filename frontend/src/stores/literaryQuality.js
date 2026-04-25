import { defineStore } from "pinia";

import {
  fetchLiteraryEvalLatest,
  fetchLiteraryQualityOverview,
  runLiteraryEval,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function emptyOverview() {
  return {
    summary: {
      object_count: 0,
      mean_score: null,
      high_risk_count: 0,
      model_voice_count: 0,
    },
    items: [],
  };
}

export const useLiteraryQualityStore = defineStore("literaryQuality", {
  state: () => ({
    overview: emptyOverview(),
    latestReport: null,
    loaded: false,
    stale: false,
    loading: false,
    evalLoading: false,
    error: "",
    evalError: "",
    textLayer: "author_draft_preferred",
  }),
  getters: {
    summary: (state) => state.overview.summary || {},
    overviewItems: (state) => state.overview.items || [],
    benchmarkCases: (state) => state.latestReport?.cases || [],
    benchmarkSummary: (state) => state.latestReport?.summary || {},
  },
  actions: {
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      await Promise.all([this.loadOverview(), this.loadLatestEval()]);
      this.markFresh();
    },
    async loadOverview(filters = {}) {
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchLiteraryQualityOverview({
          textLayer: this.textLayer,
          ...filters,
        });
        this.overview = snapshotPayload({
          summary: payload.summary || {},
          items: snapshotPayloadList(payload.items || []),
        });
      } catch (error) {
        this.overview = emptyOverview();
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async refreshOverview() {
      await this.loadOverview();
      this.markFresh();
    },
    async loadLatestEval() {
      this.evalLoading = true;
      this.evalError = "";
      try {
        const payload = await fetchLiteraryEvalLatest();
        this.latestReport = snapshotPayload(payload.report || null);
      } catch (error) {
        this.latestReport = null;
        this.evalError = error.message;
        throw error;
      } finally {
        this.evalLoading = false;
      }
    },
    async runBaselineEval() {
      return this.runEval({ mode: "baseline" });
    },
    async runLiveEval() {
      return this.runEval({ mode: "live" });
    },
    async runEval(payload = { mode: "baseline" }) {
      this.evalLoading = true;
      this.evalError = "";
      try {
        const result = await runLiteraryEval(payload);
        this.latestReport = snapshotPayload(result.report || null);
        return this.latestReport;
      } catch (error) {
        this.evalError = error.message;
        throw error;
      } finally {
        this.evalLoading = false;
      }
    },
  },
});
