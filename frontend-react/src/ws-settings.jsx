import React from "react";
import { I } from "./icons.jsx";
import { WsWorks, useActiveWork } from "./ws-works.jsx";
import { WsCatalog } from "./ws-catalog.jsx";

/* global React, I */
const { useState: useSt6 } = React;

/* ==========================================================
   Settings — 设置
   Tabs: 项目 · 写作偏好 · AI 模型 · 外观 · 数据
   ----------------------------------------------------------
   · 项目页读写 WsWorks（当前作品），状态由 WsCatalog 实时汇总
   · 写作偏好 / AI 偏好持久化到全局 ws_prefs_v1
   · 外观直接接 tweaks（与「调节舒适度」同源）
   · 数据页：导入导出跳转真实模块；危险区是真实操作
   ========================================================== */

const S_TABS = [
  { id: "project",  label: "项目", icon: "Folder" },
  { id: "writing",  label: "写作偏好", icon: "Pen" },
  { id: "ai",       label: "AI 模型", icon: "Sparkles" },
  { id: "appear",   label: "外观",  icon: "Type" },
  { id: "data",     label: "数据 & 安全", icon: "ShieldCheck" },
];

/* ---- 全局偏好持久化（跨作品） ---- */
const SET_PREFS_LS = "ws_prefs_v1";
function setPrefsLoad() { try { return JSON.parse(localStorage.getItem(SET_PREFS_LS)) || {}; } catch (e) { return {}; } }
function usePref(key, def) {
  const [v, setV] = useSt6(() => { const all = setPrefsLoad(); return all[key] !== undefined ? all[key] : def; });
  const set = (nv) => {
    setV(nv);
    try { const all = setPrefsLoad(); all[key] = nv; localStorage.setItem(SET_PREFS_LS, JSON.stringify(all)); } catch (e) {}
  };
  return [v, set];
}

function WsSettings({ go, t, setTweak }) {
  const [tab, setTab] = useSt6("project");

  return (
    <div className="page" data-screen-label="settings">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <div className="page-eyebrow">设置</div>
            <h1 className="page-title">让系统配合你，不是你配合系统</h1>
            <p className="page-subtitle">「项目」只影响当前作品；其余偏好是全局的。所有修改即改即存。</p>
          </div>
        </header>

        <div className="settings-cols">
          <aside className="settings-nav">
            {S_TABS.map(t => {
              const Ic = I[t.icon] || I.Dot;
              return (
                <button key={t.id} className={`settings-nav-btn ${tab === t.id ? "is-active" : ""}`} onClick={() => setTab(t.id)}>
                  <Ic size={15} /><span>{t.label}</span>
                </button>
              );
            })}
          </aside>

          <section className="settings-body">
            {tab === "project" && <ProjectSettings />}
            {tab === "writing" && <WritingSettings />}
            {tab === "ai" && <AISettings />}
            {tab === "appear" && <AppearSettings t={t} setTweak={setTweak} />}
            {tab === "data" && <DataSettings go={go} />}
          </section>
        </div>
      </div>
    </div>
  );
};

function Section({ title, desc, children }) {
  return (
    <section className="set-section">
      <header className="set-section-head">
        <h2 className="set-section-title text-serif">{title}</h2>
        {desc && <p className="set-section-desc">{desc}</p>}
      </header>
      <div className="set-section-body">{children}</div>
    </section>
  );
}

function Row({ label, hint, children }) {
  return (
    <div className="set-row">
      <div>
        <div className="set-row-label">{label}</div>
        {hint && <div className="set-row-hint">{hint}</div>}
      </div>
      <div className="set-row-ctl">{children}</div>
    </div>
  );
}

function Toggle({ on, onChange }) {
  return (
    <button className={`toggle ${on ? "is-on" : ""}`} onClick={() => onChange(!on)} aria-label="toggle">
      <span className="toggle-knob" />
    </button>
  );
}

