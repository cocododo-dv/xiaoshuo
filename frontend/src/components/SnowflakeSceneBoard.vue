<script setup>
import { computed, ref } from "vue";

import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { sceneFormLabel } from "../lib/snowflakeDisplay";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const store = useSnowflakeWorkbenchStore();
const selectedScenePlanId = ref("");
const SNOWFLAKE_STRUCTURE_SCOPE = "snowflake:structure";
const { runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const sceneBoard = computed(() => store.sceneBoard);
const selectedScenePlan = computed(() => {
  const scenes = sceneBoard.value?.scenes || [];
  return scenes.find((s) => s.scene_plan_id === selectedScenePlanId.value) || scenes[0] || null;
});

function scenePrimaryForm(scene) {
  return String(scene?.primary_form || scene?.scene_type || "proactive").toLowerCase() === "reactive" ? "reactive" : "proactive";
}

async function persistScenePlanField(scene, key, value) {
  if (!scene?.scene_plan_id) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "保存场景字段",
    runningMessage: "正在保存场景规划字段...",
    successMessage: () => store.lastActionMessage || "场景字段已保存。",
    nextStep: () => "下一步：继续补齐场景结构，或进入场景体检。",
    notify: false,
    action: () => store.updateScenePlan(scene.scene_plan_id, { [key]: value }),
  });
}
</script>

<template>
  <section class="snowflake-scene-board" data-testid="snowflake-scene-board">
    <div class="panel-head">
      <div>
        <span class="eyebrow">场景板</span>
        <h2>场景板</h2>
        <p class="muted">
          {{ sceneBoard.chapters?.length || 0 }} 章 · {{ sceneBoard.scenes?.length || 0 }} 场，场景列表和场景规划在这里合并编辑。
        </p>
      </div>
    </div>

    <div class="scene-board-layout">
      <div class="scene-board-table">
        <article
          v-for="scene in sceneBoard.scenes"
          :key="scene.scene_plan_id"
          class="scene-board-row"
          :class="{ active: scene.scene_plan_id === selectedScenePlan?.scene_plan_id }"
        >
          <div class="scene-board-main">
            <strong>{{ scene.title || scene.scene_id }}</strong>
            <small>{{ scene.chapter_id }} · {{ sceneFormLabel(scenePrimaryForm(scene)) }} · #{{ scene.scene_seq }}</small>
            <button type="button" class="mini-btn" @click="selectedScenePlanId = scene.scene_plan_id">详情</button>
          </div>
          <label>
            <span>摘要</span>
            <textarea class="control-input compact-textarea" :value="scene.summary || ''" @change="persistScenePlanField(scene, 'summary', $event.target.value)" />
          </label>
          <label>
            <span>坩埚</span>
            <textarea class="control-input compact-textarea" :value="scene.scene_crucible || scene.crucible || ''" @change="persistScenePlanField(scene, 'scene_crucible', $event.target.value)" />
          </label>
          <label v-if="scenePrimaryForm(scene) === 'proactive'">
            <span>目标</span>
            <textarea class="control-input compact-textarea" :value="scene.goal || ''" @change="persistScenePlanField(scene, 'goal', $event.target.value)" />
          </label>
          <label v-if="scenePrimaryForm(scene) === 'proactive'">
            <span>挫折</span>
            <textarea class="control-input compact-textarea" :value="scene.setback || ''" @change="persistScenePlanField(scene, 'setback', $event.target.value)" />
          </label>
          <label v-if="scenePrimaryForm(scene) === 'reactive'">
            <span>困境</span>
            <textarea class="control-input compact-textarea" :value="scene.dilemma || ''" @change="persistScenePlanField(scene, 'dilemma', $event.target.value)" />
          </label>
          <label>
            <span>钩子</span>
            <textarea class="control-input compact-textarea" :value="scene.hook || ''" @change="persistScenePlanField(scene, 'hook', $event.target.value)" />
          </label>
        </article>
      </div>
      <aside v-if="selectedScenePlan" class="scene-board-drawer" data-testid="snowflake-scene-board-drawer">
        <div>
          <span class="eyebrow">场景详情</span>
          <h3>{{ selectedScenePlan.title || selectedScenePlan.scene_id }}</h3>
          <p class="muted">{{ selectedScenePlan.chapter_id }} · #{{ selectedScenePlan.scene_seq }}</p>
        </div>
        <label>
          <span>视角</span>
          <input class="control-input" :value="selectedScenePlan.pov_character_id || ''" @change="persistScenePlanField(selectedScenePlan, 'pov_character_id', $event.target.value)" />
        </label>
        <label>
          <span>类型</span>
          <select class="control-input" :value="scenePrimaryForm(selectedScenePlan)" @change="persistScenePlanField(selectedScenePlan, 'primary_form', $event.target.value)">
            <option value="proactive">主动场景</option>
            <option value="reactive">反应场景</option>
          </select>
        </label>
        <label>
          <span>冲突 / 困境</span>
          <textarea
            class="control-input"
            :value="selectedScenePlan.conflict || selectedScenePlan.dilemma || ''"
            @change="persistScenePlanField(selectedScenePlan, scenePrimaryForm(selectedScenePlan) === 'reactive' ? 'dilemma' : 'conflict', $event.target.value)"
          />
        </label>
        <label>
          <span>决定 / 离场变化</span>
          <textarea
            class="control-input"
            :value="selectedScenePlan.decision || selectedScenePlan.exit_change || ''"
            @change="persistScenePlanField(selectedScenePlan, scenePrimaryForm(selectedScenePlan) === 'reactive' ? 'decision' : 'exit_change', $event.target.value)"
          />
        </label>
        <label>
          <span>目标篇幅</span>
          <input class="control-input" :value="selectedScenePlan.target_length_band || ''" @change="persistScenePlanField(selectedScenePlan, 'target_length_band', $event.target.value)" />
        </label>
      </aside>
    </div>
  </section>
</template>
