import React from "react";
import { I } from "./icons.jsx";
import { wsKey } from "./ws-works.jsx";
import { s2ExportState } from "./ws-snow.jsx";
import { WsCatalog } from "./ws-catalog.jsx";

/* global React, I */
/* ==========================================================
   AI 起草台 — 真实运行引擎（catalog-sourced scenes）
   ----------------------------------------------------------
   把演示流水线的「预检 → 起草 → 质检 → 裁决 → 归档」落到实处：
   · 上下文：雪花构思（一句话 / 道德前提 / 读者定位 / 角色表）+ 章节卡
   · 起草：后端 scenes run 管线（run/jobs 投递 + 轮询，FE-ALIGN F6）
   · 质检：确定性、可解释——短句率 / 句式重复 / 超长句标红，不装神弄鬼
   · 归档：写入写作器正文文档（wr-doc:sid）+ 字数回写 + 场景卡置 done
   · 持久化：每场的运行结果存 scn-run:sid（按作品隔离），刷新不丢
   ========================================================== */

const SCN_RUN_FIELDS = ["state", "draft", "metrics", "alignment", "verdict", "log", "attempts", "attempt", "at", "words"];
const scnRunKey = (sid) => (wsKey ? wsKey("scn-run:" + sid) : "scn-run:" + sid);
const scnQueueKey = () => (wsKey ? wsKey("scn-queue:v1") : "scn-queue:v1");

function scnRunLoad(sid) {
  try { return JSON.parse(localStorage.getItem(scnRunKey(sid))) || null; } catch (e) { return null; }
}
function scnRunSave(sid, run) {
  try {
    const slim = {}; SCN_RUN_FIELDS.forEach(f => { if (run[f] !== undefined) slim[f] = run[f]; });
    localStorage.setItem(scnRunKey(sid), JSON.stringify(slim));
  } catch (e) {}
}
function scnQueueLoad() {
  try { return JSON.parse(localStorage.getItem(scnQueueKey())) || []; } catch (e) { return []; }
}
function scnQueueSave(sids) {
  try { localStorage.setItem(scnQueueKey(), JSON.stringify(sids.slice(0, 40))); } catch (e) {}
}

/* ---- 上游上下文：雪花构思折叠成提示词材料 ---- */
function scnSnowContext() {
  try {
    const st = s2ExportState ? s2ExportState() : null;
    if (!st) return "";
    const d = st.drafts || {}, sc = st.scaffolds || {};
    const lines = [];
    const logline = (d.logline || "").trim();
    if (logline) lines.push("一句话概括：" + logline);
    const para = sc.paragraph || {};
    if ((para.premiseF || "").trim() || (para.premiseT || "").trim()) lines.push(`道德前提：「${para.premiseF || "—"}」→ 中点翻转为 →「${para.premiseT || "—"}」`);
    const aud = sc.audience || {};
    if ((aud.pleasure || "").trim()) lines.push("读者核心快感：" + aud.pleasure.trim());
    if ((aud.exclude || "").trim()) lines.push("明确不写：" + aud.exclude.trim());
    const chars = ((sc.characters || {}).chars) || {};
    const cl = Object.values(chars).filter(c => (c.name || "").trim()).slice(0, 5)
      .map(c => `${c.name}（${c.role}）：目标「${c.goal || "—"}」· 没有什么比「${c.values || "—"}」更重要`);
    if (cl.length) lines.push("角色表：\n" + cl.join("\n"));
    return lines.join("\n");
  } catch (e) { return ""; }
}

