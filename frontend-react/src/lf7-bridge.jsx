import { wsKey, WsWorks } from "./ws-works.jsx";
import { WsCatalog } from "./ws-catalog.jsx";
import { apiGet, apiPost } from "./lib/client.js";
import { LF2_CANON } from "./lf2-data.jsx";
import { rvPush } from "./ws-review.jsx";
import { scnQueueLoad, scnQueueSave } from "./ws-scene-run.jsx";

/* global window */
/* ==========================================================
   lf7-bridge — 控制塔 ↔ 工作台联动桥（FE-ALIGN Phase 7：接真）
   ----------------------------------------------------------
   ① 设定裁决统一：finding（ChapterAuditFinding）是唯一状态——
      ruleCanon → POST adjudicate（后端同事务把待办卡置 resolved）；
      待办卡的 rule_canon effect 调同一服务函数。任一侧裁决，另一侧消失。
   ② onceTask → 待办卡 dedupe_key 唯一索引（重复触发静默去重）。
   ③ 归档写回：契约 transition→archived（后端推进目录章状态 + 触发资料派生）。
   事件 lf:bridge-changed 语义保留。
   ========================================================== */

const LF7_LS = "lf7_bridge_v1";
const lf7Key = () => (wsKey ? wsKey(LF7_LS) : LF7_LS);
const LF7_MIGRATED_LS = "lf7_bridge_migrated_v1";
const lf7ProjectId = () => { try { return WsWorks ? WsWorks.activeId() : null; } catch (e) { return null; } };
const lf7IsTide = () => lf7ProjectId() === "tide";

function lf7Emit() {
  try { window.dispatchEvent(new CustomEvent("lf:bridge-changed")); } catch (e) {}
  try { window.dispatchEvent(new CustomEvent("ws:review-changed")); } catch (e) {}
}

/* ---- findings 缓存（项目级审计清单） ---- */
let lf7Findings = [];
let lf7Fetching = null;
function lf7Fetch() {
  const pid = lf7ProjectId();
  if (!pid || pid === "__loading__") return Promise.resolve();
  if (lf7Fetching) return lf7Fetching;
  lf7Fetching = (async () => {
    try {
      await lf7MigrateLegacy(pid);
      const data = await apiGet(`/api/v2/projects/${pid}/longform/audit`);
      lf7Findings = (data && data.findings) || [];
      lf7Emit();
    } catch (e) {
      console.warn("[Lf7Bridge] 拉取审计清单失败:", e);
    } finally {
      lf7Fetching = null;
    }
  })();
  return lf7Fetching;
}

function lf7Meta(finding) {
  try { return JSON.parse(finding.evidence || "{}") || {}; } catch (e) { return {}; }
}

/* 旧 localStorage 桥状态一次性上行：未裁决的 extraCanon → findings；
   已裁决（canonRuled）尽力对应 adjudicate；tasked/archived 丢弃（后端重建） */
async function lf7MigrateLegacy(pid) {
  try {
    const flag = LF7_MIGRATED_LS + "::" + pid;
    if (localStorage.getItem(flag)) return;
    localStorage.setItem(flag, new Date().toISOString());
    const st = JSON.parse(localStorage.getItem(lf7Key()) || "{}");
    for (const entry of st.extraCanon || []) {
      try {
        await apiPost(`/api/v2/projects/${pid}/longform/chapters/${entry.conflictCh || "ch"}/audit`, {
          finding_id: entry.id,
          kind: "drift",
          severity: entry.drift ? "block" : "warn",
          text: entry.conflictText || entry.subject || "设定冲突",
          meta: { subject: entry.subject, value: entry.value, source: entry.source, drift: !!entry.drift },
        });
      } catch (e) {}
    }
    for (const id of Object.keys(st.canonRuled || {})) {
      try {
        await apiPost(`/api/v2/projects/${pid}/longform/audit/${id}/adjudicate`, {
          decision: "accept_fix",
          note: (st.canonRuled[id] || {}).value || "",
        });
      } catch (e) {}
    }
  } catch (e) {}
}

