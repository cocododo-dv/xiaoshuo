import { defineStore } from "pinia";

import {
  fetchBundleWorksheetExport,
  fetchReplayDraft,
  fetchReplayFinalScene,
  importBundleWorksheet,
  previewBundleWorksheet,
} from "../lib/api";

function extractEnvelope(payload) {
  if (payload?.envelope) {
    return payload.envelope;
  }
  if (!payload?.bundle_id) {
    return null;
  }
  return {
    bundle_id: payload.bundle_id,
    scene_id: payload.scene_id,
    chapter_id: payload.chapter_id,
    bundle_snapshot_hash: payload.bundle_snapshot_hash,
    hash_contract_version: payload.hash_contract_version,
    hash_alg: payload.hash_alg,
    execution_mode: payload.execution_mode,
    created_by_action: payload.created_by_action,
    snapshot: payload.snapshot,
  };
}

function sourceComparisons(payload) {
  return payload?.source_ref_comparisons || [];
}

export const useInteropCenterStore = defineStore("interopCenter", {
  state: () => ({
    worksheetYaml: "",
    exportBundleId: "",
    replayFinalRowId: "",
    replayDraftRowId: "",
    previewResult: null,
    importResult: null,
    activeEnvelope: null,
    activeArtifactReceipt: null,
    activeSourceComparisons: [],
    activeMode: "",
    lastPreviewedWorksheet: "",
    actionId: "",
    error: "",
  }),
  getters: {
    canImport: (state) =>
      Boolean(
        state.previewResult
          && state.worksheetYaml.trim()
          && state.worksheetYaml.trim() === state.lastPreviewedWorksheet.trim(),
      ),
    comparisonSummary: (state) => state.previewResult?.summary || null,
  },
  actions: {
    async previewWorksheet(nextWorksheetYaml = this.worksheetYaml) {
      this.actionId = "preview";
      this.error = "";
      this.worksheetYaml = nextWorksheetYaml;
      try {
        const result = await previewBundleWorksheet(this.worksheetYaml);
        this.previewResult = result;
        this.importResult = null;
        this.activeEnvelope = result.envelope || null;
        this.activeArtifactReceipt = null;
        this.activeSourceComparisons = sourceComparisons(result);
        this.activeMode = "preview";
        this.lastPreviewedWorksheet = this.worksheetYaml;
        this.exportBundleId = result.envelope?.bundle_id || this.exportBundleId;
        return `Previewed ${result.envelope?.bundle_id || "worksheet"}`;
      } catch (error) {
        this.previewResult = null;
        this.activeEnvelope = null;
        this.activeArtifactReceipt = null;
        this.activeSourceComparisons = [];
        this.activeMode = "";
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async importWorksheet(nextWorksheetYaml = this.worksheetYaml) {
      this.actionId = "import";
      this.error = "";
      this.worksheetYaml = nextWorksheetYaml;
      try {
        const result = await importBundleWorksheet(this.worksheetYaml);
        this.importResult = result;
        this.activeEnvelope = result.envelope || null;
        this.activeArtifactReceipt = result.artifact_receipt || null;
        this.activeSourceComparisons = sourceComparisons(result);
        this.activeMode = "import";
        this.exportBundleId = result.bundle?.bundle_id || this.exportBundleId;
        return `Imported ${result.bundle?.bundle_id || "worksheet bundle"}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async exportBundle(bundleId = this.exportBundleId) {
      this.actionId = "export";
      this.error = "";
      try {
        const result = await fetchBundleWorksheetExport(bundleId.trim());
        this.activeEnvelope = extractEnvelope(result);
        this.activeArtifactReceipt = result.artifact_receipt || null;
        this.activeSourceComparisons = sourceComparisons(result);
        this.activeMode = "export";
        this.exportBundleId = bundleId.trim();
        return `Loaded export for ${this.exportBundleId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async replayFinalScene(rowId = this.replayFinalRowId) {
      this.actionId = "replay-final";
      this.error = "";
      try {
        const result = await fetchReplayFinalScene(rowId.trim());
        this.activeEnvelope = extractEnvelope(result);
        this.activeArtifactReceipt = result.artifact_receipt || null;
        this.activeSourceComparisons = sourceComparisons(result);
        this.activeMode = "replay-final";
        this.replayFinalRowId = rowId.trim();
        return `Loaded replay for ${this.replayFinalRowId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async replayDraft(rowId = this.replayDraftRowId) {
      this.actionId = "replay-draft";
      this.error = "";
      try {
        const result = await fetchReplayDraft(rowId.trim());
        this.activeEnvelope = extractEnvelope(result);
        this.activeArtifactReceipt = result.artifact_receipt || null;
        this.activeSourceComparisons = sourceComparisons(result);
        this.activeMode = "replay-draft";
        this.replayDraftRowId = rowId.trim();
        return `Loaded draft replay for ${this.replayDraftRowId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
