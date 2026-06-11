import React from "react";
import { I } from "./icons.jsx";
import { CT_CONTINUITY, CT_LAYERS, CT_RUBRIC_DIMS, CT_SPINE, ctLayer, ctLayerName } from "./ct-data.jsx";
import { ctHealthColor } from "./ct-map.jsx";

/* global React, I, CT_LAYERS, CT_CONTINUITY, CT_SPINE, CT_RUBRIC_DIMS, ctLayer, ctLayerName, ctHealthColor */
/* ==========================================================
   构思控制塔 — 实时联动编辑
   编辑某层的「信号字段」→ 自动跑连续性校验 + 重算 5 维评分，
   并把影响推到脊柱绑定、下游、顶部指标。

   单一数据源：signals。其余一切（层健康度 / 连续性 / 脊柱 / 指标）
   都由 ctDerive(signals) 派生，保证联动一致。
   ========================================================== */
const { useState: useES } = React;

/* 原始（基线）维度快照在 ctComputeDims/ctScore 定义后再构建，见文件下方 CT_ORIG_DIMS。 */

/* 可编辑层的信号模型。floorDims = 所有文本信号「未填」时的维度底座；
   字段 dims 增量在「填好」时叠加。number 字段只影响连续性，不直接动分。 */
const CT_EDIT_MODEL = {
  outline: {
    note: "改 07 联动三套系统：遇难人数→连续性校验、灾难落点→因果锁链评分 + 脊柱落点。",
    floorDims: { fractal: 72, causal: 54, character: 66, scenable: 70, promise: 74 },
    fields: [
      { key: "deaths", label: "那场潮汐遇难人数", type: "number", unit: "人",
        wires: [{ k: "cont", t: "连续性 · 遇难人数" }], hint: "06 角色背景记为 31，两处须一致",
        cont: "deaths" },
      { key: "act2", label: "第二幕灾难落点（灾二）", type: "text", minLen: 10,
        placeholder: "占位：第 10 章，灾二尚未具体化…",
        sample: "第 10 章：林岑查到父亲死于周岚当年的撤离决定，「记录即正义」的信念在此崩塌。",
        wires: [{ k: "rubric", t: "评分 · 因果锁链" }, { k: "spine", t: "脊柱 · 灾二落点" }],
        dims: { causal: 16, fractal: 6, scenable: 6 }, spine: { idx: 1, layer: "outline" } },
      { key: "act3", label: "第三幕灾难落点（灾三）", type: "text", minLen: 10,
        placeholder: "占位：第 14 章，灾三尚未具体化…",
        sample: "第 14 章：周岚销毁母本、向林岑摊牌，逼她在公开真相与共谋之间抉择。",
        wires: [{ k: "rubric", t: "评分 · 因果锁链" }, { k: "spine", t: "脊柱 · 灾三落点" }],
        dims: { causal: 14, fractal: 4, scenable: 4 }, spine: { idx: 2, layer: "outline" } },
    ],
  },
  backstory: {
    note: "改 06 联动三套系统：遇难人数/林岑年龄→连续性、旧伤→角色驱动评分、隐秘恐惧→可落场评分 + 灾二情感载荷。",
    floorDims: { fractal: 64, causal: 72, character: 80, scenable: 60, promise: 60 },
    fields: [
      { key: "deaths", label: "那场潮汐遇难人数", type: "number", unit: "人",
        wires: [{ k: "cont", t: "连续性 · 遇难人数" }], hint: "07 长篇大纲记为 30，两处须一致",
        cont: "deaths" },
      { key: "linAge", label: "林岑年龄", type: "number", unit: "岁",
        wires: [{ k: "cont", t: "连续性 · 林岑年龄" }], hint: "04 角色摘要须一致",
        cont: "lin_age" },
      { key: "wound", label: "第一道裂缝（旧伤）", type: "text", minLen: 8,
        placeholder: "她最深的那道旧伤是…",
        sample: "那场潮汐之后，没有人来认领她写下的对不起。",
        wires: [{ k: "rubric", t: "评分 · 角色驱动" }],
        dims: { character: 6, promise: 6 } },
      { key: "secretFear", label: "隐秘恐惧", type: "text", minLen: 8,
        placeholder: "她最怕被人发现什么…",
        sample: "她怕被人发现：她写下的每一句对不起，其实都在替自己开脱。",
        wires: [{ k: "rubric", t: "评分 · 可落场" }, { k: "spine", t: "脊柱 · 灾二情感载荷" }],
        dims: { scenable: 6, promise: 4 }, spineFeedback: { key: "d2charge", label: "灾二情感载荷" } },
    ],
  },
  characters: {
    note: "改 04 联动三套系统：年龄→连续性、价值观对撞→角色驱动评分 + 道德前提支撑、林岑目标→可落场/因果评分。",
    floorDims: { fractal: 88, causal: 74, character: 90, scenable: 70, promise: 84 },
    fields: [
      { key: "zhouAge", label: "周岚年龄", type: "number", unit: "岁",
        wires: [{ k: "cont", t: "连续性 · 周岚年龄" }], hint: "08 角色全档案记为 53",
        cont: "zhou_age" },
      { key: "linAge", label: "林岑年龄", type: "number", unit: "岁",
        wires: [{ k: "cont", t: "连续性 · 林岑年龄" }], hint: "06 角色背景须一致",
        cont: "lin_age" },
      { key: "clash", label: "价值观对撞", type: "text", minLen: 8,
        placeholder: "主角与对手的价值观如何正面相撞…",
        sample: "林岑信「白纸黑字」× 周岚信「活着的人」——同一句真相，一个要公开，一个要抹去。",
        wires: [{ k: "rubric", t: "评分 · 角色驱动" }, { k: "spine", t: "脊柱 · 道德前提支撑" }],
        dims: { character: 4 }, spineFeedback: { key: "premise", label: "道德前提支撑" } },
      { key: "linGoal", label: "林岑的具体目标", type: "text", minLen: 8,
        placeholder: "她在这个故事里要的、看得见的东西…",
        sample: "查清整座潮汐城的灾难档案被谁改写、改了多少、为什么。",
        wires: [{ k: "rubric", t: "评分 · 可落场" }, { k: "rubric", t: "评分 · 因果锁链" }],
        dims: { scenable: 8, causal: 6 } },
    ],
  },
};