function Segmented({ options, value, onChange }) {
  return (
    <div className="seg">
      {options.map(o => (
        <button key={o.value} className={`seg-btn ${value === o.value ? "is-active" : ""}`} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ===== 项目 — 读写当前作品（WsWorks），状态来自目录汇总 ===== */
function ProjectSettings() {
  const work = useActiveWork ? useActiveWork() : { id: "", title: "", genre: "", sub: "", wordsTarget: 0, wordsTargetDay: 0, streak: 0 };
  const totals = WsCatalog ? WsCatalog.totals() : { words: 0, written: 0, planned: 0, today: 0 };
  const save = (patch) => { if (WsWorks && work.id) WsWorks.update(work.id, patch); };
  const num = (e) => { const n = parseInt(e.target.value, 10); return Number.isFinite(n) && n > 0 ? n : null; };
  const pct = work.wordsTarget ? Math.min(100, Math.round((totals.words / work.wordsTarget) * 100)) : 0;

  return (
    <>
      <Section title="项目信息" desc={`当前作品《${work.title}》。改完即存，左上角书架与主页同步更新。`}>
        <Row label="项目名" hint="将出现在导航、主页与导出。">
          <input className="input" key={work.id + ":t"} defaultValue={work.title}
            onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== work.title) save({ title: v }); }} />
        </Row>
        <Row label="题材">
          <input className="input" key={work.id + ":g"} defaultValue={work.genre}
            onBlur={(e) => { const v = e.target.value.trim(); if (v !== work.genre) save({ genre: v }); }} />
        </Row>
        <Row label="一句话简介">
          <input className="input" key={work.id + ":s"} defaultValue={work.sub}
            onBlur={(e) => { const v = e.target.value.trim(); if (v !== work.sub) save({ sub: v }); }} />
        </Row>
        <Row label="目标字数">
          <input className="input" type="number" step="10000" key={work.id + ":w"} defaultValue={work.wordsTarget}
            onBlur={(e) => { const n = num(e); if (n) save({ wordsTarget: n }); }} />
        </Row>
        <Row label="每日目标" hint="主页「今日」进度条的分母。">
          <input className="input" type="number" step="100" key={work.id + ":d"} defaultValue={work.wordsTargetDay}
            onBlur={(e) => { const n = num(e); if (n) save({ wordsTargetDay: n }); }} />
        </Row>
      </Section>
      <Section title="项目状态" desc="由章节目录实时汇总，与主页 / 书架同源。">
        <Row label="完成度"><div className="set-readonly">{pct}% · {totals.written} / {totals.planned} 章 · {totals.words.toLocaleString()} 字</div></Row>
        <Row label="今日已写"><div className="set-readonly">{(totals.today || 0).toLocaleString()} 字 · 连续 {work.streak || 0} 天</div></Row>
      </Section>
    </>
  );
}

/* ===== 写作偏好 — 全局持久化 ===== */
function WritingSettings() {
  const [autosave, setAutosave] = usePref("autosave", true);
  const [indent, setIndent] = usePref("indent", "em");
  const [spell, setSpell] = usePref("spell", "name");
  const [diction, setDiction] = usePref("diction", "zh-mainland");
  const [punct, setPunct] = usePref("punct", "typographic");
  return (
    <>
      <Section title="写作习惯" desc="影响写作房间的编辑体验。">
        <Row label="自动保存" hint="改动后 3 秒静止自动保存。"><Toggle on={autosave} onChange={setAutosave} /></Row>
        <Row label="行首缩进">
          <Segmented options={[
            { value: "none",   label: "不缩进" },
            { value: "two",    label: "两空格" },
            { value: "em",     label: "全角两字" },
          ]} value={indent} onChange={setIndent} />
        </Row>
        <Row label="拼写检查">
          <Segmented options={[
            { value: "off",  label: "关闭" },
            { value: "name", label: "只查人名地名" },
            { value: "all",  label: "全部" },
          ]} value={spell} onChange={setSpell} />
        </Row>
      </Section>

      <Section title="文本规范" desc="保存与导出时统一执行。">
        <Row label="行文规范">
          <Segmented options={[
            { value: "zh-mainland", label: "大陆" },
            { value: "zh-tw",       label: "繁体" },
            { value: "literary",    label: "文学体" },
          ]} value={diction} onChange={setDiction} />
        </Row>
        <Row label="标点">
          <Segmented options={[
            { value: "typographic", label: "全角" },
            { value: "ascii",       label: "半角" },
            { value: "mixed",       label: "混排" },
          ]} value={punct} onChange={setPunct} />
        </Row>
      </Section>
    </>
  );
}

/* ===== AI 模型 — 全局持久化 ===== */
function AISettings() {
  const [primary, setPrimary] = usePref("aiPrimary", "haiku");
  const [reviewer, setReviewer] = usePref("aiReviewer", "sonnet");
  const [candN, setCandN] = usePref("aiCandN", 3);
  const [allowRef, setAllowRef] = usePref("aiAllowRef", true);
  const [strict, setStrict] = usePref("aiStrict", "normal");
  return (
    <>
      <Section title="模型" desc="选择用于候选生成与改写的模型。">
        <Row label="主力模型" hint="日常的续写、改写与候选生成。">
          <Segmented options={[
            { value: "haiku",   label: "Haiku" },
            { value: "sonnet",  label: "Sonnet" },
            { value: "opus",    label: "Opus" },
          ]} value={primary} onChange={setPrimary} />
        </Row>
        <Row label="审稿模型" hint="QC、设定冲突检测、参考相似度。">
          <Segmented options={[
            { value: "haiku", label: "Haiku" },
            { value: "sonnet", label: "Sonnet" },
          ]} value={reviewer} onChange={setReviewer} />
        </Row>
      </Section>

      <Section title="AI 行为">
        <Row label="生成候选数" hint="每次「再生」产出的候选条数。">
          <Segmented options={[{value:2,label:"2"},{value:3,label:"3"},{value:5,label:"5"}]} value={candN} onChange={setCandN} />
        </Row>
        <Row label="允许引用参考画像" hint="关闭后所有生成不再受参考画像影响。"><Toggle on={allowRef} onChange={setAllowRef} /></Row>
        <Row label="复刻检查严格度">
          <Segmented options={[
            { value: "lax",    label: "宽松" },
            { value: "normal", label: "标准" },
            { value: "strict", label: "严格" },
          ]} value={strict} onChange={setStrict} />
        </Row>
      </Section>
    </>
  );
}

/* ===== 外观 — 直接接 tweaks（与「调节舒适度」同一份状态） ===== */
function AppearSettings({ t, setTweak }) {
  const theme = t ? t.theme : "day";
  const fontSize = (t && t.fontSize) || 18;
  const lh = (t && t.lineHeight) || 2.05;
  const lhVal = lh <= 1.9 ? "snug" : lh >= 2.25 ? "airy" : "normal";
  const set = (k, v) => setTweak && setTweak(k, v);
  return (
    <>
      <Section title="主题" desc="全局生效，与左下角昼夜切换同源。">
        <Row label="模式">
          <Segmented options={[
            { value: "day",   label: "白昼" },
            { value: "dusk",  label: "暮色" },
            { value: "night", label: "夜灯" },
          ]} value={theme} onChange={(v) => set("theme", v)} />
        </Row>
        <Row label="稿纸纹理"><Toggle on={!!(t && t.texture)} onChange={(v) => set("texture", v)} /></Row>
      </Section>

      <Section title="正文排版" desc="影响写作房间的手感，与「调节舒适度」同一份设置。">
        <Row label="字号" hint={`当前 ${fontSize}px`}>
          <input type="range" min="14" max="22" value={fontSize} onChange={(e) => set("fontSize", parseInt(e.target.value, 10))} className="range" />
        </Row>
        <Row label="行距">
          <Segmented options={[
            { value: "snug",  label: "紧凑" },
            { value: "normal",label: "标准" },
            { value: "airy",  label: "宽松" },
          ]} value={lhVal} onChange={(v) => set("lineHeight", v === "snug" ? 1.8 : v === "airy" ? 2.3 : 2.05)} />
        </Row>
      </Section>
    </>
  );
}

/* ===== 数据 & 安全 — 真实动作 ===== */
function DataSettings({ go }) {
  const work = WsWorks ? WsWorks.active() : { id: "", title: "—" };
  const isSeed = WsWorks ? WsWorks.isSeed(work.id) : true;
  const worksN = WsWorks ? WsWorks.list().length : 1;

  const resetWork = () => {
    if (!window.confirm(
      `重置《${work.title}》？\n清空这部作品在本机的全部编辑（章节、构思、正文、待办、回收站），` +
      (isSeed ? "回到示例种子状态。" : "变回一部空白作品。") +
      "\n此操作无法撤销——建议先去「导入导出」导一份数据包。"
    )) return;
    try {
      const suffix = "::" + work.id;
      const doomed = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.slice(-suffix.length) === suffix) doomed.push(k);
      }
      doomed.forEach(k => localStorage.removeItem(k));
    } catch (e) {}
    location.reload();
  };

  const deleteWork = () => {
    if (!window.confirm(`删除《${work.title}》？\n这部作品会连同全部数据进入回收站，可在「回收站」里整体恢复。`)) return;
    WsWorks.remove(work.id);
    if (go) go("home");
  };

  return (
    <>
      <Section title="导入 / 导出" desc="全书稿与数据包的导出、备份恢复，都在「导入导出」模块完成。">
        <Row label="导出全书稿" hint="目录 + 正文编译成 Markdown。">
          <button className="btn btn-ghost" onClick={() => go && go("interop")}>去导出 <I.ArrowRight size={13} /></button>
        </Row>
        <Row label="备份数据包" hint="当前作品的全部状态，可迁移可恢复。">
          <button className="btn btn-ghost" onClick={() => go && go("interop")}>去备份 <I.ArrowRight size={13} /></button>
        </Row>
      </Section>
      <Section title="危险区" desc="谨慎操作。删除可从回收站找回；重置不可撤销。">
        <Row label="重置本作品" hint={isSeed ? "清空本机编辑，回到示例种子状态。" : "清空全部内容，变回一部空白作品。"}>
          <button className="btn btn-ghost" style={{ borderColor: "var(--rose)", color: "var(--rose)" }} onClick={resetWork}>重置…</button>
        </Row>
        <Row label="删除本作品" hint={isSeed ? "示例作品是演示基底，不可删除。" : worksN <= 1 ? "至少保留一部作品。" : "整部进入回收站，可恢复。"}>
          <button className="btn btn-ghost" disabled={isSeed || worksN <= 1}
            style={{ borderColor: "var(--rose)", color: "var(--rose)", opacity: (isSeed || worksN <= 1) ? 0.45 : 1 }}
            onClick={deleteWork}>删除…</button>
        </Row>
      </Section>
    </>
  );
}

Object.assign(window, { WsSettings });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { WsSettings };
