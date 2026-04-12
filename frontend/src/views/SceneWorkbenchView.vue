<script setup>
import { computed, onMounted, ref, watch } from "vue";

import AttemptTimeline from "../components/AttemptTimeline.vue";
import BundleProvenanceCard from "../components/BundleProvenanceCard.vue";
import CursorPager from "../components/CursorPager.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import PanelShell from "../components/PanelShell.vue";
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
  await workbench.refreshAll(resolveSceneId());
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
  emit("notice", `Opened ${target.target_ref}`);
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

onMounted(() => {
  loadWorkbench();
});
</script>

<template>
  <section class="panel-grid" data-testid="scene-workbench-view">
    <PanelShell
      eyebrow="Scene Workbench"
      title="Scene loop and archive"
      description="Track chapter intent, draft lineage, and archive state for a single scene."
    >
      <template #actions>
        <div class="field-inline">
          <input v-model="requestedSceneId" class="control-input" data-testid="scene-id-input" />
          <button data-testid="scene-load-button" @click="loadWorkbench">Load</button>
          <button :disabled="workbench.actionId === 'run-scene'" data-testid="run-full-scene-button" @click="runScene">
            {{ workbench.actionId === "run-scene" ? "Running..." : "Run Full Scene" }}
          </button>
        </div>
      </template>

      <div v-if="workbench.loading" class="empty">Loading workbench...</div>
      <template v-else-if="hasData">
        <article v-if="workbench.error" class="paper inline-error">
          <h3>Latest Error</h3>
          <p>{{ workbench.error }}</p>
        </article>

        <div class="stats">
          <div class="stat">
            <span>Bundle</span>
            <strong>{{ workbench.data.bundle?.bundle_id || "-" }}</strong>
          </div>
          <div class="stat">
            <span>Hash</span>
            <strong>{{ workbench.data.bundle?.bundle_snapshot_hash || "-" }}</strong>
          </div>
          <div class="stat">
            <span>Status</span>
            <strong>{{ workbench.data.scene_run_state.scene_status || "-" }}</strong>
          </div>
        </div>

        <article
          v-if="workbench.lastRunResult"
          class="paper receipt-card"
          data-testid="scene-run-receipt"
          :class="{ 'focused-card': isFocusedRunReceipt }"
        >
          <div class="receipt-head">
            <div>
              <h3>Run Receipt</h3>
              <p class="muted receipt-copy">Latest pipeline response captured before the board refresh.</p>
            </div>
            <span class="badge">run/full</span>
          </div>
          <div class="receipt-grid">
            <p><strong>Status</strong><br />{{ workbench.lastRunResult.scene_status || "-" }}</p>
            <p><strong>Bundle</strong><br />{{ workbench.lastRunResult.current_bundle_id || "-" }}</p>
            <p><strong>Hash</strong><br />{{ workbench.lastRunResult.current_bundle_hash || "-" }}</p>
            <p><strong>Final Scene</strong><br />{{ workbench.lastRunResult.current_final_scene_row_id || "-" }}</p>
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
              Open Scene Card
            </button>
          </div>
        </article>

        <div class="workbench-columns">
          <article
            class="paper"
            data-testid="scene-workbench-scene-card"
            :class="{ 'focused-card': (focusedSceneId && workbench.data.scene_card.scene_id === focusedSceneId) || isFocusedRunReceipt }"
          >
            <h3>Chapter / Scene</h3>
            <p><strong>{{ workbench.data.chapter_goal.chapter_goal }}</strong></p>
            <p>{{ workbench.data.scene_card.scene_goal }}</p>
            <p class="muted">Location: {{ workbench.data.scene_card.location || "-" }}</p>
            <p class="muted">Must include: {{ workbench.data.scene_card.must_include_text || "-" }}</p>
          </article>
          <article class="paper">
            <h3>Draft Lineage</h3>
            <p><strong>Neutral</strong><br />{{ workbench.data.neutral_draft?.content || "-" }}</p>
            <p><strong>Style</strong><br />{{ workbench.data.style_draft?.content || "-" }}</p>
            <p><strong>Final</strong><br />{{ workbench.data.final_scene?.content || "-" }}</p>
          </article>
          <article class="paper">
            <h3>Archive / Gate</h3>
            <p><strong>Scene Memory</strong><br />{{ workbench.data.scene_memory?.content || "-" }}</p>
            <p class="muted">
              Backfill pending: {{ workbench.data.chapter_state.chapter_backfill_pending_count }}
            </p>
            <p class="muted">Aggregate gate: {{ workbench.data.chapter_state.aggregate_block_reason }}</p>
            <p class="muted">Manual hold: {{ workbench.data.chapter_state.manual_hold_reason || "-" }}</p>
            <p class="muted">Final memory row: {{ workbench.data.chapter_state.last_final_memory_row_id || "-" }}</p>

            <div class="chapter-runtime-section">
              <h4>Pending Backfill</h4>
              <div v-if="pendingStagedBackfillItems.length" class="chapter-backfill-list">
                <article
                  v-for="item in pendingStagedBackfillItems"
                  :key="item.stage_id"
                  class="chapter-backfill-item"
                  :data-testid="`chapter-backfill-item-${item.stage_id}`"
                >
                  <p><strong>{{ item.marker_text }}</strong></p>
                  <p class="muted">Marker {{ item.marker_id }} · {{ item.stage_id }}</p>
                  <div class="field-inline">
                    <select
                      :data-testid="`chapter-backfill-strategy-${item.stage_id}`"
                      :value="selectedStrategyFor(item.stage_id)"
                      @change="selectedStrategies[item.stage_id] = $event.target.value"
                    >
                      <option value="create_tracker_now">create_tracker_now</option>
                      <option value="run_backfill_again">run_backfill_again</option>
                      <option value="explicit_defer_with_tracker">explicit_defer_with_tracker</option>
                      <option value="mark_staged_abandoned">mark_staged_abandoned</option>
                    </select>
                    <button
                      :disabled="workbench.actionId === `chapter-backfill:${item.stage_id}`"
                      :data-testid="`chapter-backfill-run-${item.stage_id}`"
                      @click="runChapterBackfill(item.stage_id)"
                    >
                      {{ workbench.actionId === `chapter-backfill:${item.stage_id}` ? "Running..." : "Run" }}
                    </button>
                  </div>
                </article>
              </div>
              <p v-else class="muted" data-testid="chapter-backfill-empty">No pending staged backfill.</p>
            </div>

            <div class="chapter-runtime-section">
              <h4>Chapter Ops</h4>
              <div class="field-inline">
                <button
                  :disabled="workbench.actionId === 'chapter-final-aggregate'"
                  data-testid="chapter-final-aggregate-button"
                  @click="runChapterFinalAggregate"
                >
                  {{ workbench.actionId === "chapter-final-aggregate" ? "Aggregating..." : "Run Final Aggregate" }}
                </button>
              </div>
              <div class="field-inline chapter-manual-hold-controls">
                <input
                  v-model="manualHoldReason"
                  class="control-input"
                  data-testid="chapter-manual-hold-reason-input"
                  placeholder="Manual hold reason"
                />
                <button
                  :disabled="workbench.actionId === 'chapter-manual-hold-set'"
                  data-testid="chapter-manual-hold-set-button"
                  @click="setManualHold"
                >
                  {{ workbench.actionId === "chapter-manual-hold-set" ? "Saving..." : "Set Hold" }}
                </button>
                <button
                  class="ghost"
                  :disabled="workbench.actionId === 'chapter-manual-hold-clear'"
                  data-testid="chapter-manual-hold-clear-button"
                  @click="clearManualHold"
                >
                  {{ workbench.actionId === "chapter-manual-hold-clear" ? "Clearing..." : "Clear Hold" }}
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
                  <h4>Chapter Action Receipt</h4>
                  <p class="muted receipt-copy">Latest chapter runtime action and returned receipt.</p>
                </div>
                <span class="badge">{{ workbench.lastChapterActionResult.action }}</span>
              </div>
              <p class="muted">Chapter {{ workbench.lastChapterActionResult.chapter_id }}</p>
              <p v-if="workbench.lastChapterActionResult.stage_id" class="muted">
                Stage {{ workbench.lastChapterActionResult.stage_id }}
              </p>
              <p v-if="workbench.lastChapterActionResult.strategy" class="muted">
                Strategy {{ workbench.lastChapterActionResult.strategy }}
              </p>
              <p v-if="workbench.lastChapterActionResult.reason" class="muted">
                Reason {{ workbench.lastChapterActionResult.reason }}
              </p>
              <p v-if="workbench.lastChapterActionResult.chapter_memory_row_id" class="muted">
                Final {{ workbench.lastChapterActionResult.chapter_memory_row_id }}
              </p>
              <p v-if="workbench.lastChapterActionResult.status" class="muted">
                Status {{ workbench.lastChapterActionResult.status }}
              </p>
            </article>
          </article>
        </div>

        <BundleProvenanceCard :snapshot="workbench.data.bundle?.snapshot" />
      </template>
      <div v-else-if="workbench.error" class="empty">{{ workbench.error }}</div>
      <div v-else class="empty">Enter a scene ID to load the workbench.</div>
    </PanelShell>

    <PanelShell eyebrow="Attempt Timeline" title="Execution trail">
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

    <PanelShell eyebrow="Human Review Drawer" title="Manual backflow">
      <HumanReviewDrawer
        :items="workbench.humanReviewItems"
        :focus-event-id="focusedHumanReviewEventId"
        @open-target="handleOpenTarget"
      />
    </PanelShell>
  </section>
</template>
