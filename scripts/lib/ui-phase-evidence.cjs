"use strict";

const UI_PHASE_REQUIREMENTS = Object.freeze({
  snowflake_planning: [
    { id: "step-save", method: "PATCH", path: /\/api\/v2\/projects\/[^/]+\/snowflake-workspace\/steps\/[^/?]+(?:\?|$)/, min: 10 },
    { id: "step-approve", method: "POST", path: /\/api\/v2\/projects\/[^/]+\/snowflake-workspace\/steps\/[^/]+\/approve(?:\?|$)/, min: 10 },
  ],
  materialization: [
    { id: "materialize", method: "POST", path: /\/api\/v2\/projects\/[^/]+\/snowflake-workspace\/materialize(?:\?|$)/, min: 1 },
    { id: "outline-approve", method: "POST", path: /\/api\/v2\/projects\/[^/]+\/snowflake-workspace\/outline\/approve(?:\?|$)/, min: 1 },
  ],
  scene_execution: [
    { id: "run-job-create", method: "POST", path: /\/api\/v1\/scenes\/[^/]+\/run\/jobs(?:\?|$)/, min: 1 },
  ],
  candidate_selection: [
    { id: "candidate-select", method: "POST", path: /\/api\/v1\/scenes\/[^/]+\/style-candidates\/[^/]+\/select(?:\?|$)/, min: 1 },
    { id: "selection-resume", method: "POST", path: /\/api\/v1\/scenes\/[^/]+\/resume-after-selection(?:\?|$)/, min: 1 },
  ],
  archive: [
    { id: "adopt-current", method: "POST", path: /\/api\/v1\/scenes\/[^/]+\/adopt-current(?:\?|$)/, min: 1 },
  ],
  chapter_aggregation: [
    { id: "final-aggregate", method: "POST", path: /\/api\/v1\/chapters\/[^/]+\/runtime\/aggregate\/final(?:\?|$)/, min: 1 },
  ],
});

class UiPhaseEvidenceError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "UiPhaseEvidenceError";
    this.code = code;
    this.details = details;
  }
}

function cloneRequirements(phase, minimums = {}) {
  const specs = UI_PHASE_REQUIREMENTS[phase];
  if (!specs) {
    throw new UiPhaseEvidenceError("UI_PHASE_UNKNOWN", `unknown UI phase: ${phase}`, { phase });
  }
  return specs.map((spec) => ({ ...spec, min: Number(minimums[spec.id] || spec.min), matched: 0 }));
}

function responseReceipt(response) {
  const request = response.request();
  return {
    method: String(request.method() || "GET").toUpperCase(),
    url: response.url(),
    status: Number(response.status()),
    resource_type: typeof request.resourceType === "function" ? request.resourceType() : "unknown",
  };
}

function matchingRequirement(requirements, receipt) {
  if (!new Set(["fetch", "xhr"]).has(receipt.resource_type)) return null;
  return requirements.find((spec) => spec.method === receipt.method && spec.path.test(receipt.url)) || null;
}

async function observeUiPhase(page, phase, action, options = {}) {
  if (!page || typeof page.on !== "function" || typeof action !== "function") {
    throw new UiPhaseEvidenceError("UI_PHASE_ARGUMENT_INVALID", "page and action callback are required", { phase });
  }
  const requirements = cloneRequirements(phase, options.minimums || {});
  const receipts = [];
  const failures = [];
  let interactionCount = 0;

  const onResponse = (response) => {
    const receipt = responseReceipt(response);
    const requirement = matchingRequirement(requirements, receipt);
    if (!requirement) return;
    receipts.push({ ...receipt, requirement_id: requirement.id });
    if (receipt.status >= 200 && receipt.status < 300) requirement.matched += 1;
    else failures.push({ ...receipt, requirement_id: requirement.id });
  };
  page.on("response", onResponse);

  const requireLocator = (locator, method) => {
    if (!locator || typeof locator[method] !== "function") {
      throw new UiPhaseEvidenceError("UI_PHASE_LOCATOR_REQUIRED", `a Playwright locator with ${method}() is required`, { phase, method });
    }
    interactionCount += 1;
    return locator;
  };
  const interact = {
    click: (locator, clickOptions) => requireLocator(locator, "click").click(clickOptions),
    fill: (locator, value, fillOptions) => requireLocator(locator, "fill").fill(value, fillOptions),
    check: (locator, checkOptions) => requireLocator(locator, "check").check(checkOptions),
    selectOption: (locator, value, selectOptions) => requireLocator(locator, "selectOption").selectOption(value, selectOptions),
  };

  try {
    await action(interact);
    if (options.settleMs) await new Promise((resolve) => setTimeout(resolve, Number(options.settleMs)));
  } finally {
    if (typeof page.off === "function") page.off("response", onResponse);
    else if (typeof page.removeListener === "function") page.removeListener("response", onResponse);
  }

  if (interactionCount === 0) {
    throw new UiPhaseEvidenceError("UI_PHASE_INTERACTION_REQUIRED", `${phase} has no recorded locator interaction`, { phase });
  }
  if (failures.length) {
    throw new UiPhaseEvidenceError("UI_PHASE_REQUEST_FAILED", `${phase} observed a failed browser request`, { phase, failures });
  }
  const missing = requirements.filter((item) => item.matched < item.min);
  if (missing.length) {
    throw new UiPhaseEvidenceError("UI_PHASE_REQUEST_MISSING", `${phase} did not satisfy its browser request contract`, {
      phase,
      missing: missing.map(({ id, min, matched }) => ({ id, min, matched })),
      requests: receipts,
    });
  }
  return {
    phase,
    lane: "ui",
    interaction_count: interactionCount,
    requirements: requirements.map(({ id, method, min, matched }) => ({ id, method, min, matched })),
    requests: receipts,
  };
}

module.exports = {
  UI_PHASE_REQUIREMENTS,
  UiPhaseEvidenceError,
  observeUiPhase,
};
