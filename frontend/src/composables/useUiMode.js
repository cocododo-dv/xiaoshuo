import { computed, ref } from "vue";

export const UI_MODE_STORAGE_KEY = "novel-system:ui-mode";

const VALID_MODES = new Set(["writer", "advanced"]);

function normalizeMode(mode) {
  if (mode === "guided") {
    return "writer";
  }
  return VALID_MODES.has(mode) ? mode : "writer";
}

function readStoredMode() {
  if (typeof window === "undefined" || !window.localStorage) {
    return "writer";
  }
  const stored = window.localStorage.getItem(UI_MODE_STORAGE_KEY);
  const normalized = normalizeMode(stored);
  if (stored !== normalized) {
    window.localStorage.setItem(UI_MODE_STORAGE_KEY, normalized);
  }
  return normalized;
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
    const normalized = normalizeMode(nextMode);
    uiMode.value = normalized;
    persistMode(normalized);
  }

  function toggleUiMode() {
    setUiMode(isAdvancedMode.value ? "writer" : "advanced");
  }

  return {
    uiMode,
    isAdvancedMode,
    setUiMode,
    toggleUiMode,
  };
}