function scnBuildPrompt(item, note, prevText) {
  const hit = item.sid && WsCatalog ? WsCatalog.sceneById(item.sid) : null;
  const c = hit ? hit.chapter : null;
  const s = hit ? hit.scene : {};
  const reactive = (s.kind || item.kind || "").includes("反应");
  const ctx = scnSnowContext();
  const trio = reactive
    ? `这是「反应场景（RDD）」：\n· 反应（情绪先于理性）：${s.goal || "—"}\n· 两难（没有好选项）：${s.obstacle || "—"}\n· 决定（选一个坏选项，成为下一场目标）：${s.turn || "—"}`
    : `这是「主动场景（GCS）」：\n· 目标（具体可拍摄）：${s.goal || "—"}\n· 冲突（逐级受阻）：${s.obstacle || "—"}\n· 挫败（结尾比开场更糟）：${s.turn || "—"}`;
  return [
    "你是长篇小说的场景起草助手。为下面这一场写正文初稿。",
    ctx ? "【作品上下文 · 与之严格一致】\n" + ctx : "",
    c ? `【本章】第 ${c.n} 章《${c.title}》${(c.promise || "").trim() ? " · 章承诺：" + c.promise.trim() : ""}` : "",
    `【本场】《${s.title || item.title}》${c && (c.pov || "").trim() ? " · POV：" + c.pov : ""}`,
    trio,
    prevText ? "【上一版草稿 · 按指令改写而非重来】\n" + prevText.slice(0, 1200) : "",
    note ? "【作者改写指令 · 最高优先级】\n" + note : "",
    "",
    "要求：限知视角；短句克制、动词驱动、少形容词；700–1100 字，分 5–8 段；",
    "结尾的拍（挫败/决定）必须落在最后一两段，为下一场留钩。",
    "只输出一个 JSON 对象，不要任何其它文字、不要代码围栏：",
    '{"paras":[{"beat":"goal|conflict|setback|exit 或 null","text":"段落正文"}]}',
    reactive ? "（反应场用 beat 标注：reaction→goal、dilemma→conflict、decision→exit 的对应拍）" : "（goal/conflict/setback 各标在落点段，最后一段可标 exit）",
  ].filter(Boolean).join("\n");
}

const SCN_BEAT_MAP = { goal: "goal", conflict: "conflict", setback: "setback", exit: "exit", reaction: "goal", dilemma: "conflict", decision: "exit" };
function scnParseDraft(raw) {
  if (!raw) throw new Error("空响应");
  let t = String(raw).trim().replace(/```json/gi, "").replace(/```/g, "").trim();
  const a = t.indexOf("{"), b = t.lastIndexOf("}");
  let paras = null;
  if (a >= 0 && b > a) {
    const body = t.slice(a, b + 1);
    try { const obj = JSON.parse(body); if (Array.isArray(obj.paras)) paras = obj.paras; } catch (e) {
      // 模型常在字符串里直接换行 → 控制字符让 JSON.parse 报错；拍平后重试
      try { const obj = JSON.parse(body.replace(/[\u0000-\u001f]+/g, " ")); if (Array.isArray(obj.paras)) paras = obj.paras; } catch (e2) {}
    }
  }
  if (!paras) {
    // 宽松抽取：逐对 "beat"/"text" 字段，容忍外层结构坏掉
    const found = [];
    let m;
    const re = /"beat"\s*:\s*(?:null|"([a-z]*)")\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"/g;
    while ((m = re.exec(t))) found.push({ beat: m[1] || null, text: m[2] });
    if (!found.length) {
      const re2 = /"text"\s*:\s*"((?:[^"\\]|\\.)*)"/g;
      while ((m = re2.exec(t))) found.push({ beat: null, text: m[1] });
    }
    if (found.length) paras = found;
  }
  if (!paras) {
    if (t.includes('"paras"')) throw new Error("模型输出无法解析，请重试一次");
    paras = t.split(/\n{2,}/).map(x => ({ beat: null, text: x.replace(/\n/g, "") })).filter(p => p.text.trim());
  }
  const unesc = (s) => s.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  const tidy = (s) => s.replace(/\s*\n\s*/g, "").replace(/([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])\s+(?=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])/g, "$1").trim();
  const out = paras
    .map((p, i) => ({ id: "p" + (i + 1), beat: SCN_BEAT_MAP[p.beat] || null, text: tidy(unesc((p.text || "").toString())) }))
    .filter(p => p.text);
  if (!out.length) throw new Error("未能解析出正文段落");
  return out;
}

