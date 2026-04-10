<script setup>
import { computed, onMounted, ref, watch } from "vue";

import AttemptTimeline from "../components/AttemptTimeline.vue";
import BundleProvenanceCard from "../components/BundleProvenanceCard.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import PanelShell from "../components/PanelShell.vue";
import { useShellRouter } from "../router";
import { useWorkbenchStore } from "../stores/workbench";

const emit = defineEmits(["notice"]);

const workbench = useWorkbenchStore();
const { focusTarget, openTarget } = useShellRouter();
const requestedSceneId = ref(workbench.sceneId);

const hasData = computed(() => Boolean(workbench.data));
const focusedSceneId = computed(() =>
  focusTarget.value?.target_type === "scene_card" ? focusTarget.value.target_id : "",
);
const focusedHumanReviewEventId = computed(() =>
  focusTarget.value?.target_type === "human_review_event" ? focusTarget.value.target_id : "",
);
const isFocusedRunReceipt = computed(
  () => focusTarget.value?.source_type === "scene_run_receipt" && focusTarget.value?.source_id === workbench.sceneId,
);

const prioritizedHumanReviewItems = computed(() => {
  const focusEventId = focusedHumanReviewEventId.value;
  const items = [...workbench.humanReviewItems].slice(0, 3);
  if (!focusEventId) {
    return items;
  }
  return items.sort((left, right) => Number(right.event_id === focusEventId) - Number(left.event_id === focusEventId));
});

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

async function loadWorkbench() {
  await workbench.refreshAll(resolveSceneId());
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

onMounted(() => {
  loadWorkbench();
});
</script>

<template>
  <section class="panel-grid">
    <PanelShell
      eyebrow="Scene Workbench"
      title="Scene loop and archive"
      description="Track chapter intent, draft lineage, and archive state for a single scene."
    >
      <template #actions>
        <div class="field-inline">
          <input v-model="requestedSceneId" class="control-input" />
          <button @click="loadWorkbench">Load</button>
          <button :disabled="workbench.actionId === 'run-scene'" @click="runScene">
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
          </article>
        </div>

        <BundleProvenanceCard :snapshot="workbench.data.bundle?.snapshot" />
      </template>
      <div v-else-if="workbench.error" class="empty">{{ workbench.error }}</div>
      <div v-else class="empty">Enter a scene ID to load the workbench.</div>
    </PanelShell>

    <PanelShell eyebrow="Attempt Timeline" title="Execution trail">
      <AttemptTimeline :items="workbench.data?.attempts || []" />
    </PanelShell>

    <PanelShell eyebrow="Human Review Drawer" title="Manual backflow">
      <HumanReviewDrawer
        :items="prioritizedHumanReviewItems"
        :focus-event-id="focusedHumanReviewEventId"
        @open-target="handleOpenTarget"
      />
    </PanelShell>
  </section>
</template>
