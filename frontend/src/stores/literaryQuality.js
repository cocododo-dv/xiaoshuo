import { defineStore } from "pinia";

import {
  analyzeLiteraryQualityText,
  fetchLiteraryEvalLatest,
  fetchLiteraryQualityOverview,
  runLiteraryQualityChapterSetReview,
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
    risk_clusters: [],
    fingerprints: [],
    cross_scene_reuse: [],
    recommended_next_action: null,
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
    analyzeLoading: false,
    chapterSetLoading: false,
    error: "",
    evalError: "",
    analyzeError: "",
    chapterSetError: "",
    textLayer: "author_draft_preferred",
    chapterId: "",
    riskType: "",
    minSeverity: "",
    analyzeResult: null,
    chapterSetReview: null,
  }),
  getters: {
    summary: (state) => state.overview.summary || {},
    overviewItems: (state) => state.overview.items || [],
    riskClusters: (state) => state.overview.risk_clusters || [],
    fingerprints: (state) => state.overview.fingerprints || [],
    crossSceneReuse: (state) => state.overview.cross_scene_reuse || [],
    recommendedNextAction: (state) => state.overview.recommended_next_action || null,
    spanFindings: (state) => state.analyzeResult?.span_findings || [],
    benchmarkCases: (state) => state.latestReport?.cases || [],
    benchmarkSummary: (state) => state.latestReport?.summary || {},
    chapterSetScores: (state) => state.chapterSetReview?.scores || {},
    chapterSetPatterns: (state) => state.chapterSetReview?.repeated_patterns || [],
    chapterSetSafetyFindings: (state) => state.chapterSetReview?.reference_safety_findings || [],
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
        if (Object.prototype.hasOwnProperty.call(filters, "textLayer")) {
          this.textLayer = filters.textLayer || "author_draft_preferred";
        }
        if (Object.prototype.hasOwnProperty.call(filters, "chapterId")) {
          this.chapterId = filters.chapterId || "";
        }
        if (Object.prototype.hasOwnProperty.call(filters, "riskType")) {
          this.riskType = filters.riskType || "";
        }
        if (Object.prototype.hasOwnProperty.call(filters, "minSeverity")) {
          this.minSeverity = filters.minSeverity || "";
        }
        const payload = await fetchLiteraryQualityOverview({
          textLayer: this.textLayer,
          chapterId: this.chapterId,
          riskType: this.riskType,
          minSeverity: this.minSeverity,
        });
        this.overview = snapshotPayload({
          summary: payload.summary || {},
          items: snapshotPayloadList(payload.items || []),
          risk_clusters: snapshotPayloadList(payload.risk_clusters || []),
          fingerprints: snapshotPayloadList(payload.fingerprints || []),
          cross_scene_reuse: snapshotPayloadList(payload.cross_scene_reuse || []),
          recommended_next_action: payload.recommended_next_action || null,
          filters: payload.filters || {},
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
    async analyzeText(payload = {}) {
      this.analyzeLoading = true;
      this.analyzeError = "";
      try {
        const result = await analyzeLiteraryQualityText(payload);
        this.analyzeResult = snapshotPayload(result || null);
        return this.analyzeResult;
      } catch (error) {
        this.analyzeResult = null;
        this.analyzeError = error.message;
        throw error;
      } finally {
        this.analyzeLoading = false;
      }
    },
    async runChapterSetReview(payload = {}) {
      this.chapterSetLoading = true;
      this.chapterSetError = "";
      try {
        const result = await runLiteraryQualityChapterSetReview(payload);
        this.chapterSetReview = snapshotPayload(result || null);
        return this.chapterSetReview;
      } catch (error) {
        this.chapterSetReview = null;
        this.chapterSetError = error.message;
        throw error;
      } finally {
        this.chapterSetLoading = false;
      }
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