/* 初始信号（与 CT_LAYERS 的当前显示一致） */
const CT_INITIAL_SIGNALS = {
  outline:    { deaths: 30, act2: "", act3: "" },
  backstory:  { deaths: 31, linAge: 28, wound: "那场潮汐之后，没有人来认领她写下的对不起。", secretFear: "她怕被人发现：她写下的每一句对不起，其实都在替自己开脱。" },
  characters: { zhouAge: 53, linAge: 28, clash: "林岑信「白纸黑字」× 周岚信「活着的人」——同一句真相，一个要公开，一个要抹去。", linGoal: "查清整座潮汐城的灾难档案被谁改写、改了多少、为什么。" },
};

function ctFieldGood(field, val) {
  if (field.type === "number") return val != null && val !== "";
  return String(val || "").trim().length >= (field.minLen || 8);
}
function ctComputeDims(layerKey, sig) {
  const model = CT_EDIT_MODEL[layerKey];
  if (!model) return { ...CT_ORIG_DIMS[layerKey] };
  const dims = { ...model.floorDims };
  model.fields.forEach(f => {
    if (f.dims && ctFieldGood(f, sig[f.key])) {
      Object.entries(f.dims).forEach(([d, v]) => { dims[d] = Math.min(100, (dims[d] || 0) + v); });
    }
  });
  return dims;
}
function ctScore(dims) {
  const ks = Object.keys(dims);
  return Math.round(ks.reduce((a, k) => a + dims[k], 0) / ks.length);
}
function ctContStatus(values) {
  if (values.some(v => v.num == null)) return "unverifiable";
  const nums = values.map(v => v.num);
  return nums.every(n => n === nums[0]) ? "ok" : "conflict";
}

/* 原始（基线）维度快照——用同一套公式从初始信号派生，保证「未改动时 Δ=0」 */
const CT_ORIG_DIMS = Object.fromEntries(CT_LAYERS.map(l => {
  const dims = CT_EDIT_MODEL[l.key] ? ctComputeDims(l.key, CT_INITIAL_SIGNALS[l.key]) : { ...l.health.dims };
  return [l.key, { ...dims, score: ctScore(dims) }];
}));

/* 核心：signals → 全套派生状态 */
/* 09 场景列表：把画布上的实时织线 / 节奏信号折算进质量五维。
   紧绷 → 读者契约 + 可落场；扎堆/缺折射 → 分形一致 + 角色驱动；缺冲突 → 可落场 + 因果。
   与织线图谱 / 第 9 步验收门同一份数据，所以改了场景表，质量矩阵会跟着动。 */
