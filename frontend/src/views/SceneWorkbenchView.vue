<script setup>
import { computed, onMounted, ref } from "vue";

import AttemptTimeline from "../components/AttemptTimeline.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import PanelShell from "../components/PanelShell.vue";
import { useWorkbenchStore } from "../stores/workbench";

const emit = defineEmits(["notice"]);

const workbench = useWorkbenchStore();
const requestedSceneId = ref(workbench.sceneId);

const hasData = computed(() => Boolean(workbench.data));

async function loadWorkbench() {
  await workbench.refreshAll(requestedSceneId.value.trim() || workbench.sceneId);
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

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
        </div>
      </template>

      <div v-if="workbench.loading" class="empty">Loading workbench...</div>
      <div v-else-if="workbench.error" class="empty">{{ workbench.error }}</div>
      <template v-else-if="hasData">
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

        <div class="workbench-columns">
          <article class="paper">
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
      </template>
      <div v-else class="empty">Enter a scene ID to load the workbench.</div>
    </PanelShell>

    <PanelShell eyebrow="Attempt Timeline" title="Execution trail">
      <AttemptTimeline :items="workbench.data?.attempts || []" />
    </PanelShell>

    <PanelShell eyebrow="Human Review Drawer" title="Manual backflow">
      <HumanReviewDrawer :items="workbench.humanReviewItems.slice(0, 3)" />
    </PanelShell>
  </section>
</template>
