<script setup>
import { computed, reactive } from "vue";

import PanelShell from "../components/PanelShell.vue";
import { useShellRouter } from "../router";
import { useInteropCenterStore } from "../stores/interopCenter";

const emit = defineEmits(["notice"]);

const interopCenter = useInteropCenterStore();
const { openTarget } = useShellRouter();
const query = reactive({
  exportBundleId: interopCenter.exportBundleId || "",
  replayFinalRowId: interopCenter.replayFinalRowId || "",
  replayDraftRowId: interopCenter.replayDraftRowId || "",
});

const activeEnvelope = computed(() => interopCenter.activeEnvelope);
const activeArtifactReceipt = computed(() => interopCenter.activeArtifactReceipt);
const activeSourceComparisons = computed(() => interopCenter.activeSourceComparisons || []);
const previewSummary = computed(() => interopCenter.previewResult?.summary || null);
const prettyEnvelope = computed(() =>
  activeEnvelope.value ? JSON.stringify(activeEnvelope.value, null, 2) : "",
);

function syncQueryState() {
  query.exportBundleId = interopCenter.exportBundleId || query.exportBundleId;
  query.replayFinalRowId = interopCenter.replayFinalRowId || query.replayFinalRowId;
  query.replayDraftRowId = interopCenter.replayDraftRowId || query.replayDraftRowId;
}

