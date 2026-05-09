<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  label: {
    type: String,
    required: true,
  },
  modelValue: {
    type: String,
    default: "",
  },
  options: {
    type: Array,
    default: () => [],
  },
  placeholder: {
    type: String,
    default: "请选择",
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  searchable: {
    type: Boolean,
    default: true,
  },
  foldedCount: {
    type: Number,
    default: 0,
  },
  testId: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["update:modelValue", "change"]);

const query = ref("");
const selectedOption = computed(() => props.options.find((option) => option.value === props.modelValue) || null);
const filteredOptions = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase();
  const selected = selectedOption.value;
  const matches = needle
    ? props.options.filter((option) =>
        [option.label, option.detail, option.technical, option.raw]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase()
          .includes(needle),
      )
    : props.options;

  if (selected && !matches.some((option) => option.value === selected.value)) {
    return [selected, ...matches];
  }
  return matches;
});

watch(
  () => props.modelValue,
  () => {
    query.value = "";
  },
);

function updateSelection(event) {
  const value = event.target.value;
  emit("update:modelValue", value);
  emit("change", value);
}
</script>

<template>
  <label class="compact-entity-select" :data-testid="testId || undefined">
    <span class="compact-entity-label">{{ label }}</span>
    <input
      v-if="searchable"
      v-model="query"
      class="compact-entity-search"
      type="search"
      :placeholder="`搜索${label}`"
      :disabled="disabled"
    />
    <select class="control-input" :value="modelValue" :disabled="disabled" @change="updateSelection">
      <option value="">{{ placeholder }}</option>
      <option v-for="option in filteredOptions" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
    <p v-if="selectedOption" class="compact-entity-meta">
      <strong class="line-clamp-2">{{ selectedOption.label }}</strong>
      <span class="technical-ref">{{ selectedOption.detail || selectedOption.technical }}</span>
    </p>
    <p v-if="foldedCount > 0 && !query" class="compact-entity-folded">
      已折叠 {{ foldedCount }} 条同名历史记录，可搜索 ID 找回。
    </p>
  </label>
</template>
