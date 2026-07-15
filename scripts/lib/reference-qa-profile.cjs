const fs = require("node:fs");
const path = require("node:path");

const ALLOWED_CLOUD_POLICIES = new Set(["local_only", "segments_only", "allow_full_cloud"]);

function parseJson(text, label) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} 不是有效 JSON: ${error.message}`);
  }
}

function readJsonFile(filePath, label) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`${label}不存在: ${filePath}`);
  }
  return parseJson(fs.readFileSync(filePath, "utf8"), label);
}

function resolvePath(root, value) {
  return path.normalize(path.isAbsolute(value) ? value : path.resolve(root, value));
}

function isInside(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function readPositiveInteger(value, label) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`${label} 必须是正整数`);
  }
  return parsed;
}

function readStringArray(value, label) {
  if (!Array.isArray(value)) {
    throw new Error(`${label} 必须是字符串数组`);
  }
  const normalized = [...new Set(value.map((item) => String(item || "").trim()).filter(Boolean))];
  if (normalized.length === 0) {
    throw new Error(`${label} 不得为空`);
  }
  return normalized;
}

function loadReferenceQaProfile({ repoRoot, env = process.env, profilePath } = {}) {
  if (!repoRoot) {
    throw new Error("repoRoot 必填");
  }
  const selectedProfilePath = resolvePath(
    repoRoot,
    profilePath || env.QA_REFERENCE_PROFILE_PATH || "config/qa/public-domain-source-safety-five-chapter.json",
  );
  const raw = readJsonFile(selectedProfilePath, "来源安全 QA 配置");
  if (raw.schema_version !== 1) {
    throw new Error(`不支持的来源安全 QA 配置版本: ${raw.schema_version}`);
  }

  const configuredReferencePath = resolvePath(repoRoot, String(raw.reference_path || ""));
  const referenceOverridden = Boolean(String(env.REFERENCE_BOOK_PATH || "").trim());
  const referencePath = referenceOverridden
    ? resolvePath(repoRoot, String(env.REFERENCE_BOOK_PATH).trim())
    : configuredReferencePath;
  if (!fs.existsSync(referencePath) || !fs.statSync(referencePath).isFile()) {
    throw new Error(`参考语料文件不存在: ${referencePath}`);
  }
  if (!referenceOverridden && raw.require_repo_path === true && !isInside(repoRoot, referencePath)) {
    throw new Error(`固定 lane 的参考语料必须位于仓库内: ${referencePath}`);
  }

  const cloudPolicy = String(env.REFERENCE_CLOUD_POLICY || raw.cloud_policy || "").trim();
  if (!ALLOWED_CLOUD_POLICIES.has(cloudPolicy)) {
    throw new Error(`不支持的 cloud_policy: ${cloudPolicy}`);
  }

  let rightsDeclaration = referenceOverridden ? null : raw.rights_declaration || null;
  if (String(env.REFERENCE_RIGHTS_DECLARATION_JSON || "").trim()) {
    rightsDeclaration = parseJson(env.REFERENCE_RIGHTS_DECLARATION_JSON, "REFERENCE_RIGHTS_DECLARATION_JSON");
  }
  if (rightsDeclaration !== null && (typeof rightsDeclaration !== "object" || Array.isArray(rightsDeclaration))) {
    throw new Error("rights_declaration 必须是对象或 null");
  }
  if (
    cloudPolicy !== "local_only" &&
    !(rightsDeclaration?.declared === true && rightsDeclaration?.send_rights === true)
  ) {
    throw new Error(
      "非 local_only 来源安全 lane 必须显式声明 declared=true 且 send_rights=true；自定义语料不会继承公有领域配置的权属声明。",
    );
  }

  const protectedTerms = String(env.REFERENCE_PROTECTED_TERMS_JSON || "").trim()
    ? readStringArray(
        parseJson(env.REFERENCE_PROTECTED_TERMS_JSON, "REFERENCE_PROTECTED_TERMS_JSON"),
        "REFERENCE_PROTECTED_TERMS_JSON",
      )
    : readStringArray(raw.protected_terms, "protected_terms");

  return {
    profilePath: selectedProfilePath,
    laneId: referenceOverridden ? "operator-supplied-reference" : String(raw.lane_id || "unnamed-reference-lane"),
    description: String(raw.description || ""),
    referencePath,
    sourceBasis: referenceOverridden
      ? String(env.REFERENCE_SOURCE_BASIS || "operator_supplied")
      : String(raw.source_basis || "unspecified"),
    sourceAttribution: referenceOverridden ? null : String(raw.source_attribution || ""),
    cloudPolicy,
    rightsDeclaration,
    protectedTerms,
    expectedChapterCount: readPositiveInteger(
      env.QA_CHAPTER_COUNT || raw.expected_chapter_count || 5,
      "expected_chapter_count",
    ),
    expectedScenesPerChapter: readPositiveInteger(
      env.QA_SCENES_PER_CHAPTER || raw.expected_scenes_per_chapter || 3,
      "expected_scenes_per_chapter",
    ),
  };
}

module.exports = { ALLOWED_CLOUD_POLICIES, loadReferenceQaProfile };
