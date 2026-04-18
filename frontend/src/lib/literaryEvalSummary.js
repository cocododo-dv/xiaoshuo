const DIMENSION_LABELS = {
  required_terms: "必备词",
  style_cues: "风格线索",
  banned_terms: "禁用词",
  length: "长度",
};

function formatScore(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "-";
  }
  return numeric.toFixed(2);
}

function previewText(value, maxLength = 180) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) {
    return "-";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

export function buildLiteraryEvalCaseRows(report) {
  const cases = Array.isArray(report?.cases) ? report.cases : [];
  return cases.map((item, index) => {
    const caseId = item?.case_id || `case_${index + 1}`;
    const issues = Array.isArray(item?.issues) ? item.issues.filter(Boolean) : [];
    const dimensions = item?.dimensions && typeof item.dimensions === "object"
      ? Object.entries(item.dimensions).map(([key, value]) => ({
          key,
          label: DIMENSION_LABELS[key] || key,
          score: formatScore(value),
        }))
      : [];

    return {
      caseId,
      title: item?.title || caseId,
      passed: Boolean(item?.passed),
      statusLabel: item?.passed ? "通过" : "未通过",
      scoreLabel: formatScore(item?.score),
      dimensions,
      issueText: issues.length ? issues.join("；") : "无",
      generatedPreview: previewText(item?.generated_text),
    };
  });
}
