<script setup>
import { PenLine, SlidersHorizontal } from "lucide-vue-next";

import { useUiMode } from "../composables/useUiMode";

const { uiMode, setUiMode } = useUiMode();
</script>

<template>
  <section class="ws-mode-switch" aria-label="界面模式">
    <div class="ws-mode-options ui-mode-options" role="group" aria-label="界面模式">
      <button
        type="button"
        class="ws-mode-btn"
        :class="{ 'is-active': uiMode === 'writer' }"
        :aria-pressed="uiMode === 'writer'"
        data-testid="ui-mode-writer"
        title="作家模式 · 只显示日常写作"
        @click="setUiMode('writer')"
      >
        <PenLine :size="15" aria-hidden="true" />
        <span>作家</span>
      </button>
      <button
        type="button"
        class="ws-mode-btn"
        :class="{ 'is-active': uiMode === 'advanced' }"
        :aria-pressed="uiMode === 'advanced'"
        data-testid="ui-mode-advanced"
        title="高级模式 · 显示生产与运维工具"
        @click="setUiMode('advanced')"
      >
        <SlidersHorizontal :size="15" aria-hidden="true" />
        <span>高级</span>
      </button>
    </div>
  </section>
</template>