const Lf7Bridge = {
  /* 旧 state() 返回桥状态对象；视图读 handoff9 等键 —— 缓存映射保形 */
  state() {
    const ruled = this.ruled();
    return {
      canonRuled: ruled,
      extraCanon: this.extraCanon(),
      archived: lf7ArchivedMap(),
      handoff9: lf7HandoffLocal().handoff9 || null,
      tasked: {},
    };
  },
  /* —— 设定裁决：塔或收件箱任一侧统一并锁定（后端同源） —— */
  ruleCanon(id, value) {
    const pid = lf7ProjectId();
    if (!pid) return;
    // 乐观：本地缓存先置 adjudicated
    lf7Findings = lf7Findings.map(f => f.finding_id === id ? { ...f, status: "adjudicated", decision_note: value || f.decision_note } : f);
    lf7Emit();
    apiPost(`/api/v2/projects/${pid}/longform/audit/${id}/adjudicate`, {
      decision: "accept_fix",
      note: value || "",
    }).then(() => lf7Fetch()).catch((e) => {
      try { window.alert((e && e.message) || "裁决失败。"); } catch (e2) {}
      lf7Fetch();
    });
  },
  isRuled(id) {
    const f = lf7Findings.find(x => x.finding_id === id);
    return !!(f && f.status === "adjudicated");
  },
  ruled() {
    const out = {};
    lf7Findings.forEach(f => {
      if (f.status === "adjudicated") out[f.finding_id] = { value: f.decision_note || null, at: Date.parse(f.updated_at || "") || Date.now() };
    });
    return out;
  },
  /* —— 章级审计回执（FE-ALIGN H2）：契约+产出+锚点在场确定性扫描 ——
     正文存在 → 还原 LF3_AUDIT 形状（honored=命中带真实引用句；未检出/到期
     承诺归 introduced 区待人工核对；drifted 恒空——违约判定属 LLM 审计 D13）；
     无正文 → null（lf6 回落静态演示）。 */
  async auditReceipt(chNo) {
    const pid = lf7ProjectId();
    const chapterId = lf7ChapterIdByNo(chNo);
    if (!pid || !chapterId) return null;
    let r = null;
    try { r = await apiGet(`/api/v2/projects/${pid}/longform/chapters/${chapterId}/audit-receipt`); } catch (e) { return null; }
    if (!r || !r.has_text) return null;
    return {
      ch: r.chapter_no || chNo,
      real: true,
      words: r.words_total,
      contractStatus: (r.contract || {}).status || "",
      honored: (r.anchor_hits || []).map((h, i) => ({
        id: "rh-" + (h.id || i), label: "锚点在场", tone: "sage",
        text: `${h.subject} = ${h.value}`, evidence: h.evidence, at: h.at,
      })),
      drifted: [],
      introduced: [
        ...(r.anchor_misses || []).map((m, i) => ({
          id: "rm-" + (m.id || i), kind: "未检出", tone: "gold",
          text: `${m.subject} = ${m.value}`,
          note: "本章正文未检出该锚点值——人工核对，必要时回写作台补写。",
          actions: ["人工核对"],
        })),
        ...(r.pending || []).map((p, i) => ({
          id: "rp-" + (p.id || i), kind: "到期承诺", tone: "gold",
          text: p.title, note: p.note || "本章为计划回收章——待人工核对落点。",
          actions: ["人工核对回收落点"],
        })),
      ],
    };
  },
  /* —— 章级「违约级判定」（FE-ALIGN P2 / D13）：草稿 vs 交接契约 LLM 比对 ——
     接后端 adjudicate-draft：违约 → 映射成 drifted 形状（带真实 finding_id，
     可走 ruleCanon 裁决）+ 刷新缓存让收件箱出现裁决卡；LLM 未配置 → 诚实降级
     （skipped + author_action，drifted 留空，不机器判违约）。 */
  async adjudicateDraft(chNo) {
    const pid = lf7ProjectId();
    const chapterId = lf7ChapterIdByNo(chNo);
    if (!pid || !chapterId) return null;
    let r = null;
    try {
      r = await apiPost(`/api/v2/projects/${pid}/longform/chapters/${chapterId}/audit/adjudicate-draft`, {});
    } catch (e) {
      return { skipped: true, reason: "error", author_action: null, drifted: [], findings_created: 0, error: (e && e.message) || "裁定失败" };
    }
    if (!r) return null;
    if (r.skipped) {
      return { skipped: true, reason: r.reason || "skipped", author_action: r.author_action || null, drifted: [], findings_created: 0 };
    }
    try { lf7Fetch(); } catch (e) {}  // 裁定落了 finding，刷新缓存让裁决卡/ruleCanon 可用
    const drifted = (r.violations || []).map((v, i) => {
      const block = v.severity === "block";
      return {
        id: v.finding_id || ("vio-" + i),
        finding_id: v.finding_id || null,
        real: true,
        label: block ? "违约 · 阻断" : "违约 · 偏离",
        tone: block ? "rose" : "gold",
        sev: block ? "high" : "medium",
        what: v.text,
        detail: (v.clause_ref ? `违反交接契约第 ${v.clause_ref} 条。` : "") + (v.suggested_fix || ""),
        line: v.evidence_sentence || "",
        at: v.at || "",
        fixes: v.suggested_fix ? [v.suggested_fix, "钉入下一轮交接复核"] : ["钉入下一轮交接复核"],
      };
    });
    return { skipped: false, reason: null, drifted, findings_created: r.findings_created || 0 };
  },
  /* —— 归档时新发现的冲突：直接建 finding（后端同事务产待办卡） —— */
  addCanonConflict(entry) {
    const pid = lf7ProjectId();
    if (!pid || !entry || !entry.id) return;
    if (lf7Findings.some(f => f.finding_id === entry.id)) return;
    const chapterRef = lf7ChapterIdByNo(entry.conflictCh) || String(entry.conflictCh || "");
    apiPost(`/api/v2/projects/${pid}/longform/chapters/${chapterRef}/audit`, {
      finding_id: entry.id,
      kind: "drift",
      severity: entry.drift ? "block" : "warn",
      text: entry.conflictText || entry.subject || "设定冲突",
      meta: { subject: entry.subject, value: entry.value, source: entry.source, drift: !!entry.drift },
    }).then(() => lf7Fetch()).catch((e) => {
      console.warn("[Lf7Bridge] 登记冲突失败:", e);
    });
  },
  extraCanon() {
    /* 后端 findings 中超出 LF2_CANON 静态种子的条目（归档新增），还原为 canon 条目形状。
       只认 kind=drift（canon 冲突的登记 kind）——G1 起 findings 还承载
       空降/断链/认知态（unplanted_reveal/causal_break/unfair_clue），归 LF3 投影 */
    const base = new Set(((LF2_CANON || [])).map(c => c.id));
    return lf7Findings
      .filter(f => f.kind === "drift" && !base.has(f.finding_id))
      .map(f => {
        const meta = lf7Meta(f);
        return {
          id: f.finding_id,
          subject: meta.subject || f.text,
          value: meta.value || "（待统一）",
          source: meta.source,
          status: f.status === "adjudicated" ? "locked" : "conflict",
          drift: !!meta.drift,
          conflictCh: meta.source,
          conflictText: f.text,
        };
      });
  },
  /* —— 拍板产物化：dedupe_key 唯一索引保证同一事项只有一张卡 —— */
  onceTask(key, payload) {
    if (rvPush) rvPush({ ...(payload || {}), dedupeKey: key });
    return true; // 去重由后端唯一索引静默完成
  },
  /* —— 归档登记：以目录章状态为准（写回链 P7 后端化） —— */
  isArchived(ch) {
    try {
      const chapter = (WsCatalog ? WsCatalog.get() : []).find(c => parseInt(c.n, 10) === parseInt(ch, 10));
      return !!(chapter && ["draft", "review", "approved"].includes(chapter.state));
    } catch (e) { return false; }
  },
  markArchived(ch) {
    /* 真实归档动作走 lf7ArchiveCh9 / 契约 transition；这里仅触发刷新（保留签名） */
    void ch;
    try { if (WsCatalog && WsCatalog.__refresh) WsCatalog.__refresh(); } catch (e) {}
    lf7Emit();
  },
  /* —— 演示闭环复位：不再移植（等价能力 = 后端 reset_author_state 工具） —— */
  resetLoop9() {
    try { window.alert("演示复位已随后端化下线：用 python -m novel_system.tools.reset_author_state 重置，或重启 dev（自动 reseed demo）。"); } catch (e) {}
  },
  __refresh: lf7Fetch,
};

