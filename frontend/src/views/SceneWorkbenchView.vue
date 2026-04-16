<script setup>
import { computed, onActivated, ref, watch } from "vue";

import AttemptTimeline from "../components/AttemptTimeline.vue";
import BundleProvenanceCard from "../components/BundleProvenanceCard.vue";
import CursorPager from "../components/CursorPager.vue";
import GenerationSummaryCard from "../components/GenerationSummaryCard.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import QcReportCard from "../components/QcReportCard.vue";
import { useShellRouter } from "../router";
import { useWorkbenchStore } from "../stores/workbench";

const emit = defineEmits(["notice"]);

const workbench = useWorkbenchStore();
const { focusTarget, openTarget } = useShellRouter();
const requestedSceneId = ref(workbench.sceneId);
const manualHoldReason = ref("");
const selectedStrategies = ref({});

const hasData = computed(() => Boolean(workbench.data));
const chapterState = computed(() => workbench.data?.chapter_state || {});
const chapterId = computed(() => workbench.data?.chapter_goal?.chapter_id || "");
const runPreflight = computed(() => workbench.data?.run_preflight || {
  can_run: true,
  overall_status: "ready",
  blocking_items: [],
  warning_items: [],
  context_items: [],
});
const generationSummary = computed(() => workbench.data?.generation_summary || null);
const hardQcSummary = computed(() => workbench.data?.hard_qc_summary || null);
const softQcSummary = computed(() => workbench.data?.soft_qc_summary || null);
const rewriteCounters = computed(() => workbench.data?.rewrite_counters || null);
const humanReviewSummary = computed(() => workbench.data?.human_review_summary || null);
const pendingStagedBackfillItems = computed(() =>
  (chapterState.value.staged_backfill_items || []).filter((item) => item.status === "pending"),
);
const focusedSceneId = computed(() =>
  focusTarget.value?.target_type === "scene_card" ? focusTarget.value.target_id : "",
);
const focusedHumanReviewEventId = computed(() =>
  focusTarget.value?.target_type === "human_review_event" ? focusTarget.value.target_id : "",
);
const isFocusedRunReceipt = computed(
  () => focusTarget.value?.source_type === "scene_run_receipt" && focusTarget.value?.source_id === workbench.sceneId,
);

const STATUS_LABELS = {
  ready: "就绪",
  archived: "已归档",
  pending: "待处理",
  running: "进行中",
  completed: "已完成",
  none: "无",
  blocked_waiting_backfill: "等待补写",
  manual_hold: "人工挂起",
};

const ACTION_LABELS = {
  run_backfill: "执行补写",
  run_backfill_again: "重新执行补写",
  create_tracker_now: "立即创建跟踪",
  explicit_defer_with_tracker: "明确延后并跟踪",
  mark_staged_abandoned: "标记暂存为放弃",
  run_final_aggregate: "运行最终聚合",
  set_manual_hold: "设置人工挂起",
  clear_manual_hold: "清除人工挂起",
};

const PREFLIGHT_STATUS_LABELS = {
  ready: "可以运行",
  warning: "可以运行，但建议先补充信息",
  blocked: "暂时不可运行",
};

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function formatAction(action) {
  return ACTION_LABELS[action] || action || "-";
}

function formatPreflightStatus(status) {
  return PREFLIGHT_STATUS_LABELS[status] || status || "-";
}

function resolveSceneId() {
  return requestedSceneId.value.trim() || workbench.sceneId;
}

function sceneCardTarget(sceneId = resolveSceneId()) {
  if (!sceneId) {
    return null;
  }
  return {
    target_type: "scene_card",
    target_id: sceneId,
    target_ref: `scene_card:${sceneId}`,
  };
}

function selectedStrategyFor(stageId) {
  if (!selectedStrategies.value[stageId]) {
    selectedStrategies.value[stageId] = "create_tracker_now";
  }
  return selectedStrategies.value[stageId];
}

