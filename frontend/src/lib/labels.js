const COMMON_STATUS_LABELS = {
  pending_review: "待确认",
  stale: "需检查",
  approved: "已完成",
  skipped: "已跳过",
  blocked: "暂不能继续",
  warning: "可以继续，但有提醒",
  ready: "可以继续",
};

const SNOWFLAKE_ACTION_LABELS = {
  gate: "规划完成度",
  materialization: "整理结构",
  triage: "场景检查",
  next_action: "下一步",
  writer_flow: "生成与审阅",
};

export function statusLabel(value, fallback = "") {
  return COMMON_STATUS_LABELS[String(value || "").toLowerCase()] || fallback || value || "";
}

export function snowflakeActionLabel(value, fallback = "") {
  return SNOWFLAKE_ACTION_LABELS[String(value || "").toLowerCase()] || fallback || value || "";
}

export function snowflakeGateStatusLabel(status) {
  if (status === "blocked") {
    return "还差几处才能整理";
  }
  if (status === "warning") {
    return "可以整理，但有提醒";
  }
  return "可以整理成章节结构";
}