/* handoff9 等纯 UI 流程标记仍留本地（不构成业务真相） */
function lf7HandoffLocal() {
  try { return JSON.parse(localStorage.getItem(lf7Key()) || "{}"); } catch (e) { return {}; }
}
function lf7SaveLocal(patch) {
  const st = { ...lf7HandoffLocal(), ...patch };
  try { localStorage.setItem(lf7Key(), JSON.stringify(st)); } catch (e) {}
  lf7Emit();
}
function lf7ArchivedMap() {
  const out = {};
  try {
    (WsCatalog ? WsCatalog.get() : []).forEach(c => {
      if (["draft", "review", "approved"].includes(c.state)) out[parseInt(c.n, 10)] = true;
    });
  } catch (e) {}
  return out;
}
function lf7ChapterIdByNo(no) {
  try {
    const chapter = (WsCatalog ? WsCatalog.get() : []).find(c => parseInt(c.n, 10) === parseInt(no, 10));
    return chapter ? chapter.backendId : null;
  } catch (e) { return null; }
}

/* 把已裁决应用到 canon 种子（塔挂载时调用）：
   已裁决 → 锁定 + 钉入；归档新增的冲突（extraCanon）一并并入 */
function lf7ApplyCanon(seed) {
  const ruled = Lf7Bridge.ruled();
  const extras = Lf7Bridge.extraCanon().filter(x => !seed.some(c => c.id === x.id));
  return [...seed, ...extras].map(c =>
    ruled[c.id] && c.status === "conflict"
      ? { ...c, status: "locked", pinned: true, drift: false, fresh: false }
      : c
  );
}