async function loadWorkbench() {
  await workbench.refreshAll(resolveSceneId(), { force: true });
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

async function ensureWorkbenchLoaded() {
  await workbench.ensureLoaded({ sceneId: resolveSceneId() });
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

async function nextAttemptsPage() {
  await workbench.nextAttemptsPage();
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

async function previousAttemptsPage() {
  await workbench.previousAttemptsPage();
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

async function runScene() {
  try {
    const sceneId = resolveSceneId();
    const message = await workbench.runScene(sceneId);
    openTarget(sceneCardTarget(sceneId), {
      view_id: "workbench",
      source_type: "scene_run_receipt",
      source_id: sceneId,
    });
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runChapterBackfill(stageId) {
  try {
    const message = await workbench.runChapterBackfill(
      chapterId.value,
      stageId,
      selectedStrategyFor(stageId),
      resolveSceneId(),
    );
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runChapterFinalAggregate() {
  try {
    const message = await workbench.runChapterFinalAggregate(chapterId.value, resolveSceneId());
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function setManualHold() {
  try {
    const message = await workbench.setChapterManualHold(chapterId.value, manualHoldReason.value, resolveSceneId());
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function clearManualHold() {
  try {
    const message = await workbench.clearChapterManualHold(chapterId.value, resolveSceneId());
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

function handleOpenTarget(target) {
  openTarget(target);
  emit("notice", `已打开 ${target.target_ref}`);
}

watch(
  () => focusTarget.value?.target_ref,
  async () => {
    if (
      focusTarget.value?.target_type === "scene_card"
      && focusTarget.value.target_id
      && focusTarget.value.target_id !== workbench.sceneId
    ) {
      requestedSceneId.value = focusTarget.value.target_id;
      await loadWorkbench();
    }
  },
);

watch(
  () => workbench.data?.chapter_state?.manual_hold_reason,
  (value) => {
    manualHoldReason.value = value || "";
  },
  { immediate: true },
);

onActivated(() => {
  ensureWorkbenchLoaded();
});
</script>

<template>
  <section class="panel-grid" data-testid="scene-workbench-view">
    <PanelShell
      eyebrow="场景工作台"
      title="场景循环与归档"
      description="跟踪单个场景的章节意图、草稿谱系和归档状态。"
    >
      <template #actions>
        <div class="field-inline">
          <input v-model="requestedSceneId" class="control-input" data-testid="scene-id-input" />
          <button data-testid="scene-load-button" @click="loadWorkbench">读取</button>
          <button
            :disabled="workbench.actionId === 'run-scene' || !runPreflight.can_run"
            data-testid="run-full-scene-button"
            @click="runScene"
          >
            {{ workbench.actionId === "run-scene" ? "运行中..." : "运行完整场景" }}
          </button>
        </div>
      </template>

      <div v-if="workbench.loading" class="empty">正在加载场景工作台...</div>
      <template v-else-if="hasData">
        <article v-if="workbench.error" class="paper inline-error">
          <h3>最新错误</h3>
          <p>{{ workbench.error }}</p>
        </article>

        <div class="stats">
          <div class="stat">
            <span>构包</span>
            <strong>{{ workbench.data.bundle?.bundle_id || "-" }}</strong>
          </div>
          <div class="stat">
            <span>哈希</span>
            <strong>{{ workbench.data.bundle?.bundle_snapshot_hash || "-" }}</strong>
          </div>
          <div class="stat">
            <span>状态</span>
            <strong>{{ formatStatus(workbench.data.scene_run_state.scene_status) }}</strong>
          </div>
        </div>

        <article class="paper preflight-card" data-testid="scene-run-preflight-card">
          <div class="receipt-head">
            <div>
              <h3>运行前检查</h3>
              <p class="muted receipt-copy">在点击完整运行前，先确认当前场景依赖和输入状态是否到位。</p>
            </div>
            <span class="badge" data-testid="scene-run-preflight-status">
              {{ formatPreflightStatus(runPreflight.overall_status) }}
            </span>
          </div>

          <p class="muted">
            {{ runPreflight.can_run ? "当前允许执行完整场景运行。" : "当前存在真实阻塞项，完整场景运行已被禁用。" }}
          </p>

          <div
            v-if="runPreflight.blocking_items.length"
            class="preflight-group"
            data-testid="scene-run-preflight-blocking"
          >
            <h4>阻塞项</h4>
            <ProgressiveList
              :items="runPreflight.blocking_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-blocking-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item preflight-item-blocking"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <div
            v-if="runPreflight.warning_items.length"
            class="preflight-group"
            data-testid="scene-run-preflight-warning"
          >
            <h4>建议补充</h4>
            <ProgressiveList
              :items="runPreflight.warning_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-warning-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <div
            v-if="runPreflight.context_items.length"
            class="preflight-group"
            data-testid="scene-run-preflight-context"
          >
            <h4>章节上下文</h4>
            <ProgressiveList
              :items="runPreflight.context_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-context-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <p
            v-if="!runPreflight.blocking_items.length && !runPreflight.warning_items.length && !runPreflight.context_items.length"
            class="muted"
          >
            当前没有预检提示，可以直接执行完整场景运行。
          </p>
        </article>

        <article
          v-if="workbench.lastRunResult"
          class="paper receipt-card"
          data-testid="scene-run-receipt"
          :class="{ 'focused-card': isFocusedRunReceipt }"
        >
          <div class="receipt-head">
            <div>
              <h3>运行回执</h3>
              <p class="muted receipt-copy">面板刷新前捕获的最近一次流水线返回结果。</p>
            </div>
            <span class="badge">完整运行</span>
          </div>
          <div class="receipt-grid">
            <p><strong>状态</strong><br />{{ formatStatus(workbench.lastRunResult.scene_status) }}</p>
            <p><strong>构包</strong><br />{{ workbench.lastRunResult.current_bundle_id || "-" }}</p>
            <p><strong>哈希</strong><br />{{ workbench.lastRunResult.current_bundle_hash || "-" }}</p>
            <p><strong>最终场景</strong><br />{{ workbench.lastRunResult.current_final_scene_row_id || "-" }}</p>
          </div>
          <div class="card-actions">
            <button
              class="ghost"
              @click="handleOpenTarget({
                ...sceneCardTarget(),
                source_type: 'scene_run_receipt',
                source_id: workbench.sceneId,
                view_id: 'workbench',
              })"
            >
              打开场景卡片
            </button>
          </div>
        </article>

        <div class="workbench-columns" data-testid="scene-workbench-summary-row">
          <GenerationSummaryCard
            data-testid="scene-generation-summary-card"
            :summary="generationSummary"
          />
          <QcReportCard
            data-testid="scene-qc-report-card"
            :hard-summary="hardQcSummary"
            :soft-summary="softQcSummary"
            :rewrite-counters="rewriteCounters"
            :human-review-summary="humanReviewSummary"
          />
        </div>

        <div class="workbench-columns">
          <article
            class="paper"
            data-testid="scene-workbench-scene-card"
            :class="{ 'focused-card': (focusedSceneId && workbench.data.scene_card.scene_id === focusedSceneId) || isFocusedRunReceipt }"
          >
            <h3>章节 / 场景</h3>
            <p><strong>{{ workbench.data.chapter_goal.chapter_goal }}</strong></p>
            <p>{{ workbench.data.scene_card.scene_goal }}</p>
            <p class="muted">地点：{{ workbench.data.scene_card.location || "-" }}</p>
            <p class="muted">必须包含：{{ workbench.data.scene_card.must_include_text || "-" }}</p>
          </article>
          <article class="paper">
            <h3>草稿谱系</h3>
            <p><strong>中性稿</strong><br />{{ workbench.data.neutral_draft?.content || "-" }}</p>
            <p><strong>风格稿</strong><br />{{ workbench.data.style_draft?.content || "-" }}</p>
            <p><strong>定稿</strong><br />{{ workbench.data.final_scene?.content || "-" }}</p>
          </article>
          <article class="paper">
            <h3>归档 / 门控</h3>
            <p><strong>场景记忆</strong><br />{{ workbench.data.scene_memory?.content || "-" }}</p>
            <p class="muted">待补写：{{ workbench.data.chapter_state.chapter_backfill_pending_count }}</p>
            <p class="muted">聚合门控：{{ formatStatus(workbench.data.chapter_state.aggregate_block_reason) }}</p>
            <p class="muted">人工挂起：{{ workbench.data.chapter_state.manual_hold_reason || "-" }}</p>
            <p class="muted">最终记忆行：{{ workbench.data.chapter_state.last_final_memory_row_id || "-" }}</p>

            <div class="chapter-runtime-section">
              <h4>待处理补写</h4>
              <ProgressiveList
                v-if="pendingStagedBackfillItems.length"
                class="chapter-backfill-list"
                :items="pendingStagedBackfillItems"
                :initial-count="4"
                :batch-size="4"
                :threshold="4"
                test-id="chapter-backfill-progressive-list"
              >
                <template #default="{ items }">
                  <article
                    v-for="item in items"
                    :key="item.stage_id"
                    class="chapter-backfill-item"
                    :data-testid="`chapter-backfill-item-${item.stage_id}`"
                  >
                  <p><strong>{{ item.marker_text }}</strong></p>
                  <p class="muted">标记 {{ item.marker_id }} / 阶段 {{ item.stage_id }}</p>
                  <div class="field-inline">
                    <select
                      :data-testid="`chapter-backfill-strategy-${item.stage_id}`"
                      :value="selectedStrategyFor(item.stage_id)"
                      @change="selectedStrategies[item.stage_id] = $event.target.value"
                    >
                      <option value="create_tracker_now">立即创建跟踪</option>
                      <option value="run_backfill_again">重新执行补写</option>
                      <option value="explicit_defer_with_tracker">明确延后并跟踪</option>
                      <option value="mark_staged_abandoned">标记暂存为放弃</option>
                    </select>
                    <button
                      :disabled="workbench.actionId === `chapter-backfill:${item.stage_id}`"
                      :data-testid="`chapter-backfill-run-${item.stage_id}`"
                      @click="runChapterBackfill(item.stage_id)"
                    >
                      {{ workbench.actionId === `chapter-backfill:${item.stage_id}` ? "执行中..." : "执行" }}
                    </button>
                  </div>
                  </article>
                </template>
              </ProgressiveList>
              <p v-else class="muted" data-testid="chapter-backfill-empty">当前没有待处理的暂存补写。</p>
            </div>

            <div class="chapter-runtime-section">
              <h4>章节操作</h4>
              <div class="field-inline">
                <button
                  :disabled="workbench.actionId === 'chapter-final-aggregate'"
                  data-testid="chapter-final-aggregate-button"
                  @click="runChapterFinalAggregate"
                >
                  {{ workbench.actionId === "chapter-final-aggregate" ? "聚合中..." : "运行最终聚合" }}
                </button>
              </div>
              <div class="field-inline chapter-manual-hold-controls">
                <input
                  v-model="manualHoldReason"
                  class="control-input"
                  data-testid="chapter-manual-hold-reason-input"
                  placeholder="人工挂起原因"
                />
                <button
                  :disabled="workbench.actionId === 'chapter-manual-hold-set'"
                  data-testid="chapter-manual-hold-set-button"
                  @click="setManualHold"
                >
                  {{ workbench.actionId === "chapter-manual-hold-set" ? "保存中..." : "设置挂起" }}
                </button>
                <button
                  class="ghost"
                  :disabled="workbench.actionId === 'chapter-manual-hold-clear'"
                  data-testid="chapter-manual-hold-clear-button"
                  @click="clearManualHold"
                >
                  {{ workbench.actionId === "chapter-manual-hold-clear" ? "清除中..." : "清除挂起" }}
                </button>
              </div>
            </div>

            <article
              v-if="workbench.lastChapterActionResult"
              class="paper mini receipt-card chapter-receipt"
              data-testid="chapter-action-receipt"
            >
              <div class="receipt-head">
                <div>
                  <h4>章节操作回执</h4>
                  <p class="muted receipt-copy">最近一次章节运行时操作及返回回执。</p>
                </div>
                <span class="badge">{{ formatAction(workbench.lastChapterActionResult.action) }}</span>
              </div>
              <p class="muted">章节 {{ workbench.lastChapterActionResult.chapter_id }}</p>
              <p v-if="workbench.lastChapterActionResult.stage_id" class="muted">
                阶段 {{ workbench.lastChapterActionResult.stage_id }}
              </p>
              <p v-if="workbench.lastChapterActionResult.strategy" class="muted">
                策略 {{ formatAction(workbench.lastChapterActionResult.strategy) }}
              </p>
              <p v-if="workbench.lastChapterActionResult.reason" class="muted">
                原因 {{ workbench.lastChapterActionResult.reason }}
              </p>
              <p v-if="workbench.lastChapterActionResult.chapter_memory_row_id" class="muted">
                最终记忆 {{ workbench.lastChapterActionResult.chapter_memory_row_id }}
              </p>
              <p v-if="workbench.lastChapterActionResult.status" class="muted">
                状态 {{ formatStatus(workbench.lastChapterActionResult.status) }}
              </p>
            </article>
          </article>
        </div>

        <LazySection
          :key="`bundle-provenance-${workbench.data.bundle?.bundle_id || workbench.sceneId}`"
          title="包谱系"
          toggle-test-id="scene-toggle-bundle-provenance"
        >
          <BundleProvenanceCard :snapshot="workbench.data.bundle?.snapshot" />
        </LazySection>
      </template>
      <div v-else-if="workbench.error" class="empty">{{ workbench.error }}</div>
      <div v-else class="empty">输入场景 ID 后即可加载工作台。</div>
    </PanelShell>

    <PanelShell eyebrow="尝试时间线" title="执行轨迹">
      <AttemptTimeline :items="workbench.attempts" />
      <CursorPager
        test-id-prefix="attempts-pager"
        :pagination="workbench.attemptPagination"
        :can-previous="Boolean(workbench.attemptCursorStack.length)"
        :can-next="Boolean(workbench.attemptPagination?.has_next)"
        :disabled="workbench.attemptLoading"
        @previous="previousAttemptsPage"
        @next="nextAttemptsPage"
      />
    </PanelShell>

    <PanelShell eyebrow="人工审核抽屉" title="人工回流">
      <HumanReviewDrawer
        :items="workbench.humanReviewItems"
        :focus-event-id="focusedHumanReviewEventId"
        @open-target="handleOpenTarget"
      />
    </PanelShell>
  </section>
</template>
