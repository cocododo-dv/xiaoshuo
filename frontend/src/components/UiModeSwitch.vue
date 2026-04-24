<script setup>
import { SlidersHorizontal } from "lucide-vue-next";

import { useUiMode } from "../composables/useUiMode";

const { uiMode, setUiMode } = useUiMode();
</script>

<template>
  <section class="ui-mode-switch" aria-label="界面模式">
    <div class="ui-mode-switch-head">
      <SlidersHorizontal :size="16" aria-hidden="true" />
      <span>界面模式</span>
    </div>
    <div class="ui-mode-options" role="group" aria-label="界面模式">
      <button
        type="button"
        class="ui-mode-option"
        :class="{ active: uiMode === 'writer' }"
        :aria-pressed="uiMode === 'writer'"
        data-testid="ui-mode-writer"
        @click="setUiMode('writer')"
      >
        作家
      </button>
      <button
        type="button"
        class="ui-mode-option"
        :class="{ active: uiMode === 'advanced' }"
        :aria-pressed="uiMode === 'advanced'"
        data-testid="ui-mode-advanced"
        @click="setUiMode('advanced')"
      >
        高级
      </button>
    </div>
  </section>
</template>
