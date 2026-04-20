<script setup>
import { computed, reactive } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
import VirtualList from "../components/VirtualList.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useInteropCenterStore } from "../stores/interopCenter";

const emit = defineEmits(["notice"]);

const interopCenter = useInteropCenterStore();
const { openTarget } = useShellRouter();
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const INTEROP_IMPORT_SCOPE = "interop:import";
const INTEROP_RESULT_SCOPE = "interop:result";
const query = reactive({
  exportBundleId: interopCenter.exportBundleId || "",
  replayFinalRowId: interopCenter.replayFinalRowId || "",
  replayDraftRowId: interopCenter.replayDraftRowId || "",
});

const activeEnvelope = computed(() => interopCenter.activeEnvelope);
const activeArtifactReceipt = computed(() => interopCenter.activeArtifactReceipt);
const activeSourceComparisons = computed(() => interopCenter.activeSourceComparisons || []);
const previewSummary = computed(() => interopCenter.previewResult?.summary || null);
const ACTIVE_MODE_LABELS = {
  preview: "预览结果",
  import: "导入结果",
  export: "导出结果",
  "replay-final": "终稿回放",
  "replay-draft": "草稿回放",
  idle: "未加载",
};

function formatActiveMode(mode) {
  return ACTIVE_MODE_LABELS[mode || "idle"] || mode || "未加载";
}

