import { computed, ref } from "vue";

export const UI_MODE_STORAGE_KEY = "novel-system:ui-mode";

const VALID_MODES = new Set(["guided", "advanced"]);

function readStoredMode() {
  if (typeof window === "undefined" || !window.localStorage) {
    return "guided";
  }
  const stored = window.localStorage.getItem(UI_MODE_STORAGE_KEY);
  return VALID_MODES.has(stored) ? stored : "guided";
}

const uiMode = ref(readStoredMode());

function persistMode(mode) {
  if (typeof window === "undefined" || !window.localStorage) {
    return;
  }
  window.localStorage.setItem(UI_MODE_STORAGE_KEY, mode);
}

export function useUiMode() {
  const isAdvancedMode = computed(() => uiMode.value === "advanced");

  function setUiMode(nextMode) {
    const normalized = VALID_MODES.has(nextMode) ? nextMode : "guided";
    uiMode.value = normalized;
    persistMode(normalized);
  }

  function toggleUiMode() {
    setUiMode(isAdvancedMode.value ? "guided" : "advanced");
  }

  return {
    uiMode,
    isAdvancedMode,
    setUiMode,
    toggleUiMode,
  };
}