/* 待裁决设定冲突（塔与待办同一事实：后端 findings status=open） */
function lf7PendingCanon() {
  if (!lf7IsTide()) {
    /* 非 demo 作品：纯后端 findings */
    return lf7Findings.filter(f => f.status === "open").map(f => {
      const meta = lf7Meta(f);
      return { id: f.finding_id, subject: meta.subject || f.text, value: meta.value || "（待统一）", source: meta.source, conflictCh: meta.source, conflictText: f.text, drift: !!meta.drift };
    });
  }
  const base = LF2_CANON || [];
  const ruled = Lf7Bridge.ruled();
  const openIds = new Set(lf7Findings.filter(f => f.status === "open").map(f => f.finding_id));
  const extras = Lf7Bridge.extraCanon().filter(x => x.status === "conflict" && !base.some(c => c.id === x.id));
  return [...base, ...extras].filter(c => c.status === "conflict" && !ruled[c.id] && (openIds.size === 0 || openIds.has(c.id) || !lf7Findings.some(f => f.finding_id === c.id)));
}


/* 塔台化：交接 = 把第 9 章按契约拆成 3 场、入列 AI 起草台（唯一执行器）。
   塔不再直接生成正文 —— 场内质检归起草台，跨章审计归塔。 */
const LF7_CH9_PLAN = {
  id: "ch09", act: "act2", n: "09", title: "登记簿与脚印", state: "writing",
  tension: 0.66, pov: "林岑", time: "D18 · 夜", place: "档案学院 · 地下档案室",
  words: { cur: 0, target: 5200 },
  entry: "林岑借督察随行的名义，再次进入档案学院。",
  exit: "第二组脚印有了主人轮廓，抽屉还没有打开。",
  align: true,
  promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
  drama: {
    promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
    spine: "控制塔下发交接契约 · AI 起草台逐场起草。",
    arc: "由「单独求证」转向「与周岚被迫同行」。",
    problem: "档案箱里那张旧照片，是谁放进去的？",
    aftertaste: "她把盐钟扣回掌心。",
    ending: "章末留下未开的抽屉。",
    forbidden: "—",
    notes: "由控制塔交接下发：逐场起草完成后回塔做章级审计。",
  },
  threads: [{ name: "第二组脚印", role: "回收" }, { name: "旧照片", role: "新引" }],
  scenes: [
    { title: "借阅登记簿", kind: "主动", state: "todo", contract: ["ho-c1", "ho-c3"], goal: "以督察随行名义换取借阅权限", obstacle: "登记需留实名与年龄（锚点：林岑 28 岁）", turn: "她在年龄栏写下「28」，描深了那个 8" },
    { title: "档案室对峙", kind: "主动", state: "todo", contract: ["ho-c4", "ho-c2", "ho-l1"], goal: "让周岚打开三号档案箱（锚点：地下档案室）", obstacle: "周岚只给看目录，不给开箱", turn: "箱内出现替换件，和一张没有说明的旧照片" },
    { title: "楼梯间 · 三楼转角", kind: "主动", state: "todo", contract: ["ho-l6", "ho-c5", "ho-arc-阿恪"], goal: "核对第二组脚印（到期承诺：逾期回收）", obstacle: "夜班迅查将至", turn: "鞋码比父亲小半号——有人在他之后下过楼" },
  ],
};

