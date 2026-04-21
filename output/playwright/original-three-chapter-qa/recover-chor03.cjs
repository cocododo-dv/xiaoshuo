const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "../../..");
const apiBase =
  process.env.PLAYWRIGHT_API_BASE ||
  fs.readFileSync(path.join(repoRoot, ".codex-run", "backend.url"), "utf8").trim();
const operatorRef = process.env.PLAYWRIGHT_OPERATOR_REF || `qa.original-three-chapters.recover.${Date.now()}`;

function idKey(label) {
  return `${label}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function parse(response, method, apiPath) {
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(`${method} ${apiPath} failed ${response.status}: ${payload.error?.message || response.statusText}`);
  }
  return payload.data;
}

async function post(apiPath, data = {}, timeoutMs = 600000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase}${apiPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Operator-Ref": operatorRef,
        "X-Idempotency-Key": idKey(apiPath),
      },
      body: JSON.stringify(data),
      signal: controller.signal,
    });
    return await parse(response, "POST", apiPath);
  } finally {
    clearTimeout(timeout);
  }
}

async function get(apiPath) {
  const response = await fetch(`${apiBase}${apiPath}`, {
    headers: { "X-Operator-Ref": operatorRef },
  });
  return parse(response, "GET", apiPath);
}

async function main() {
  await post("/api/v1/scenes", {
    scene_id: "CHOR03_SC01",
    chapter_id: "CHOR03",
    must_include_text: "无灯船坞水面无倒影；盐钟残片开柜；潮声倒退三秒。",
    forbidden_text:
      "不得复刻参考书原句、专名、超自然体系、学院组织或标志性桥段；不得重复同一句；不得把必须包含文本在结尾作为清单复述；正文不得出现“以上线索”“不要”“必须包含”“清单”“任务”等说明话术。",
  }, 30000);
  const run = await post("/api/v1/scenes/CHOR03_SC01/run/full", {}, 600000);
  const workbench = await get("/api/v1/scenes/CHOR03_SC01/workbench");
  const result = {
    operatorRef,
    run,
    sceneStatus: workbench.scene_run_state?.scene_status || null,
    finalRowId: workbench.final_scene?.row_id || null,
    bundleId: workbench.bundle?.bundle_id || null,
    hardQc: workbench.hard_qc_summary || null,
    softQc: workbench.soft_qc_summary || null,
    finalText: workbench.final_scene?.content || "",
    attempts: (workbench.attempts || []).map((item) => ({
      step: item.step,
      status: item.status,
      sourceBundleId: item.source_bundle_id,
    })),
  };
  fs.writeFileSync(
    path.join(__dirname, "recover-chor03-result.json"),
    JSON.stringify(result, null, 2),
    "utf8",
  );
  console.log(JSON.stringify({ sceneStatus: result.sceneStatus, finalRowId: result.finalRowId, bundleId: result.bundleId }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
