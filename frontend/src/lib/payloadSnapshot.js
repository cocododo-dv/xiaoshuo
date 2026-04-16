import { markRaw } from "vue";

function snapshotValue(value) {
  if (!value || typeof value !== "object") {
    return value;
  }

  if (Array.isArray(value)) {
    const items = value.map((item) => snapshotValue(item));
    markRaw(items);
    return Object.freeze(items);
  }

  const snapshot = {};
  Object.entries(value).forEach(([key, nestedValue]) => {
    snapshot[key] = snapshotValue(nestedValue);
  });
  markRaw(snapshot);
  return Object.freeze(snapshot);
}

export function snapshotPayload(value) {
  return snapshotValue(value);
}

export function snapshotPayloadList(items) {
  return snapshotValue(items || []);
}
