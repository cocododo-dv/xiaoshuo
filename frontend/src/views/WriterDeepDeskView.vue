<script setup>
import { onActivated, onMounted } from "vue";

import DeepDeskIndex from "../components/DeepDeskIndex.vue";
import DeepDeskPatchCandidates from "../components/DeepDeskPatchCandidates.vue";
import DeepDeskQualityRail from "../components/DeepDeskQualityRail.vue";
import DeepDeskReader from "../components/DeepDeskReader.vue";
import PanelShell from "../components/PanelShell.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useShellRouter } from "../router";
import { useWriterDeepDeskStore } from "../stores/writerDeepDesk";

const emit = defineEmits(["notice"]);

const desk = useWriterDeepDeskStore();
const { navigate } = useShellRouter();

async function ensureLoaded(force = false) {
  try {
    await desk.ensureLoaded({ force });
  } catch (error) {
    emit("notice", error.message);
  }
}

async function refreshDesk() {
  await ensureLoaded(true);
}

function openManuscripts() {
  navigate("manuscripts");
}

onMounted(() => {
  ensureLoaded();
});

onActivated(() => {
  ensureLoaded();
});
</script>

<template>
  <section class="panel-grid writer-deep-desk" data-testid="writer-deep-desk">
    <WorkflowPageHeader view-id="deepdesk" />
    <PanelShell
      eyebrow="写作与深改台"
      title="职业作者日用写作舱"
      description="作者稿是第一入口：AI 可以反向提取戏剧卡、诊断、生成候选、记录偏好，但不会自动覆盖 FinalScene 或 ChapterMemory。"
    >
      <template #actions>
        <div class="field-inline deep-desk-actions">
          <button data-testid="deep-desk-refresh" :disabled="desk.loading" @click="refreshDesk">
            {{ desk.loading ? "刷新中..." : "刷新" }}
          </button>
          <button class="ghost" @click="openManuscripts">返回成稿中心</button>
        </div>
      </template>

      <div v-if="desk.loading" class="empty">正在载入写作与深改台...</div>
      <div v-else-if="desk.error" class="empty">{{ desk.error }}</div>
      <div v-else class="deep-desk-shell">
        <DeepDeskIndex @notice="emit('notice', $event)" />
        <DeepDeskReader @notice="emit('notice', $event)" />
        <DeepDeskQualityRail @notice="emit('notice', $event)" />
      </div>

      <DeepDeskPatchCandidates @notice="emit('notice', $event)" />
    </PanelShell>
  </section>
</template>

<style scoped>
.deep-desk-shell {
  display: grid;
  grid-template-columns: minmax(18rem, 21rem) minmax(0, 1fr) minmax(18rem, 22rem);
  gap: 1rem;
  align-items: start;
}

@media (max-width: 1360px) {
  .deep-desk-shell {
    grid-template-columns: 1fr;
  }
}

</style>