function formatJsonPayload(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function comparisonKey(item) {
  return `${item?.object_type || "unknown"}:${item?.lineage_key || "unknown"}:${item?.source_ref_key || "unknown"}`;
}

function syncQueryState() {
  query.exportBundleId = interopCenter.exportBundleId || query.exportBundleId;
  query.replayFinalRowId = interopCenter.replayFinalRowId || query.replayFinalRowId;
  query.replayDraftRowId = interopCenter.replayDraftRowId || query.replayDraftRowId;
}

async function runPreview() {
  const result = await runFlowAction({
    scopeKey: INTEROP_IMPORT_SCOPE,
    actionLabel: "预览工作表",
    runningMessage: "正在解析工作表并生成预览...",
    successMessage: (message) => message || "工作表预览已生成。",
    nextStep: () => "下一步：确认预览无误后点击「导入工作表」。",
    action: () => interopCenter.previewWorksheet(),
  });
  if (result) {
    syncQueryState();
  }
}

async function runImport() {
  const result = await runFlowAction({
    scopeKey: INTEROP_IMPORT_SCOPE,
    actionLabel: "导入工作表",
    runningMessage: "正在导入工作表产物...",
    successMessage: (message) => message || "工作表已导入。",
    nextStep: () => "下一步：查看导入回执，或打开场景工作台继续验证。",
    action: () => interopCenter.importWorksheet(),
  });
  if (result) {
    syncQueryState();
  }
}

async function loadExport() {
  const result = await runFlowAction({
    scopeKey: INTEROP_RESULT_SCOPE,
    actionLabel: "加载导出结果",
    runningMessage: "正在加载 bundle 导出结果...",
    successMessage: (message) => message || "导出结果已加载。",
    nextStep: () => "下一步：查看结果信封和来源对比。",
    action: () => interopCenter.exportBundle(query.exportBundleId),
  });
  if (result) {
    syncQueryState();
  }
}

async function loadReplayFinal() {
  const result = await runFlowAction({
    scopeKey: INTEROP_RESULT_SCOPE,
    actionLabel: "回放终稿场景",
    runningMessage: "正在回放终稿场景...",
    successMessage: (message) => message || "终稿场景已回放。",
    nextStep: () => "下一步：查看回放回执和来源对比。",
    action: () => interopCenter.replayFinalScene(query.replayFinalRowId),
  });
  if (result) {
    syncQueryState();
  }
}

async function loadReplayDraft() {
  const result = await runFlowAction({
    scopeKey: INTEROP_RESULT_SCOPE,
    actionLabel: "回放草稿",
    runningMessage: "正在回放草稿...",
    successMessage: (message) => message || "草稿已回放。",
    nextStep: () => "下一步：查看回放回执和来源对比。",
    action: () => interopCenter.replayDraft(query.replayDraftRowId),
  });
  if (result) {
    syncQueryState();
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
  emit("notice", `已打开目标：${item.target.target_ref}`);
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
  emit("notice", `已打开场景工作台：scene_card:${activeEnvelope.value.scene_id}`);
}
</script>

<template>
  <section class="panel-grid" data-testid="interop-center-view">
    <PanelShell
      eyebrow="互操作中心"
      title="预览、导入、导出与回放工作表"
      description="校验 worksheet_yaml 信封，导入 P0/P1 包，并对照当前运行态查看 source_ref_comparisons。"
    >
      <div class="interop-layout">
        <article class="paper">
          <div class="receipt-head">
            <div>
              <h3>预览工作表</h3>
              <p class="muted receipt-copy">粘贴严格的 YAML 格式 worksheet_yaml 信封，先让后端校验，通过后再解锁导入。</p>
            </div>
            <span class="badge">worksheet_yaml</span>
          </div>
          <label class="interop-wide">
            <span>工作表 YAML</span>
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
              {{ interopCenter.actionId === "preview" ? "预览中..." : "预览工作表" }}
            </button>
            <button
              :disabled="!interopCenter.canImport || interopCenter.actionId === 'import'"
              data-testid="interop-import-button"
              @click="runImport"
            >
              {{ interopCenter.actionId === "import" ? "导入中..." : "导入工作表" }}
            </button>
          </div>
          <FlowActionReceipt :receipt="receipt(INTEROP_IMPORT_SCOPE)" />

          <article v-if="previewSummary" class="paper mini" data-testid="interop-preview-summary">
            <h4>预览结果</h4>
            <p><strong>包 ID</strong><br />{{ previewSummary.bundle_id }}</p>
            <p><strong>场景 / 章节</strong><br />{{ previewSummary.scene_id }} / {{ previewSummary.chapter_id }}</p>
            <p><strong>执行模式</strong><br />{{ previewSummary.execution_mode }}</p>
            <p><strong>对比项数量</strong><br />{{ previewSummary.comparison_count }}</p>
            <p><strong>哈希契约</strong><br />{{ interopCenter.previewResult?.envelope?.hash_contract_version || "-" }}</p>
          </article>

          <article
            v-if="interopCenter.activeMode === 'import' && activeArtifactReceipt"
            class="paper mini"
            data-testid="interop-import-receipt"
          >
            <h4>导入回执</h4>
            <p><strong>包 ID</strong><br />{{ activeEnvelope?.bundle_id || "-" }}</p>
            <p><strong>产物类型</strong><br />{{ activeArtifactReceipt.artifact_kind }}</p>
            <p><strong>产物路径</strong><br />{{ activeArtifactReceipt.file_path }}</p>
          </article>
        </article>

        <article class="paper">
          <div class="receipt-head">
            <div>
              <h3>包导出与回放</h3>
              <p class="muted receipt-copy">加载已导出的 bundle worksheet，或者把已有 final scene / draft 回放到结果面板。</p>
            </div>
            <span class="badge">回放接口</span>
          </div>

          <div class="interop-query-grid">
            <label>
              <span>包 ID</span>
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
              {{ interopCenter.actionId === "export" ? "加载中..." : "加载导出结果" }}
            </button>

            <label>
              <span>终稿场景行 ID</span>
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
              {{ interopCenter.actionId === "replay-final" ? "加载中..." : "回放终稿场景" }}
            </button>

            <label>
              <span>草稿行 ID</span>
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
              {{ interopCenter.actionId === "replay-draft" ? "加载中..." : "回放草稿" }}
            </button>
          </div>
          <FlowActionReceipt :receipt="receipt(INTEROP_RESULT_SCOPE)" />
        </article>

        <article class="paper">
          <div class="receipt-head">
            <div>
              <h3>结果信封</h3>
              <p class="muted receipt-copy">下面会渲染 source_ref_comparisons，并附带版本偏差、文本偏差和跳转入口。</p>
            </div>
            <span class="badge">{{ formatActiveMode(interopCenter.activeMode) }}</span>
          </div>

          <article v-if="interopCenter.error" class="paper mini inline-error">
            <h4>最新错误</h4>
            <p>{{ interopCenter.error }}</p>
          </article>

          <div v-if="activeEnvelope" data-testid="interop-envelope-panel">
            <div class="receipt-grid">
              <p><strong>包 ID</strong><br />{{ activeEnvelope.bundle_id }}</p>
              <p><strong>哈希</strong><br />{{ activeEnvelope.bundle_snapshot_hash || "-" }}</p>
              <p><strong>执行模式</strong><br />{{ activeEnvelope.execution_mode || "-" }}</p>
              <p><strong>创建动作</strong><br />{{ activeEnvelope.created_by_action || "-" }}</p>
            </div>
            <div class="card-actions">
              <button class="ghost" @click="openBundleScene">打开场景工作台</button>
            </div>
            <LazySection
              :key="`interop-envelope-${activeEnvelope.bundle_id || interopCenter.activeMode}`"
              title="结果信封详情"
              toggle-test-id="interop-toggle-envelope"
            >
              <pre class="json-block">{{ formatJsonPayload(activeEnvelope) }}</pre>
            </LazySection>
          </div>
          <div v-else class="empty">先预览或加载工作表，再查看归一化后的结果信封。</div>

          <article
            v-if="interopCenter.activeMode.startsWith('replay') && activeArtifactReceipt"
            class="paper mini"
            data-testid="interop-replay-receipt"
          >
            <h4>回放回执</h4>
            <p><strong>产物类型</strong><br />{{ activeArtifactReceipt.artifact_kind }}</p>
            <p><strong>产物路径</strong><br />{{ activeArtifactReceipt.file_path }}</p>
          </article>

          <VirtualList
            v-if="activeSourceComparisons.length"
            class="comparison-list"
            :items="activeSourceComparisons"
            :item-key="comparisonKey"
            :estimated-item-height="260"
            :threshold="8"
            :viewport-height="640"
            test-id="interop-comparison-virtual-list"
          >
            <template #default="{ item }">
              <article
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
                  <p><strong>版本偏差</strong><br />{{ item.version_status }}</p>
                  <p><strong>文本偏差</strong><br />{{ item.text_status }}</p>
                  <p><strong>来源行 / 版本</strong><br />{{ item.source_row_id || "-" }} / {{ item.source_version ?? "-" }}</p>
                  <p><strong>生效行 / 版本</strong><br />{{ item.active_row_id || "-" }} / {{ item.active_version ?? "-" }}</p>
                </div>
                <div class="comparison-copy-grid">
                  <div>
                    <div class="history-title">来源文本</div>
                    <p>{{ item.source_text || "-" }}</p>
                  </div>
                  <div>
                    <div class="history-title">生效文本</div>
                    <p>{{ item.active_text || "-" }}</p>
                  </div>
                </div>
                <div class="card-actions">
                  <button v-if="item.target" class="ghost" @click="openComparisonTarget(item)">
                    打开 {{ item.target.view_id === "knowledge" ? "知识控制台" : "场景工作台" }}
                  </button>
                </div>
              </article>
            </template>
          </VirtualList>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
