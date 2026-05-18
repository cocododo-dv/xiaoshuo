<script setup>
import BaseButton from "./base/BaseButton.vue";
import { useNextStep } from "../composables/useNextStep";
import { WRITER_PATH_STATUS_LABELS } from "../composables/useWriterPathProgress";

const {
  items,
  status,
  headline,
  writerMotivation,
  journeyPhase,
  summaryText,
  nextActionText,
  ctaLabel,
  ctaDisabled,
  go,
  navigateToItem,
} = useNextStep();

const PHASE_STEPS = [
  { key: "构思", label: "构思", number: 1 },
  { key: "起草", label: "起草", number: 2 },
  { key: "打磨", label: "打磨", number: 3 },
];

function phaseStatus(phaseKey) {
  const idx = PHASE_STEPS.findIndex((s) => s.key === phaseKey);
  const currentIdx = PHASE_STEPS.findIndex((s) => s.key === journeyPhase.value);
  if (currentIdx === -1) return "todo";
  if (idx < currentIdx) return "done";
  if (idx === currentIdx) return "active";
  return "todo";
}

// Phase index maps 1:1 onto the first three core path items
// (0 → snowflake-workbench / 1 → writer-flow / 2 → writer-room). Navigate to
// the phase's own canonical view rather than its dynamic handoff target so the
// breadcrumb behaves like a breadcrumb (predictable destination per step).
function goToPhase(idx) {
  const item = items.value[idx];
  if (item) {
    navigateToItem(item.viewId);
  }
}

function statusLabel(value) {
  return WRITER_PATH_STATUS_LABELS[value] || value || "正在进行";
}

function isOptionalItem(item) {
  return item.viewId === "reference" || item.viewId === "review";
}
</script>

<template>
  <section class="writer-path-progress" data-testid="writer-path-progress" aria-label="创作旅程引导">
    <div class="journey-breadcrumb" data-testid="journey-breadcrumb">
      <nav class="journey-main-path" aria-label="创作旅程">
        <button
          v-for="(step, idx) in PHASE_STEPS"
          :key="step.key"
          type="button"
          class="journey-dot-group"
          :class="phaseStatus(step.key)"
          :aria-current="phaseStatus(step.key) === 'active' ? 'step' : undefined"
          :data-testid="`journey-step-${step.key}`"
          @click="goToPhase(idx)"
        >
          <span class="journey-dot" :class="phaseStatus(step.key)">
            <span v-if="phaseStatus(step.key) === 'done'">&#10003;</span>
            <span v-else>{{ step.number }}</span>
          </span>
          <span class="journey-dot-label">{{ step.label }}</span>
        </button>
      </nav>
      <div class="journey-optional">
        <button
          v-for="item in items.filter(isOptionalItem)"
          :key="item.viewId"
          type="button"
          class="journey-optional-tag"
          :class="{ attention: item.status === 'blocked' }"
          :data-testid="`journey-optional-${item.viewId}`"
          @click="navigateToItem(item)"
        >
          {{ item.label }}
          <span v-if="item.status === 'blocked'" class="journey-optional-badge">!</span>
          <span v-if="item.viewId === 'reference'" class="journey-optional-hint">随时可做</span>
        </button>
      </div>
    </div>

    <div class="writer-path-guide" :class="`writer-path-${status}`">
      <div class="writer-path-guide-top">
        <span class="writer-path-stage">{{ journeyPhase }}阶段</span>
        <span class="writer-path-status">{{ statusLabel(status) }}</span>
      </div>

      <p class="writer-path-headline">
        <strong>{{ headline }}</strong>
      </p>

      <p v-if="writerMotivation" class="writer-path-motivation">
        {{ writerMotivation }}
      </p>

      <p
        class="writer-path-active-summary"
        data-testid="writer-path-active-summary"
        role="status"
        aria-live="polite"
      >
        <span v-if="summaryText">{{ summaryText }} </span>{{ nextActionText }}
      </p>

      <div class="writer-path-guide-cta">
        <BaseButton
          variant="primary"
          data-testid="writer-path-go"
          block
          :loading="status === 'running'"
          :disabled="ctaDisabled"
          @click="go"
        >
          {{ ctaLabel }}
        </BaseButton>
      </div>
    </div>
  </section>
</template>

<style scoped>
.journey-breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.65rem 1rem;
  border: 1px solid rgba(47, 111, 98, 0.14);
  border-radius: var(--radius-panel, 8px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 72%, transparent);
}

.journey-main-path {
  display: flex;
  align-items: center;
  gap: 0;
}

.journey-dot-group {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  appearance: none;
  margin: 0;
  padding: 0.2rem 0.3rem;
  border: 0;
  border-radius: var(--radius-control, 8px);
  background: none;
  font: inherit;
  color: inherit;
  text-align: inherit;
  cursor: pointer;
}

.journey-dot-group:hover .journey-dot-label {
  color: var(--color-primary-strong, #24564d);
}

.journey-dot-group:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring, 0 0 0 3px rgba(163, 63, 47, 0.15));
}

