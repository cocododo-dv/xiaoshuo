<script setup>
import { onMounted } from "vue";

import AliasScopeCard from "../components/AliasScopeCard.vue";
import PanelShell from "../components/PanelShell.vue";
import { useIndexConsoleStore } from "../stores/indexConsole";

const emit = defineEmits(["notice"]);

const indexConsole = useIndexConsoleStore();

async function refreshIndex() {
  await indexConsole.load();
  if (indexConsole.error) {
    emit("notice", indexConsole.error);
  }
}

async function runRecovery() {
  try {
    emit("notice", await indexConsole.runRecovery());
  } catch (error) {
    emit("notice", error.message);
  }
}

async function retry(jobId) {
  try {
    emit("notice", await indexConsole.retryVerifyJob(jobId));
  } catch (error) {
    emit("notice", error.message);
  }
}

onMounted(() => {
  refreshIndex();
});
</script>

<template>
  <section class="panel-grid">
    <PanelShell
      eyebrow="Index Console"
      title="Alias, verify, and recovery"
      description="Inspect alias scopes, verify jobs, and runtime recovery from one board."
    >
      <template #actions>
        <div class="field-inline">
          <button @click="refreshIndex">Refresh</button>
          <button @click="runRecovery">Recovery Sweep</button>
        </div>
      </template>

      <div v-if="indexConsole.loading" class="empty">Loading alias scopes...</div>
      <div v-else-if="indexConsole.error" class="empty">{{ indexConsole.error }}</div>
      <div v-else-if="!indexConsole.aliasScopes.length" class="empty">No alias scopes exist yet.</div>
      <div v-else class="alias-grid">
        <AliasScopeCard v-for="item in indexConsole.aliasScopes" :key="item.alias_scope" :item="item" />
      </div>
    </PanelShell>

    <PanelShell eyebrow="Jobs" title="Reindex / Verify">
      <div v-if="!indexConsole.jobs.length" class="empty">No index jobs are queued.</div>
      <div v-else class="job-table">
        <div v-for="item in indexConsole.jobs" :key="item.job_id" class="job-row">
          <div>
            <strong>{{ item.job_type }}</strong>
            <div class="muted">{{ item.job_id }}</div>
          </div>
          <div class="muted">{{ item.status }}</div>
          <div class="muted">{{ item.alias_scope }}</div>
          <div class="job-actions">
            <button
              v-if="item.job_type === 'verify'"
              :disabled="indexConsole.actionId === item.job_id"
              @click="retry(item.job_id)"
            >
              Retry Verify
            </button>
            <span v-else class="muted">auto built</span>
          </div>
        </div>
      </div>
    </PanelShell>
  </section>
</template>