function ctSceneLive(base) {
  const dims = { ...base.health.dims };
  const flags = [];
  const read = window.ctReadScenes;
  const scenes = read ? read() : { list: [], lines: [] };
  const list = scenes.list || [], lines = scenes.lines || [];
  if (!list.length || !window.s2PacingRuns) return { health: base.health, structFlags: flags };
  const pacing = window.s2PacingRuns(list);
  const stats = window.s2LineStats(list, lines);
  const tightMax = pacing.tight.length ? Math.max(...pacing.tight.map(r => r.len)) : 0;
  const slackMax = pacing.slack.length ? Math.max(...pacing.slack.map(r => r.len)) : 0;
  const clustered = stats.filter(s => s.clustered).length;
  const noRefract = stats.filter(s => s.noRefract).length;
  const noCru = list.filter(s => !(s.crucible || "").trim()).length;
  const clamp = (x) => Math.max(0, Math.min(100, Math.round(x)));
  if (tightMax >= 3) { dims.promise -= 14; dims.scenable -= 6; flags.push({ t: `节奏紧绷 ×${tightMax}`, tone: "rose", q: `连续 ${tightMax} 场主动，缺反应喘息` }); }
  if (slackMax >= 3) { dims.promise -= 8; flags.push({ t: `节奏松弛 ×${slackMax}`, tone: "gold", q: `连续 ${slackMax} 场反应，推进不足` }); }
  if (clustered) { dims.fractal -= 8 * clustered; dims.character -= 4 * clustered; flags.push({ t: `支线扎堆 ×${clustered}`, tone: "gold", q: `${clustered} 条支线集中在窄段，像绕路而非编织` }); }
  if (noRefract) { dims.fractal -= 10 * noRefract; flags.push({ t: `缺折射 ×${noRefract}`, tone: "rose", q: `${noRefract} 条线未折射道德前提，可能是闲笔` }); }
  if (noCru) { dims.scenable -= 8 * noCru; dims.causal -= 4 * noCru; flags.push({ t: `缺冲突 ×${noCru}`, tone: "rose", q: `${noCru} 场无坩埚` }); }
  Object.keys(dims).forEach(k => { dims[k] = clamp(dims[k]); });
  const score = Math.round(Object.values(dims).reduce((a, b) => a + b, 0) / Object.keys(dims).length);
  return { health: { dims, score }, structFlags: flags };
}

function ctDerive(signals) {
  /* 1. 连续性（仅 deaths / zhou_age 受信号驱动，其余静态） */
  const continuity = CT_CONTINUITY.map(item => {
    if (item.id === "deaths") {
      const values = [
        { layer: "backstory", label: "06 角色背景", num: +signals.backstory.deaths, val: `${signals.backstory.deaths} 人` },
        { layer: "outline", label: "07 长篇大纲", num: +signals.outline.deaths, val: `${signals.outline.deaths} 人` },
      ];
      const status = ctContStatus(values);
      return { ...item, values, status, note: status === "ok" ? "06 与 07 已统一，09 场景列表可安全引用。" : "06 与 07 数字不一致；09 场景列表灾难规模引用此数，须先统一。" };
    }
    if (item.id === "zhou_age") {
      const values = [
        { layer: "characters", label: "04 角色摘要", num: +signals.characters.zhouAge, val: `${signals.characters.zhouAge}` },
        { layer: "profile", label: "08 角色全档案", num: 53, val: "53" },
      ];
      return { ...item, values, status: ctContStatus(values), note: ctContStatus(values) === "ok" ? "两处一致。" : "04 与 08 年龄不一致，须统一。" };
    }
    if (item.id === "lin_age") {
      const values = [
        { layer: "characters", label: "04 角色摘要", num: +signals.characters.linAge, val: `${signals.characters.linAge}` },
        { layer: "backstory", label: "06 角色背景", num: +signals.backstory.linAge, val: `${signals.backstory.linAge}` },
      ];
      return { ...item, values, status: ctContStatus(values), note: ctContStatus(values) === "ok" ? "04 与 06 一致。" : "04 与 06 林岑年龄不一致，须统一。" };
    }
    return item;
  });

  /* 2. 层维度（可编辑层重算；09 场景列表由实时织线/节奏驱动；其余静态） */
  const layers = CT_LAYERS.map(l => {
    if (l.key === "scenes") {
      const live = ctSceneLive(l);
      return { ...l, health: live.health, structFlags: live.structFlags };
    }
    if (!CT_EDIT_MODEL[l.key]) return l;
    const dims = ctComputeDims(l.key, signals[l.key]);
    const score = ctScore(dims);
    /* deaths 冲突时，给涉及层一个一致性状态：仍可保持 approved，但分数已反映 */
    return { ...l, health: { dims, score } };
  });
  const layerMap = Object.fromEntries(layers.map(l => [l.key, l]));

  /* 3. 脊柱绑定（灾二/灾三的 outline 落点由 07 信号驱动） */
  const og = signals.outline;
  const clashF = CT_EDIT_MODEL.characters.fields.find(f => f.key === "clash");
  const fearF = CT_EDIT_MODEL.backstory.fields.find(f => f.key === "secretFear");
  const clashGood = ctFieldGood(clashF, signals.characters.clash);
  const fearGood = ctFieldGood(fearF, signals.backstory.secretFear);
  const spine = {
    ...CT_SPINE,
    extras: {
      premise: clashGood ? { tone: "sage", text: "支撑充分" } : { tone: "gold", text: "待夯实" },
      d2charge: fearGood ? { tone: "sage", text: "已注入" } : { tone: "gold", text: "偏薄" },
    },
    disasters: CT_SPINE.disasters.map((d, idx) => ({
      ...d,
      bindings: d.bindings.map(b => {
        if (b.layer !== "outline") return b;
        if (idx === 1) return { ...b, status: ctFieldGood(CT_EDIT_MODEL.outline.fields[1], og.act2) ? "ok" : "weak", at: ctFieldGood(CT_EDIT_MODEL.outline.fields[1], og.act2) ? "第 10 章 · 已落位" : "第 10 章（占位）" };
        if (idx === 2) return { ...b, status: ctFieldGood(CT_EDIT_MODEL.outline.fields[2], og.act3) ? "ok" : "weak", at: ctFieldGood(CT_EDIT_MODEL.outline.fields[2], og.act3) ? "第 14 章 · 已落位" : "第 14 章（占位）" };
        return b;
      }),
    })),
  };

  /* 4. 指标 */
  const metrics = {
    health: Math.round(layers.reduce((a, l) => a + l.health.score, 0) / layers.length),
    approved: layers.filter(l => l.state === "approved").length,
    alerts: continuity.filter(c => c.status === "conflict").length,
    stale: layers.filter(l => l.state === "stale").length,
  };

  return { layers, layerMap, continuity, spine, metrics };
}