async function runPreview() {
  try {
    const message = await interopCenter.previewWorksheet();
    syncQueryState();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runImport() {
  try {
    const message = await interopCenter.importWorksheet();
    syncQueryState();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function loadExport() {
  try {
    const message = await interopCenter.exportBundle(query.exportBundleId);
    syncQueryState();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function loadReplayFinal() {
  try {
    const message = await interopCenter.replayFinalScene(query.replayFinalRowId);
    syncQueryState();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function loadReplayDraft() {
  try {
    const message = await interopCenter.replayDraft(query.replayDraftRowId);
    syncQueryState();
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

function openComparisonTarget(item) {
  if (!item?.target) {
    return;
  }
  openTarget(item.target, {
    view_id: item.target.view_id,
    source_type: "interop_comparison",
    source_id: item.target.target_ref,
  });
  emit("notice", `Opened ${item.target.target_ref}`);
}

function openBundleScene() {
  if (!activeEnvelope.value?.scene_id) {
    return;
  }
  openTarget(
    {
      target_type: "scene_card",
      target_id: activeEnvelope.value.scene_id,
      target_ref: `scene_card:${activeEnvelope.value.scene_id}`,
      view_id: "workbench",
    },
    {
      view_id: "workbench",
      source_type: "interop_bundle",
      source_id: activeEnvelope.value.bundle_id,
    },
  );
  emit("notice", `Opened scene_card:${activeEnvelope.value.scene_id}`);
}
</script>

<template>
  <section class="panel-grid" data-testid="interop-center-view">
    <PanelShell
      eyebrow="Interop Center"
      title="Preview, import, export, and replay bundle worksheets"
      description="Validate worksheet_yaml envelopes, import P0/P1 bundles, and inspect source_ref_comparisons against the current runtime state."
    >
      <div class="interop-layout">
        <article class="paper">
          <div class="receipt-head">
            <div>
              <h3>Preview Worksheet</h3>
              <p class="muted receipt-copy">Paste a strict YAML worksheet_yaml envelope, validate it on the backend, then unlock Import Worksheet.</p>
            </div>
            <span class="badge">worksheet_yaml</span>
          </div>
          <label class="interop-wide">
            <span>Worksheet YAML</span>
            <textarea
              v-model="interopCenter.worksheetYaml"
              class="control-input control-textarea interop-editor"
              data-testid="interop-worksheet-input"
              placeholder="bundle_id: bundle_interop_v1"
            />
          </label>
          <div class="card-actions">
            <button
              :disabled="interopCenter.actionId === 'preview'"
              data-testid="interop-preview-button"
              @click="runPreview"
            >
              {{ interopCenter.actionId === "preview" ? "Previewing..." : "Preview Worksheet" }}
            </button>
            <button
              :disabled="!interopCenter.canImport || interopCenter.actionId === 'import'"
              data-testid="interop-import-button"
              @click="runImport"
            >
              {{ interopCenter.actionId === "import" ? "Importing..." : "Import Worksheet" }}
            </button>
          </div>

          <article v-if="previewSummary" class="paper mini" data-testid="interop-preview-summary">
            <h4>Preview Worksheet</h4>
            <p><strong>Bundle</strong><br />{{ previewSummary.bundle_id }}</p>
            <p><strong>Scene / Chapter</strong><br />{{ previewSummary.scene_id }} / {{ previewSummary.chapter_id }}</p>
            <p><strong>Execution Mode</strong><br />{{ previewSummary.execution_mode }}</p>
            <p><strong>Comparisons</strong><br />{{ previewSummary.comparison_count }}</p>
            <p><strong>Hash Contract</strong><br />{{ interopCenter.previewResult?.envelope?.hash_contract_version || "-" }}</p>
          </article>

          <article
            v-if="interopCenter.activeMode === 'import' && activeArtifactReceipt"
            class="paper mini"
            data-testid="interop-import-receipt"
          >
            <h4>Import Worksheet</h4>
            <p><strong>Bundle</strong><br />{{ activeEnvelope?.bundle_id || "-" }}</p>
            <p><strong>Artifact Kind</strong><br />{{ activeArtifactReceipt.artifact_kind }}</p>
            <p><strong>Artifact Path</strong><br />{{ activeArtifactReceipt.file_path }}</p>
          </article>
        </article>

        <article class="paper">
          <div class="receipt-head">
            <div>
              <h3>Bundle Export</h3>
              <p class="muted receipt-copy">Load a bundle worksheet export or replay an existing final scene / draft into the result panel.</p>
            </div>
            <span class="badge">GET interop/replay</span>
          </div>

          <div class="interop-query-grid">
            <label>
              <span>Bundle ID</span>
              <input
                v-model="query.exportBundleId"
                class="control-input"
                data-testid="interop-export-bundle-id"
                placeholder="bundle_CH001_SC01"
              />
            </label>
            <button
              :disabled="interopCenter.actionId === 'export'"
              data-testid="interop-export-button"
              @click="loadExport"
            >
              {{ interopCenter.actionId === "export" ? "Loading..." : "Bundle Export" }}
            </button>

            <label>
              <span>Final Scene Row ID</span>
              <input
                v-model="query.replayFinalRowId"
                class="control-input"
                data-testid="interop-replay-final-row-id"
                placeholder="final_scene_CH001_SC01"
              />
            </label>
            <button
              :disabled="interopCenter.actionId === 'replay-final'"
              data-testid="interop-replay-final-button"
              @click="loadReplayFinal"
            >
              {{ interopCenter.actionId === "replay-final" ? "Loading..." : "Replay Final Scene" }}
            </button>

            <label>
              <span>Draft Row ID</span>
              <input
                v-model="query.replayDraftRowId"
                class="control-input"
                data-testid="interop-replay-draft-row-id"
                placeholder="draft_scene_CH001_SC01"
              />
            </label>
            <button
              :disabled="interopCenter.actionId === 'replay-draft'"
              @click="loadReplayDraft"
            >
              {{ interopCenter.actionId === "replay-draft" ? "Loading..." : "Replay Draft" }}
            </button>
          </div>
        </article>

        <article class="paper">
          <div class="receipt-head">
            <div>
              <h3>Result Envelope</h3>
              <p class="muted receipt-copy">source_ref_comparisons are rendered below with version and text drift summaries plus jump links.</p>
            </div>
            <span class="badge">{{ interopCenter.activeMode || "idle" }}</span>
          </div>

          <article v-if="interopCenter.error" class="paper mini inline-error">
            <h4>Latest Error</h4>
            <p>{{ interopCenter.error }}</p>
          </article>

          <div v-if="activeEnvelope" data-testid="interop-envelope-panel">
            <div class="receipt-grid">
              <p><strong>Bundle</strong><br />{{ activeEnvelope.bundle_id }}</p>
              <p><strong>Hash</strong><br />{{ activeEnvelope.bundle_snapshot_hash || "-" }}</p>
              <p><strong>Execution</strong><br />{{ activeEnvelope.execution_mode || "-" }}</p>
              <p><strong>Created By</strong><br />{{ activeEnvelope.created_by_action || "-" }}</p>
            </div>
            <div class="card-actions">
              <button class="ghost" @click="openBundleScene">Open Scene Workbench</button>
            </div>
            <pre>{{ prettyEnvelope }}</pre>
          </div>
          <div v-else class="empty">Preview or load a worksheet to inspect the normalized envelope.</div>

          <article
            v-if="interopCenter.activeMode.startsWith('replay') && activeArtifactReceipt"
            class="paper mini"
            data-testid="interop-replay-receipt"
          >
            <h4>Replay Final Scene</h4>
            <p><strong>Artifact Kind</strong><br />{{ activeArtifactReceipt.artifact_kind }}</p>
            <p><strong>Artifact Path</strong><br />{{ activeArtifactReceipt.file_path }}</p>
          </article>

          <div v-if="activeSourceComparisons.length" class="comparison-list">
            <article
              v-for="item in activeSourceComparisons"
              :key="`${item.object_type}:${item.lineage_key}:${item.source_ref_key}`"
              class="paper mini comparison-card"
              :data-testid="`interop-source-comparison-${item.object_type}-${item.lineage_key}`"
            >
              <div class="source-top">
                <div>
                  <div class="eyebrow">{{ item.object_type }}</div>
                  <h4>{{ item.lineage_key }}</h4>
                </div>
                <span class="badge">{{ item.source_ref_key }}</span>
              </div>
              <div class="comparison-diff-grid">
                <p><strong>Version Drift</strong><br />{{ item.version_status }}</p>
                <p><strong>Text Drift</strong><br />{{ item.text_status }}</p>
                <p><strong>Source Row / Version</strong><br />{{ item.source_row_id || "-" }} / {{ item.source_version ?? "-" }}</p>
                <p><strong>Active Row / Version</strong><br />{{ item.active_row_id || "-" }} / {{ item.active_version ?? "-" }}</p>
              </div>
              <div class="comparison-copy-grid">
                <div>
                  <div class="history-title">Source Text</div>
                  <p>{{ item.source_text || "-" }}</p>
                </div>
                <div>
                  <div class="history-title">Active Text</div>
                  <p>{{ item.active_text || "-" }}</p>
                </div>
              </div>
              <div class="card-actions">
                <button v-if="item.target" class="ghost" @click="openComparisonTarget(item)">
                  Open {{ item.target.view_id === "knowledge" ? "Knowledge Console" : "Scene Workbench" }}
                </button>
              </div>
            </article>
          </div>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
