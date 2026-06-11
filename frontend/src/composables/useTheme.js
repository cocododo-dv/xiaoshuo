import { computed, ref } from "vue";

export const THEME_STORAGE_KEY = "novel-system:theme";

const THEME_ORDER = ["day", "dusk", "night"];
const THEME_ATTRS = { day: "", dusk: "sepia", night: "dark" };
export const THEME_LABELS = { day: "白昼", dusk: "暮色", night: "夜灯" };

function normalizeTheme(theme) {
  return THEME_ORDER.includes(theme) ? theme : "day";
}

function readStoredTheme() {
  if (typeof window === "undefined" || !window.localStorage) {
    return "day";
  }
  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "day";
  }
}

function applyThemeAttribute(theme) {
  if (typeof document === "undefined") {
    return;
  }
  const attr = THEME_ATTRS[theme] || "";
  if (attr) {
    document.documentElement.setAttribute("data-theme", attr);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

const theme = ref(readStoredTheme());
applyThemeAttribute(theme.value);

function persistTheme(value) {
  if (typeof window === "undefined" || !window.localStorage) {
    return;
  }
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, value);
  } catch {
    // Ignore storage failures; the in-memory theme remains usable.
  }
}

export function useTheme() {
  const themeLabel = computed(() => THEME_LABELS[theme.value] || THEME_LABELS.day);

  function setTheme(nextTheme) {
    const normalized = normalizeTheme(nextTheme);
    theme.value = normalized;
    applyThemeAttribute(normalized);
    persistTheme(normalized);
  }

  function cycleTheme() {
    const index = THEME_ORDER.indexOf(theme.value);
    setTheme(THEME_ORDER[(index + 1) % THEME_ORDER.length]);
  }

  return {
    theme,
    themeLabel,
    setTheme,
    cycleTheme,
  };
}