/* ====== 实时联动编辑面板 ====== */
function CTLiveEdit({ layerKey, signals, onSignal, layerMap, continuity, spine, onClose, onSelect, onOpenStep }) {
  const model = CT_EDIT_MODEL[layerKey];
  if (!model) return null;
  const sig = signals[layerKey];
  const live = layerMap[layerKey];
  const orig = CT_ORIG_DIMS[layerKey];
  const l = ctLayer(layerKey);
  const feeds = l.feeds.filter(f => f !== "materialize");

  /* 受影响的连续性项 */
  const contIds = [...new Set(model.fields.filter(f => f.cont).map(f => f.cont))];
  const contItems = continuity.filter(c => contIds.includes(c.id));

  const statusTone = { ok: "sage", conflict: "rose", unverifiable: "slate", weak: "gold", missing: "rose" };
  const statusLabel = { ok: "一致", conflict: "冲突", unverifiable: "待补全", weak: "占位", missing: "未落场" };

  /* 受影响的脊柱：灾难落点（outline）与道德前提/情感载荷（04/06）*/
  const spineHits = [];
  model.fields.forEach(f => {
    if (f.spine) {
      const d = spine.disasters[f.spine.idx];
      const b = d.bindings.find(x => x.layer === f.spine.layer);
      spineHits.push({ label: d.id, at: b.at, tone: statusTone[b.status], text: statusLabel[b.status] });
    }
    if (f.spineFeedback) {
      const ex = (spine.extras || {})[f.spineFeedback.key] || { tone: "slate", text: "—" };
      spineHits.push({ label: f.spineFeedback.label, at: "由本字段驱动", tone: ex.tone, text: ex.text });
    }
  });

  return (
    <section className="ct-panel ct-inspector ct-live">
      <header className="ct-live-head">
        <span className="ct-live-ic"><I.Zap size={15} /></span>
        <div>
          <h3 className="ct-panel-title">实时联动编辑 · {l.num} {l.name}</h3>
          <p className="ct-panel-sub">{model.note}</p>
        </div>
        <button className="ct-blast-x" onClick={onClose} title="退出编辑"><span className="ct-x-glyph">×</span></button>
      </header>

      {/* 字段 */}
      <div className="ct-live-fields">
        {model.fields.map(f => (
          <div key={f.key} className="ct-live-field">
            <div className="ct-live-flabel">
              <span>{f.label}</span>
              <span className="ct-live-wires">
                {f.wires.map((w, i) => <span key={i} className={`ct-wire ct-wire-${w.k}`}>{w.t}</span>)}
              </span>
            </div>
            {f.type === "number" ? (
              <div className="ct-live-numrow">
                <button className="ct-num-btn" onClick={() => onSignal(layerKey, f.key, Math.max(0, (+sig[f.key]) - 1))}>−</button>
                <input className="ct-num-input" type="number" value={sig[f.key]}
                  onChange={(e) => onSignal(layerKey, f.key, e.target.value === "" ? "" : +e.target.value)} />
                <span className="ct-num-unit">{f.unit}</span>
                <button className="ct-num-btn" onClick={() => onSignal(layerKey, f.key, (+sig[f.key] || 0) + 1)}>+</button>
                {f.hint && <span className="ct-live-hint">{f.hint}</span>}
              </div>
            ) : (
              <div className="ct-live-textwrap">
                <textarea className="ct-live-text" rows={2} value={sig[f.key]} placeholder={f.placeholder}
                  onChange={(e) => onSignal(layerKey, f.key, e.target.value)} />
                {!ctFieldGood(f, sig[f.key]) && f.sample && (
                  <button className="ct-live-fill" onClick={() => onSignal(layerKey, f.key, f.sample)}><I.Wand size={12} /> 用示例填充</button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 联动反馈 */}
      <div className="ct-live-feedback">
        <div className="ct-live-fb-head"><I.Activity size={12} /> 本次联动</div>

        {/* 评分重算 */}
        <div className="ct-live-block">
          <div className="ct-live-block-h">评分重算 <span className="ct-live-score-now" style={{ color: ctHealthColor(live.health.score) }}>{orig.score} → {live.health.score}</span></div>
          <div className="ct-dims">
            {CT_RUBRIC_DIMS.map(d => {
              const o = orig[d.key], n = live.health.dims[d.key], delta = n - o;
              return (
                <div key={d.key} className="ct-dim">
                  <span className="ct-dim-label">{d.short}</span>
                  <span className="ct-dim-bar"><span style={{ width: `${n}%`, background: ctHealthColor(n) }} /></span>
                  <span className={`ct-dim-delta ${delta > 0 ? "up" : delta < 0 ? "down" : ""}`}>{delta === 0 ? n : (delta > 0 ? `▲${delta}` : `▼${-delta}`)}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* 连续性 */}
        {contItems.length > 0 && (
          <div className="ct-live-block">
            <div className="ct-live-block-h">连续性校验</div>
            {contItems.map(c => (
              <div key={c.id} className={`ct-live-cont is-${c.status}`}>
                <span className="ct-live-cont-fact">{c.fact}</span>
                <span className="ct-live-cont-vals">
                  {c.values.map((v, i) => <span key={i}>{v.num}{i < c.values.length - 1 ? " vs " : ""}</span>)}
                </span>
                <span className={`pill pill-${statusTone[c.status]} text-xs`}><span className="pill-dot" />{statusLabel[c.status]}</span>
              </div>
            ))}
          </div>
        )}

        {/* 脊柱落点 */}
        {spineHits.length > 0 && (
          <div className="ct-live-block">
            <div className="ct-live-block-h">脊柱联动</div>
            {spineHits.map((s, i) => (
              <div key={i} className="ct-live-spine">
                <span className="ct-live-spine-id">{s.label} · {s.at}</span>
                <span className={`pill pill-${s.tone} text-xs`}><span className="pill-dot" />{s.text}</span>
              </div>
            ))}
          </div>
        )}

        {/* 下游波及 */}
        {feeds.length > 0 && (
          <div className="ct-live-downstream">
            <I.AlertTriangle size={12} />
            <span>改动将波及下游：{feeds.map(f => (
              <button key={f} className="ct-live-down-chip" onClick={() => onSelect(f)}>{ctLayerName(f)}</button>
            ))}<b>建议复核</b></span>
          </div>
        )}
      </div>

      <button className="btn btn-primary ct-live-open" onClick={() => onOpenStep && onOpenStep(layerKey)}>
        <I.Layers size={14} /> 在逐步工作台展开本层全部字段
      </button>
    </section>
  );
}

Object.assign(window, {
  CT_EDIT_MODEL, CT_INITIAL_SIGNALS, CT_ORIG_DIMS,
  ctDerive, ctComputeDims, ctScore, ctFieldGood, CTLiveEdit,
});

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { CT_EDIT_MODEL, CT_INITIAL_SIGNALS, CT_ORIG_DIMS, ctDerive, ctComputeDims, ctScore, ctFieldGood, CTLiveEdit };