/* ---- 确定性质检：可解释、可复算 ---- */
function scnSentencesOf(text) {
  return text.split(/(?<=[。！？；…])/).map(s => s.trim()).filter(s => s.length > 1);
}
/* ---- 质检阈值：从 Tweaks 面板读，改动对已生成稿实时重算 ---- */
function scnQcTh() {
  const t = window.__scnQcTh || {};
  return { short: t.short || 55, repeat: t.repeat || 30, long: t.long || 64 };
}

function scnQC(paras, reactive) {
  const th = scnQcTh();
  const all = paras.map(p => p.text).join("");
  const sents = paras.flatMap(p => scnSentencesOf(p.text));
  const n = sents.length || 1;
  const shortRate = Math.round(100 * sents.filter(s => s.length <= 20).length / n);
  const openers = {};
  sents.forEach(s => { const k = s.slice(0, 2); openers[k] = (openers[k] || 0) + 1; });
  /* 句式重复：同一起手出现 ≥ 3 次才计（限知视角里「她」起句是正常的） */
  const repeated = Object.values(openers).filter(c => c >= 3).reduce((a, c) => a + c, 0);
  const repeatRate = Math.round(100 * repeated / n);
  const longs = sents.filter(s => s.length > th.long);

  // 把风险句标进段落 parts（写作台同款高亮）
  const risks = [];
  const draft = paras.map(p => {
    const parts = [];
    let rest = p.text;
    scnSentencesOf(p.text).forEach(s => {
      const at = rest.indexOf(s);
      if (at < 0) return;
      const isLong = s.length > th.long;
      const isRep = openers[s.slice(0, 2)] > 2;
      if (isLong || isRep) {
        if (at > 0) parts.push({ text: rest.slice(0, at) });
        const tip = isLong ? `超长句（${s.length} 字 > 阈值 ${th.long}）：考虑拆成两到三句` : `句首「${s.slice(0, 2)}」重复 ${openers[s.slice(0, 2)]} 次：换个起手`;
        parts.push({ risk: isLong ? "pace" : "repeat", sev: isLong ? "mid" : "low", text: s, tip });
        risks.push({ sev: isLong ? "mid" : "low" });
        rest = rest.slice(at + s.length);
      }
    });
    if (rest) parts.push({ text: rest });
    return { id: p.id, beat: p.beat, parts: parts.length ? parts : [{ text: p.text }] };
  });

  const metrics = [
    { label: "短句率",   pct: shortRate,  target: th.short,  val: shortRate + "%", tone: shortRate >= th.short ? "ok" : "warn" },
    { label: "句式重复", pct: repeatRate, target: th.repeat, val: repeatRate + "%", tone: repeatRate <= th.repeat ? "ok" : "warn" },
    { label: "超长句",   pct: Math.min(100, longs.length * 20), target: 20, val: longs.length + " 句", tone: longs.length <= 1 ? "ok" : "warn" },
  ];
  const beats = reactive ? ["goal", "conflict", "exit"] : ["goal", "conflict", "setback", "exit"];
  const noteOf = reactive
    ? { goal: "反应拍", conflict: "两难拍", exit: "决定拍" }
    : { goal: "目标拍", conflict: "冲突拍", setback: "挫败拍", exit: "出口拍" };
  const alignment = beats.map(b => {
    const p = paras.find(x => x.beat === b);
    return { beat: b, para: p ? p.id : null, status: p ? "ok" : "pend", note: p ? `${noteOf[b]}落在 ${p.id}` : `模型未标注${noteOf[b]}` };
  });
  const alignOk = alignment.filter(a => a.status === "ok").length;
  const warns = metrics.filter(m => m.tone === "warn").length + (risks.length ? 1 : 0);
  const words = all.replace(/\s/g, "").length;
  return {
    draft, metrics, alignment, words,
    verdict: {
      qc: warns ? "通过 · 有风险" : "通过",
      risks: risks.length ? `${risks.length} 处风险句` : "无风险句",
      align: `戏剧卡 ${alignOk}/${beats.length} 对齐`,
      words,
    },
  };
}

/* ---- 完整一跑：后端 scenes run 管线（FE-ALIGN F6）----
   投递 run job（POST run/jobs）→ 轮询 run-jobs/{id} → workbench 取产出
   → 本地确定性复检。失败/阻塞给明确引导（执行契约缺字段 / LLM 未启用 /
   预检不过），不装假进度。scnBuildPrompt 保留作提示词参考（管线内由
   后端 config/prompts.yaml 组装）。 */