function lf7Dispatch9() {
  if (!lf7IsTide() || !WsCatalog) return null;
  if (Lf7Bridge.isArchived(9)) return null;
  try {
    const chs = WsCatalog.get();
    const i = chs.findIndex(c => parseInt(c.n, 10) === 9);
    const existing = i >= 0 ? chs[i] : null;
    /* 已经下发过 / 已有实质内容的第 9 章不重复覆盖 */
    if (!(existing && existing.state !== "planned")) {
      const plan = { ...LF7_CH9_PLAN, scenes: LF7_CH9_PLAN.scenes.map(s => ({ ...s })) };
      WsCatalog.set(i >= 0 ? chs.map((c, j) => (j === i ? plan : c)) : [...chs, plan]);
    }
    /* 入列起草台（唯一执行器）：取回盖戳后的 sid 送进队列 */
    const ch9 = WsCatalog.get().find(c => parseInt(c.n, 10) === 9);
    const sids = ch9 ? (ch9.scenes || []).map(s => s.sid).filter(Boolean) : [];
    if (scnQueueLoad && scnQueueSave) {
      const q = scnQueueLoad();
      scnQueueSave([...sids.filter(x => !q.includes(x)), ...q]);
    }
    lf7SaveLocal({ handoff9: { at: Date.now(), sids } });
    return { sids, ch: 9 };
  } catch (e) { return null; }
}

/* 归档写回：章级审计通过后，第 9 章在目录里置为草稿（进成稿中心待审）。
   若从未下发过（旧路径），退而插入静态演示章。 */
const LF7_CH9 = {
  id: "ch09", act: "act2", n: "09", title: "登记簿与脚印", state: "draft",
  tension: 0.66, pov: "林岑", time: "D18 · 夜", place: "档案学院 · 地下档案室",
  words: { cur: 5230, target: 5200 },
  entry: "林岑借督察随行的名义，再次进入档案学院。",
  exit: "第二组脚印有了主人轮廓，抽屉还没有打开。",
  align: true,
  promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
  drama: {
    promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
    spine: "AI 按交接契约整章起草，控制塔逐条审计后归档。",
    arc: "由「单独求证」转向「与周岚被迫同行」。",
    problem: "档案箱里那张旧照片，是谁放进去的？",
    aftertaste: "她把盐钟扣回掌心。",
    ending: "章末留下未开的抽屉。",
    forbidden: "—",
    notes: "控制塔归档：偏离「三楼/地下档案室」已裁决并送下一轮交接复核。",
  },
  threads: [{ name: "第二组脚印", role: "回收" }, { name: "旧照片", role: "新引" }],
  scenes: [
    { title: "借阅登记簿", kind: "主动", state: "done", words: 1680, goal: "以督察随行名义换取借阅权限", obstacle: "登记需留实名与年龄", turn: "她在年龄栏写下「28」，描深了那个 8" },
    { title: "档案室对峙", kind: "主动", state: "done", words: 1890, goal: "让周岚打开三号档案箱", obstacle: "周岚只给看目录，不给开箱", turn: "箱内出现替换件，和一张没有说明的旧照片" },
    { title: "楼梯间 · 三楼转角", kind: "主动", state: "done", words: 1660, goal: "核对第二组脚印", obstacle: "夜班巡查将至", turn: "鞋码比父亲小半号——有人在他之后下过楼" },
  ],
};

function lf7ArchiveCh9() {
  if (!lf7IsTide() || !WsCatalog) return false;
  if (Lf7Bridge.isArchived(9)) return false;
  try {
    const chs = WsCatalog.get();
    const i = chs.findIndex(c => parseInt(c.n, 10) === 9);
    if (i >= 0 && chs[i].state !== "planned") {
      /* 塔台化路径：起草台逐场写完的第 9 章，章级审计通过后置为草稿（进成稿中心待审） */
      WsCatalog.set(chs.map((c, j) => (j === i ? {
        ...c, state: "draft", current: false,
        drama: { ...(c.drama || {}), notes: "控制塔章级审计通过后归档；「三楼/地下」漂移已裁决并送下一轮交接复核。" },
      } : c)));
      Lf7Bridge.markArchived(9);
      return true;
    }
    /* 旧路径兑底：从未下发过时插入静态演示章 */
    const next = i >= 0
      ? chs.map((c, j) => (j === i ? { ...LF7_CH9 } : c))
      : [...chs, { ...LF7_CH9 }];
    WsCatalog.set(next);
    Lf7Bridge.markArchived(9);
    return true;
  } catch (e) { return false; }
}

/* 启动装载 + 作品切换刷新 */
try { lf7Fetch(); } catch (e) {}
window.addEventListener("ws:work-changed", () => { try { lf7Fetch(); } catch (e) {} });

Object.assign(window, { Lf7Bridge, lf7ApplyCanon, lf7PendingCanon, lf7ArchiveCh9, lf7Dispatch9 });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { Lf7Bridge, lf7ApplyCanon, lf7PendingCanon, lf7ArchiveCh9, lf7Dispatch9 };
