<script setup>
import { ref } from "vue";
import { Bot, MessageSquare, Save } from "lucide-vue-next";

import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { patchKeyListLabel, sourceLabel, stepKeyLabel } from "../lib/snowflakeDisplay";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const store = useSnowflakeWorkbenchStore();
const assistantInput = ref("");
const SNOWFLAKE_ASSISTANT_SCOPE = "snowflake:assistant";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

async function requestAssistant() {
  if (!assistantInput.value.trim()) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: SNOWFLAKE_ASSISTANT_SCOPE,
    actionLabel: "请求助手建议",
    runningMessage: "常驻助手正在基于当前草稿给建议...",
    successMessage: () => store.lastActionMessage || "助手建议已返回。",
    nextStep: () => "下一步：采纳候选补丁，或继续手动编辑当前草稿。",
    action: () => store.requestAssistant(assistantInput.value),
  });
  if (result) {
    assistantInput.value = "";
  }
}

async function quickAssistant(message) {
  if (!message || (!store.currentStep && !store.selectedTriageItem)) {
    return;
  }
  await runFlowAction({
    scopeKey: SNOWFLAKE_ASSISTANT_SCOPE,
    actionLabel: "请求快捷建议",
    runningMessage: "正在分析当前上下文...",
    successMessage: () => store.lastActionMessage || "快捷建议已返回。",
    nextStep: () => "下一步：采纳候选或继续补字段。",
    action: () => store.requestAssistant(message),
  });
}

function applyAssistantCandidate(reply) {
  store.applyAssistantCandidate(reply);
  emit("notice", "助手候选已应用到当前草稿，但还未保存。");
}
</script>

<template>
  <aside class="snowflake-assistant-panel" data-testid="snowflake-assistant-panel">
    <div class="panel-head">
      <div>
        <span class="eyebrow">助手</span>
        <h2>常驻助手</h2>
      </div>
      <Bot :size="18" />
    </div>

    <div class="assistant-quick-actions">
      <button
        type="button"
        class="ghost mini-btn"
        :disabled="!store.project || !store.currentStep || store.actionId === 'assistant'"
        @click="quickAssistant('请分析当前雪花步骤的优点、缺口和下一步修法。')"
      >
        分析此步
      </button>
      <button
        type="button"
        class="ghost mini-btn"
        :disabled="!store.project || !store.currentStep || store.actionId === 'assistant'"
        @click="quickAssistant('请强化当前草稿，让目标、冲突、代价和读者承诺更具体。')"
      >
        强化当前稿
      </button>
      <button
        type="button"
        class="ghost mini-btn"
        :disabled="!store.project || !store.currentStep || store.actionId === 'assistant'"
        @click="quickAssistant('请给出一个可应用到当前步骤的候选补丁。')"
      >
        候选补丁
      </button>
    </div>
    <FlowActionReceipt compact :receipt="receipt(SNOWFLAKE_ASSISTANT_SCOPE)" />

    <div class="assistant-thread">
      <article v-for="(reply, index) in store.assistantReplies" :key="`${reply.step_key}-${index}`" class="assistant-card">
        <div class="assistant-card-head">
          <strong>{{ stepKeyLabel(reply.step_key) }}</strong>
          <small>{{ sourceLabel(reply.source) }}</small>
        </div>
        <p>{{ reply.reply }}</p>
        <ul v-if="reply.suggestions?.length" class="assistant-list">
          <li v-for="(suggestion, suggestionIndex) in reply.suggestions" :key="`${index}-${suggestionIndex}`">
            {{ suggestion }}
          </li>
        </ul>
        <p v-if="reply.candidate_label" class="assistant-candidate-label">{{ reply.candidate_label }}</p>
        <p v-if="reply.candidate_patch" class="muted">可应用修改：{{ patchKeyListLabel(reply.candidate_patch) }}</p>
        <button
          v-if="reply.candidate_patch"
          type="button"
          class="ghost mini-btn"
          @click="applyAssistantCandidate(reply)"
        >
          <Save :size="14" />
          <span>应用候选到当前草稿</span>
        </button>
      </article>
      <p v-if="!store.assistantReplies.length" class="muted">
        在任一步骤里问它"哪里还不够尖"，它就会基于当前雪花上下文给建议。
      </p>
    </div>

    <label class="field-block">
      <span>想让助手看什么</span>
      <textarea
        v-model="assistantInput"
        class="control-input"
        placeholder="比如：这个目标读者定位还可以更尖一点吗？"
      />
    </label>
    <button
      type="button"
      class="primary action-btn"
      :disabled="!store.project || !assistantInput.trim() || store.actionId === 'assistant'"
      @click="requestAssistant"
    >
      <MessageSquare :size="16" />
      <span>请求建议</span>
    </button>
  </aside>
</template>