function scnFriendly(e) {
  const code = (e && e.code) || "";
  const msg = (e && e.message) || String(e || "");
  if (code === "SCENE_EXECUTION_CONTRACT_BLOCKED") {
    const miss = (((e && e.details) || {}).missing_fields || []).join("、");
    return new Error(`这一场的执行契约还缺关键字段${miss ? `（${miss}）` : ""}——先在章节编排把场景卡补全，或走「构思 → 物化」主路径生成完整场景卡。`);
  }
  if (/LLM/i.test(code) || /llm|provider|api.?key/i.test(msg)) {
    return new Error("AI 起草需要可用的 LLM：请到「系统设置 → 模型与接入」配置并启用后重试。原始信息：" + msg);
  }
  return new Error("起草失败：" + msg);
}

async function scnRun(item, note, prevText) { // eslint-disable-line no-unused-vars
  const { apiGet, apiPost } = await import("./lib/client.js");
  const sceneId = WsCatalog && WsCatalog.__backendSceneId
    ? await WsCatalog.__backendSceneId(item.sid)
    : null;
  if (!sceneId) throw new Error("这一场还没同步到后端目录——稍候片刻或刷新后重试。");
  const t0 = Date.now();
  let job;
  // G3：作者改写指令随任务下发（后端注入风格生成阶段的提示词）
  const body = note && String(note).trim() ? { author_note: String(note).trim().slice(0, 500) } : {};
  try { job = await apiPost(`/api/v1/scenes/${sceneId}/run/jobs`, body); } catch (e) { throw scnFriendly(e); }
  const TERMINAL = ["completed", "blocked", "failed", "cancelled"];
  let last = job;
  const deadline = Date.now() + 5 * 60 * 1000;
  while (!TERMINAL.includes(last.status)) {
    if (Date.now() > deadline) throw new Error("起草超时（5 分钟）——后台任务可能仍在运行，稍后可在质检台查看产出。");
    await new Promise(r => setTimeout(r, 2000));
    try { last = await apiGet(`/api/v1/run-jobs/${job.job_id}`); } catch (e) {}
  }
  /* 终态后先看产出：需人工审阅的 blocked 也可能已有草稿，照实呈现 */
  let wb = null;
  try { wb = await apiGet(`/api/v1/scenes/${sceneId}/workbench`); } catch (e) {}
  const content = (wb && ((wb.final_scene && wb.final_scene.content)
    || (wb.style_draft && wb.style_draft.content)
    || (wb.neutral_draft && wb.neutral_draft.content))) || "";
  if (!content.trim()) {
    throw scnFriendly({ code: last.error_code || "", message: last.error_text || `任务以「${last.status}」结束且没有产出正文（${last.current_step || "—"}）` });
  }
  const paras = content.split(/\n{2,}|\n/).map((x, i) => ({ id: "p" + (i + 1), beat: null, text: x.trim() })).filter(p => p.text);
  const hit = item.sid && WsCatalog ? WsCatalog.sceneById(item.sid) : null;
  const reactive = ((hit && hit.scene.kind) || item.kind || "").includes("反应");
  const qc = scnQC(paras, reactive);
  const secs = Math.round((Date.now() - t0) / 1000);
  const tm = (off) => new Date(t0 + off * 1000).toTimeString().slice(0, 8);
  const pipeState = wb && wb.scene_run_state ? wb.scene_run_state.scene_status : last.status;
  qc.log = [
    { t: tm(0), who: "system", text: "已投递后端起草任务（scenes run 管线：预检 → 蓝图 → 起草 → 硬/软双层质检）" },
    note ? { t: tm(0), who: "system", text: "改写指令已随任务下发（注入风格生成阶段，优先级最高）" } : null,
    { t: tm(secs), who: "pipeline", text: `管线结束 · 任务 ${last.status} · 场景状态 ${pipeState} · ${qc.words} 字 · 用时 ${secs}s` },
    last.status === "blocked" ? { t: tm(secs), who: "pipeline", text: "管线把这稿停在人工审阅/重写闸门——草稿已取回，可在此采纳或回管线处理" } : null,
    { t: tm(secs + 1), who: "qc", text: `本地复检：短句率 ${qc.metrics[0].val} · 句式重复 ${qc.metrics[1].val} · ${qc.verdict.risks}` },
  ].filter(Boolean);
  qc.cost = [
    { k: "起草", v: `后端管线 · ${secs}s` },
    { k: "质检", v: "硬/软双层 + 本地复检" },
    { k: "字数", v: String(qc.words), mono: true },
  ];
  return qc;
}

