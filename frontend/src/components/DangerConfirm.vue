<script setup>
import { ref } from "vue";

const props = defineProps({
  label: {
    type: String,
    required: true,
  },
  confirmLabel: {
    type: String,
    default: "确认执行",
  },
  message: {
    type: String,
    default: "该操作不可轻易撤销，请再次确认。",
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  testId: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["confirm"]);
const armed = ref(false);

function arm() {
  if (props.disabled) {
    return;
  }
  if (!armed.value) {
    armed.value = true;
    return;
  }
  emit("confirm");
  armed.value = false;
}
</script>

<template>
  <div class="danger-confirm" :class="{ armed }">
    <p v-if="armed" class="danger-confirm-message">{{ message }}</p>
    <button type="button" class="danger-button" :data-testid="testId || undefined" :disabled="disabled" @click="arm">
      {{ armed ? confirmLabel : label }}
    </button>
  </div>
</template>