.journey-dot-group:not(:last-child)::after {
  content: "";
  display: block;
  width: 2rem;
  height: 2px;
  margin: 0 0.35rem;
  background: rgba(47, 111, 98, 0.18);
  border-radius: 1px;
}

.journey-dot-group.done:not(:last-child)::after {
  background: rgba(47, 111, 98, 0.5);
}

.journey-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 50%;
  font-size: 0.72rem;
  font-weight: 800;
  border: 2px solid rgba(47, 111, 98, 0.22);
  background: #fff;
  color: rgba(47, 111, 98, 0.5);
}

.journey-dot.active {
  border-color: var(--color-primary, #2f6f62);
  background: var(--color-primary, #2f6f62);
  color: #fff;
}

.journey-dot.done {
  border-color: var(--color-primary, #2f6f62);
  background: rgba(47, 111, 98, 0.12);
  color: var(--color-primary, #2f6f62);
}

.journey-dot-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: rgba(37, 51, 66, 0.55);
}

.journey-dot-group.active .journey-dot-label {
  color: var(--color-primary-strong, #24564d);
}

.journey-dot-group.done .journey-dot-label {
  color: var(--color-primary, #2f6f62);
}

.journey-optional {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.journey-optional-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.6rem;
  border: 1px solid rgba(47, 111, 98, 0.14);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  color: rgba(37, 51, 66, 0.6);
  font-size: 0.74rem;
  font-weight: 600;
  cursor: pointer;
}

.journey-optional-tag:hover {
  border-color: rgba(47, 111, 98, 0.3);
  background: rgba(47, 111, 98, 0.06);
}

.journey-optional-tag.attention {
  border-color: rgba(159, 63, 50, 0.28);
  color: var(--color-danger, #9f3f32);
}

.journey-optional-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border-radius: 50%;
  background: var(--color-danger, #9f3f32);
  color: #fff;
  font-size: 0.62rem;
  font-weight: 800;
}

.journey-optional-hint {
  color: rgba(37, 51, 66, 0.4);
  font-size: 0.68rem;
  font-weight: 400;
}

.writer-path-guide {
  display: grid;
  gap: 0.45rem;
  padding: 0.95rem 1.05rem;
  border: 1px solid rgba(47, 111, 98, 0.22);
  border-left: 4px solid var(--color-primary, #2f6f62);
  border-radius: var(--radius-panel, 8px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 74%, transparent);
}

.writer-path-guide.writer-path-blocked {
  border-color: rgba(159, 63, 50, 0.26);
  border-left-color: var(--color-danger, #9f3f32);
}

.writer-path-guide.writer-path-running {
  border-color: rgba(63, 125, 134, 0.26);
  border-left-color: var(--teal, #3f7d86);
}

.writer-path-guide.writer-path-todo {
  border-color: rgba(140, 103, 43, 0.24);
  border-left-color: var(--color-warning, #8c672b);
}

.writer-path-guide-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  min-width: 0;
}

.writer-path-stage {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  padding: 0.16rem 0.5rem;
  border-radius: 999px;
  background: rgba(47, 111, 98, 0.12);
  color: var(--color-primary-strong, #24564d);
  font-size: 0.74rem;
  font-weight: 700;
  letter-spacing: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.writer-path-status {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  min-height: 1.6rem;
  padding: 0.18rem 0.48rem;
  border: 1px solid rgba(37, 51, 66, 0.1);
  border-radius: 999px;
  background: rgba(37, 51, 66, 0.08);
  color: rgba(37, 51, 66, 0.76);
  font-size: 0.75rem;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
}

.writer-path-running .writer-path-status {
  background: rgba(63, 125, 134, 0.12);
  color: #285b63;
}

.writer-path-blocked .writer-path-status {
  background: rgba(159, 63, 50, 0.12);
  color: #7c3329;
}

.writer-path-done .writer-path-status {
  background: rgba(47, 111, 98, 0.13);
  color: var(--color-primary-strong, #24564d);
}

.writer-path-todo .writer-path-status {
  background: rgba(140, 103, 43, 0.12);
  color: #72521f;
}

.writer-path-headline {
  margin: 0;
  min-width: 0;
}

.writer-path-headline strong {
  color: var(--surface-text, #1b1815);
  font-size: 1.08rem;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.writer-path-motivation {
  margin: 0;
  color: color-mix(in srgb, var(--color-primary, #2f6f62) 82%, #1b1815);
  font-size: 0.86rem;
  line-height: 1.5;
  font-style: italic;
}

.writer-path-active-summary {
  margin: 0;
  color: var(--surface-muted, rgba(37, 51, 66, 0.62));
  font-size: 0.84rem;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.writer-path-guide-cta {
  display: flex;
  margin-top: 0.3rem;
}

@media (max-width: 768px) {
  .journey-breadcrumb {
    flex-direction: column;
    align-items: flex-start;
  }

  .writer-path-guide-top {
    flex-wrap: wrap;
  }

  .journey-dot-group:not(:last-child)::after {
    width: 1.2rem;
    margin: 0 0.2rem;
  }
}
</style>