/* ---- 归档：写入写作器正文 + 字数回写 + 场景卡置 done ---- */
function scnEscape(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function scnAdoptToDoc(sid, draft) {
  if (!sid || !WsCatalog) return { ok: false, reason: "没有场景卡" };
  const html = (draft || []).map(p => "<p>" + scnEscape(p.parts.map(x => x.text).join("")) + "</p>").join("");
  const text = (draft || []).map(p => p.parts.map(x => x.text).join("")).join("");
  const key = wsKey ? wsKey("wr-doc:" + sid) : "wr-doc:" + sid;
  let existing = "";
  try { existing = localStorage.getItem(key) || ""; } catch (e) {}
  const hasReal = existing && existing.replace(/<[^>]+>/g, "").replace(/\s/g, "").length > 0 && !existing.includes("在这里开始写这一场");
  if (hasReal && !window.confirm("这一场在写作器里已有正文。归档会覆盖现有正文（写作器的版本会丢失），确定继续？")) {
    return { ok: false, reason: "已取消" };
  }
  /* FE-ALIGN P8：正文写穿 author-drafts 主路径（WrDocs 缓存+PATCH），
     不再绕过后端直写 localStorage */
  try {
    if (window.WrDocs) window.WrDocs.save(sid, html);
    else localStorage.setItem(key, html);
  } catch (e) { return { ok: false, reason: "写入失败" }; }
  const hit = WsCatalog.sceneById(sid);
  const prev = hit && typeof hit.scene.words === "number" ? hit.scene.words : 0;
  const count = text.replace(/\s/g, "").length;
  try { WsCatalog.recordSceneWords(sid, count, prev); } catch (e) {}
  try {
    WsCatalog.set(WsCatalog.get().map(c => ({
      ...c, scenes: (c.scenes || []).map(s => s.sid === sid ? { ...s, state: "done" } : s),
    })));
  } catch (e) {}
  return { ok: true, words: count };
}

/* 已生成稿件的实时重算：阈值改动后，风险标记 / 指标 / 判词跟着变 */
function scnReQC(draft, kind) {
  try {
    const paras = (draft || []).map(p => ({ id: p.id, beat: p.beat, text: p.parts.map(x => x.text).join("") }));
    if (!paras.length) return null;
    return scnQC(paras, (kind || "").includes("反应"));
  } catch (e) { return null; }
}

/* ---- 选场器数据：目录里可入列的场 ---- */
function scnPickList(queuedSids) {
  const q = new Set(queuedSids || []);
  try {
    return (WsCatalog ? WsCatalog.get() : []).map(c => ({
      id: c.id, n: c.n, title: c.title,
      scenes: (c.scenes || []).map(s => ({
        sid: s.sid, title: s.title, kind: s.kind, state: s.state,
        ready: !!((s.goal || "").trim() && !(s.goal || "").includes("待规划")),
        queued: q.has(s.sid),
        hasDraft: !!scnRunLoad(s.sid),
      })),
    })).filter(c => c.scenes.length);
  } catch (e) { return []; }
}

Object.assign(window, { scnRun, scnAdoptToDoc, scnPickList, scnRunLoad, scnRunSave, scnQueueLoad, scnQueueSave, scnQC, scnReQC, scnBuildPrompt, scnParseDraft });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { scnRun, scnAdoptToDoc, scnPickList, scnRunLoad, scnRunSave, scnQueueLoad, scnQueueSave, scnQC, scnReQC, scnBuildPrompt, scnParseDraft };
