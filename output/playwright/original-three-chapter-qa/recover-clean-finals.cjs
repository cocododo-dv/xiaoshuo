const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "../../..");
const apiBase =
  process.env.PLAYWRIGHT_API_BASE ||
  fs.readFileSync(path.join(repoRoot, ".codex-run", "backend.url"), "utf8").trim();
const operatorRef = process.env.PLAYWRIGHT_OPERATOR_REF || `qa.original-three-chapters.clean-finals.${Date.now()}`;

const scenes = [
  {
    sceneId: "CHOR01_SC01",
    chapterId: "CHOR01",
    mustIncludeText: "盐钟残片边缘有蓝白盐霜；潮汐记录缺页的编号连成一条倒置船线。",
  },
  {
    sceneId: "CHOR02_SC01",
    chapterId: "CHOR02",
    mustIncludeText: "监听站墙面贴满褪色潮位图；磁带倒放时出现幸存者的呼吸和三声盐钟。",
  },
];

const forbiddenText =
  "不得复刻参考书原句、专名、超自然体系、学院组织或标志性桥段；不得重复同一句；不得把必须包含文本在结尾作为清单复述；正文不得出现“以上线索”“不要”“必须包含”“清单”“任务”等说明话术。";

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

async function recoverScene(scene) {
  await post("/api/v1/scenes", {
    scene_id: scene.sceneId,
    chapter_id: scene.chapterId,
    must_include_text: scene.mustIncludeText,
    forbidden_text: forbiddenText,
  }, 30000);

  const startedAt = Date.now();
  const run = await post(`/api/v1/scenes/${encodeURIComponent(scene.sceneId)}/run/full`, {}, 600000);
  const workbench = await get(`/api/v1/scenes/${encodeURIComponent(scene.sceneId)}/workbench`);
  const finalText = workbench.final_scene?.content || "";
  return {
    sceneId: scene.sceneId,
    chapterId: scene.chapterId,
    ms: Date.now() - startedAt,
    run,
    sceneStatus: workbench.scene_run_state?.scene_status || null,
    finalRowId: workbench.final_scene?.row_id || null,
    bundleId: workbench.bundle?.bundle_id || null,
    hardQc: workbench.hard_qc_summary || null,
    softQc: workbench.soft_qc_summary || null,
    finalText,
    badTerms: ["以上线索", "不要", "必须包含", "清单", "任务"].filter((term) => finalText.includes(term)),
  };
}

async function main() {
  const results = [];
  for (const scene of scenes) {
    results.push(await recoverScene(scene));
  }
  const payload = { operatorRef, recoveredAt: new Date().toISOString(), results };
  fs.writeFileSync(
    path.join(__dirname, "recover-clean-finals-result.json"),
    JSON.stringify(payload, null, 2),
    "utf8",
  );
  console.log(JSON.stringify(results.map((item) => ({
    sceneId: item.sceneId,
    sceneStatus: item.sceneStatus,
    finalRowId: item.finalRowId,
    bundleId: item.bundleId,
    badTerms: item.badTerms,
  })), null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
