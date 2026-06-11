import React from "react";
import ReactDOM from "react-dom";
import { I } from "./icons.jsx";
import { TweakRadio, TweakSection, TweakSlider, TweakToggle, TweaksPanel, useTweaks } from "./tweaks-panel.jsx";
import { WsWorks, useActiveWork, useWorks } from "./ws-works.jsx";
import { WRITER_TWEAK_DEFAULTS, WriterRoom, WriterTweaks } from "./ws-writer.jsx";
import { WsReview, useReviewBadge } from "./ws-review.jsx";
import { WsHome } from "./ws-home.jsx";
import { WsConstruct, WsSnowflake } from "./ws-snow.jsx";
import { WsFlowmap } from "./ws-flowmap.jsx";
import { WsStyleRef } from "./ws-styleref.jsx";
import { WsLibrary, WsTrash } from "./ws-library.jsx";
import { WsAuthor } from "./ws-author.jsx";
import { SceneTweaks, WsScene } from "./ws-scene.jsx";
import { WsManuscripts } from "./ws-manuscripts.jsx";
import { WsLongform6 } from "./lf6-app.jsx";
import { WsIndex, WsInterop } from "./ws-ops.jsx";
import { WsSettings } from "./ws-settings.jsx";
import { WsPalette } from "./ws-palette.jsx";

/* global React, ReactDOM, I, useTweaks, TweaksPanel, TweakSection, TweakSlider, TweakToggle, TweakRadio,
   WsHome, WsReview, useReviewBadge, WsSnowflake, WriterRoom, WriterTweaks, WRITER_TWEAK_DEFAULTS, SceneTweaks,
   WsFlowmap, WsLibrary, WsTrash, WsStyleRef, WsAuthor, WsScene, WsManuscripts, WsLongform6,
   WsIndex, WsInterop, WsSettings, WsPalette, WsWorks, useActiveWork, useWorks */
const { useState: useAS, useEffect: useAE, useRef: useARef } = React;
const wsPortal = ReactDOM.createPortal;

const WS_THEME = { day: "light", dusk: "sepia", night: "dark" };

const WS_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "day",
  "motion": "standard",
  "texture": true,
  "mode": "writer",
  "measure": 680,
  "fontSize": 18,
  "lineHeight": 2.05,
  "focus": "light",
  "ambient": true,
  "aiPlace": "tray",
  "wrLayout": "desk",
  "typewriter": false,
  "scnFont": 16,
  "scnDensity": "cozy",
  "scnLog": true,
  "scnBeats": true,
  "scnShort": 55,
  "scnRepeat": 30,
  "scnLong": 64
}/*EDITMODE-END*/;

/* Navigation — grouped, with advanced-only groups gated by mode.
   `daily` is always visible (the everyday writing loop); `production`
   and `ops` only appear in 高级 mode, keeping the writer surface calm. */
const WS_NAV_GROUPS = [
  {
    id: "daily", label: "日常写作",
    items: [
      { id: "home",      label: "主页", icon: "Home" },
      { id: "flowmap",   label: "流程", icon: "GitBranch" },
      { id: "snowflake", label: "构思", icon: "Snowflake" },
      { id: "writer",    label: "写作", icon: "Pen" },
      { id: "styleref",  label: "风格", icon: "Beaker" },
      { id: "review",    label: "待办", icon: "Inbox", liveBadge: true },
      { id: "library",   label: "资料", icon: "Library" },
    ],
  },
  {
    id: "production", label: "生产与质控", advanced: true,
    items: [
      { id: "author",      label: "章节编排", icon: "Layout" },
      { id: "scene",       label: "AI 起草台", icon: "Play" },
      { id: "manuscripts", label: "成稿中心", icon: "BookOpen" },
      { id: "longform",    label: "长篇控制塔", icon: "Radar" },
    ],
  },
  {
    id: "ops", label: "运维工具", advanced: true,
    items: [
      { id: "index",   label: "发布索引", icon: "UploadCloud" },
      { id: "interop", label: "导入导出", icon: "FileInput" },
    ],
  },
  {
    id: "system", label: "系统",
    items: [
      { id: "settings", label: "设置",   icon: "Settings" },
      { id: "trash",    label: "回收站", icon: "Trash" },
    ],
  },
];

// flat id → label, for routing validation + palette
const WS_VIEW_LABELS = (() => {
  const m = {};
  WS_NAV_GROUPS.forEach(g => g.items.forEach(it => { m[it.id] = it.label; }));
  return m;
})();
const WS_ALL_VIEWS = Object.keys(WS_VIEW_LABELS);
/* 旧路由别名：独立深改台已并入写作台，深链重定向到深改姿态 */
const WS_VIEW_ALIAS = { deepdesk: "writer" };

function App() {
  const [t, setTweak] = useTweaks(WS_DEFAULTS);
  const [view, setView] = useAS("home");
  const [palette, setPalette] = useAS(false);
  const mode = t.mode === "advanced" ? "advanced" : "writer";
  const work = useActiveWork();

  useAE(() => { document.documentElement.setAttribute("data-theme", WS_THEME[t.theme] || "light"); }, [t.theme]);
  useAE(() => { document.title = `创作工作台 · ${work.title}`; }, [work.title]);

  // hash routing
  useAE(() => {
    const r = () => {
      let h = (location.hash || "#home").replace("#", "");
      if (WS_VIEW_ALIAS[h]) {
        const target = WS_VIEW_ALIAS[h];
        history.replaceState(null, "", "#" + target);
        if (h === "deepdesk") setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-posture", { detail: "deep" })), 120);
        h = target;
      }
      if (WS_ALL_VIEWS.includes(h)) {
        const isAdvanced = WS_NAV_GROUPS.some(g => g.advanced && g.items.some(it => it.id === h));
        if (isAdvanced) setTweak("mode", "advanced");
        setView(h);
      }
    };
    r();
    window.addEventListener("hashchange", r);
    return () => window.removeEventListener("hashchange", r);
  }, []);

  const go = (v) => {
    if (WS_VIEW_ALIAS[v]) {
      const orig = v;
      v = WS_VIEW_ALIAS[v];
      if (orig === "deepdesk") setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-posture", { detail: "deep" })), 120);
    }
    if (!WS_ALL_VIEWS.includes(v)) return;
    // navigating to an advanced view auto-reveals 高级 mode so the rail stays consistent
    const isAdvanced = WS_NAV_GROUPS.some(g => g.advanced && g.items.some(it => it.id === v));
    if (isAdvanced && mode !== "advanced") setTweak("mode", "advanced");
    setView(v);
    history.replaceState(null, "", "#" + v);
    setPalette(false);
  };

  // ⌘K palette
  useAE(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(p => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = (cmd) => {
    switch (cmd.type) {
      case "go": go(cmd.view); break;
      case "theme": setTweak("theme", cmd.value); break;
      case "mode": setTweak("mode", cmd.value); break;
      case "tweaks": window.dispatchEvent(new CustomEvent("ws:tweaks-open")); break;
      case "scene":
        go("writer");
        setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-scene", { detail: cmd.sceneId })), 60);
        break;
      case "writer-action":
        go("writer");
        setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-action", { detail: cmd.action })), 60);
        break;
      case "step":
        go("snowflake");
        setTimeout(() => window.dispatchEvent(new CustomEvent("ws:snow-step", { detail: cmd.key })), 60);
        break;
      case "work":
        WsWorks.setActive(cmd.workId);
        go("home");
        break;
      case "new-work":
        window.dispatchEvent(new CustomEvent("ws:new-work"));
        break;
      default: break;
    }
  };

  const inWriter = view === "writer";

  const renderView = () => {
    switch (view) {
      case "home":        return <WsHome go={go} />;
      case "snowflake":   return <WsConstruct go={go} />;
      case "review":      return <WsReview go={go} />;
      case "flowmap":     return <WsFlowmap go={go} />;
      case "styleref":    return <WsStyleRef go={go} />;
      case "library":     return <WsLibrary go={go} />;
      case "author":      return <WsAuthor go={go} />;
      case "scene":       return <WsScene go={go} t={t} />;
      case "manuscripts": return <WsManuscripts go={go} />;
      case "longform":    return <WsLongform6 go={go} />;
      case "index":       return <WsIndex go={go} />;
      case "interop":     return <WsInterop go={go} />;
      case "settings":    return <WsSettings go={go} t={t} setTweak={setTweak} />;
      case "trash":       return <WsTrash go={go} />;
      case "writer":      return <div className="ws-writer-mount"><WriterRoom t={t} setTweak={setTweak} go={go} onExit={() => go("home")} /></div>;
      default:            return <WsHome go={go} />;
    }
  };

  return (
    <div className="ws-app" data-motion={t.motion} data-texture={t.texture ? "on" : "off"} data-mode={mode}>
      <Rail view={view} go={go} t={t} setTweak={setTweak} mode={mode} onPalette={() => setPalette(true)} />
      <div className="ws-rail-scrim" aria-hidden="true" />
      <main className={`ws-content ${inWriter ? "is-writer" : ""}`} key={view + "::" + work.id} data-screen-label={`ws · ${view}`}>
        {renderView()}
      </main>

      <WsPalette open={palette} onClose={() => setPalette(false)} run={run} theme={t.theme} mode={mode} />

      <TweaksPanel title="Tweaks">
        <TweakSection label="氛围与主题" />
        <TweakRadio label="主题" value={t.theme}
          options={[{ value: "day", label: "白昼" }, { value: "dusk", label: "暮色" }, { value: "night", label: "夜灯" }]}
          onChange={(v) => setTweak("theme", v)} />
        <TweakToggle label="稿纸纹理" value={t.texture} onChange={(v) => setTweak("texture", v)} />
        <TweakRadio label="动效强度" value={t.motion}
          options={[{ value: "off", label: "关" }, { value: "subtle", label: "轻" }, { value: "standard", label: "标准" }]}
          onChange={(v) => setTweak("motion", v)} />
        <TweakRadio label="界面模式" value={mode}
          options={[{ value: "writer", label: "作家" }, { value: "advanced", label: "高级" }]}
          onChange={(v) => setTweak("mode", v)} />

        <WriterTweaks t={t} setTweak={setTweak} />
        {view === "scene" && <SceneTweaks t={t} setTweak={setTweak} />}
      </TweaksPanel>
    </div>
  );
}

/* ==========================================================
   WorkSwitcher — 作品切换器 (replaces the static brand block)
   Click the brand to open a bookshelf popover: every work,
   the active one checked, mini progress, and 「＋ 新建作品」.
   Popover + modal portal to <body> so the rail's overflow /
   backdrop-filter can't clip them.
   ========================================================== */
const WS_ACCENTS = [
  { id: "crimson", label: "潮红" },
  { id: "gold", label: "暮金" },
  { id: "sage", label: "苔绿" },
  { id: "slate", label: "石青" },
];

function WorkSwitcher({ go }) {
  const works = useWorks();
  const active = useActiveWork();
  const [open, setOpen] = useAS(false);
  const [newOpen, setNewOpen] = useAS(false);

  // palette / command can request the new-work modal
  useAE(() => {
    const h = () => { setOpen(false); setNewOpen(true); };
    window.addEventListener("ws:new-work", h);
    return () => window.removeEventListener("ws:new-work", h);
  }, []);

  // Esc closes whichever layer is on top
  useAE(() => {
    if (!open && !newOpen) return;
    const onKey = (e) => { if (e.key === "Escape") { if (newOpen) setNewOpen(false); else setOpen(false); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, newOpen]);

  const pickWork = (id) => { WsWorks.setActive(id); setOpen(false); go("home"); };
  const startNew = () => { setOpen(false); setNewOpen(true); };
  const createWork = (data) => { WsWorks.create(data); setNewOpen(false); go("home"); };

  return (
    <React.Fragment>
      <button className={`ws-brand ${open ? "is-open" : ""}`} onClick={() => setOpen(o => !o)}
        aria-haspopup="true" aria-expanded={open} title="切换 / 新建作品">
        <span className="ws-brand-mark" data-accent={active.accent}>{active.mark}</span>
        <span className="ws-brand-text">
          <span className="ws-brand-title">{active.title}</span>
          <span className="ws-brand-sub">{active.genre}</span>
        </span>
        <span className="ws-brand-caret"><I.ChevronDown size={15} /></span>
      </button>

      {open && wsPortal(
        <WorkPopover works={works} activeId={active.id} onPick={pickWork} onNew={startNew} onClose={() => setOpen(false)} />,
        document.body
      )}
      {newOpen && wsPortal(
        <NewWorkModal onCreate={createWork} onClose={() => setNewOpen(false)} />,
        document.body
      )}
    </React.Fragment>
  );
}

function WorkPopover({ works, activeId, onPick, onNew, onClose }) {
  const removeWork = (e, w) => {
    e.stopPropagation();
    if (!window.confirm(`删除《${w.title}》？\n这部作品会连同章节、构思、正文、待办一起进入回收站，可在「回收站」里整体恢复。`)) return;
    WsWorks.remove(w.id);
  };
  return (
    <div className="ws-wsw-scrim" onClick={onClose}>
      <div className="ws-wsw" role="menu" onClick={(e) => e.stopPropagation()}>
        <div className="ws-wsw-head">
          <span className="ws-wsw-head-lbl">作品</span>
          <span className="ws-wsw-head-n">{works.length} 部</span>
        </div>
        <div className="ws-wsw-list">
          {works.map(w => {
            const pct = w.wordsTarget ? Math.min(100, Math.round((w.wordsTotal / w.wordsTarget) * 100)) : 0;
            const isActive = w.id === activeId;
            const deletable = !WsWorks.isSeed(w.id) && works.length > 1;
            return (
              <button key={w.id} className={`ws-wsw-row ${isActive ? "is-active" : ""}`} role="menuitemradio"
                aria-checked={isActive} onClick={() => onPick(w.id)}>
                <span className="ws-wsw-mark" data-accent={w.accent}>{w.mark}</span>
                <span className="ws-wsw-meta">
                  <span className="ws-wsw-title">{w.title}</span>
                  <span className="ws-wsw-sub">{w.genre} · {w.chaptersWritten > 0 ? `${(w.wordsTotal / 10000).toFixed(1)} 万字 · ${pct}%` : "尚未开始"}</span>
                  <span className="ws-wsw-bar"><i data-accent={w.accent} style={{ width: pct + "%" }} /></span>
                </span>
                {deletable && (
                  <span className="ws-wsw-del" role="button" title="删除这部作品"
                    style={{ display: "inline-flex", padding: 6, borderRadius: 8, color: "var(--ink-3)", opacity: 0.7 }}
                    onClick={(e) => removeWork(e, w)}>
                    <I.Trash size={14} />
                  </span>
                )}
                {isActive && <span className="ws-wsw-check"><I.Check size={15} /></span>}
              </button>
            );
          })}
        </div>
        <button className="ws-wsw-new" onClick={onNew}>
          <span className="ws-wsw-new-ic"><I.Plus size={16} /></span> 新建作品
        </button>
      </div>
    </div>
  );
}

function NewWorkModal({ onCreate, onClose }) {
  const [title, setTitle] = useAS("");
  const [genre, setGenre] = useAS("");
  const [sub, setSub] = useAS("");
  const [target, setTarget] = useAS(100000);
  const [accent, setAccent] = useAS("slate");
  const ref = useARef(null);
  useAE(() => { if (ref.current) ref.current.focus(); }, []);
  const canCreate = title.trim().length > 0;
  const submit = () => { if (canCreate) onCreate({ title, genre, sub, wordsTarget: target, accent }); };

  return (
    <div className="ws-nw-scrim" onClick={onClose}>
      <div className="ws-nw" role="dialog" aria-modal="true" aria-label="新建作品" onClick={(e) => e.stopPropagation()}>
        <div className="ws-nw-head">
          <span className="ws-nw-mark" data-accent={accent}>{Array.from(title.trim())[0] || "新"}</span>
          <div>
            <div className="ws-nw-eyebrow">新建作品</div>
            <h2 className="ws-nw-title">开一部新书</h2>
          </div>
          <button className="ws-nw-x" onClick={onClose} title="取消"><I.X size={18} /></button>
        </div>

        <div className="ws-nw-body">
          <label className="ws-nw-field">
            <span className="ws-nw-lbl">书名 <em>必填</em></span>
            <input ref={ref} className="ws-nw-input" value={title} placeholder="例如：盐镇来信"
              onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
          </label>
          <label className="ws-nw-field">
            <span className="ws-nw-lbl">题材</span>
            <input className="ws-nw-input" value={genre} placeholder="例如：悬疑 · 长篇"
              onChange={(e) => setGenre(e.target.value)} />
          </label>
          <label className="ws-nw-field">
            <span className="ws-nw-lbl">一句话简介</span>
            <textarea className="ws-nw-input ws-nw-area" value={sub} placeholder="用一句话说清这部作品是关于什么的——也可以之后在雪花里再写。"
              rows={2} onChange={(e) => setSub(e.target.value)} />
          </label>
          <div className="ws-nw-row2">
            <label className="ws-nw-field">
              <span className="ws-nw-lbl">目标字数</span>
              <div className="ws-nw-target">
                <input className="ws-nw-input" type="number" min="10000" step="10000" value={target}
                  onChange={(e) => setTarget(e.target.value)} />
                <span className="ws-nw-target-suffix">字</span>
              </div>
            </label>
            <div className="ws-nw-field">
              <span className="ws-nw-lbl">主色</span>
              <div className="ws-nw-accents">
                {WS_ACCENTS.map(a => (
                  <button key={a.id} type="button" title={a.label}
                    className={`ws-nw-acc ${accent === a.id ? "is-sel" : ""}`} data-accent={a.id}
                    onClick={() => setAccent(a.id)} />
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="ws-nw-foot">
          <button className="btn btn-ghost" onClick={onClose}>取消</button>
          <button className="btn btn-accent" disabled={!canCreate} onClick={submit}>
            <I.Plus size={15} /> 创建并进入
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---- Rail ---- */
function Rail({ view, go, t, setTweak, mode, onPalette }) {
  const groups = WS_NAV_GROUPS.filter(g => !g.advanced || mode === "advanced");
  const reviewBadge = useReviewBadge();  // 订阅式：处理完即消失，按作品隔离
  return (
    <aside className="ws-rail">
      <WorkSwitcher go={go} />

      <button className="ws-cmdk" onClick={onPalette} title="命令面板 ⌘K">
        <span className="ws-item-ic"><I.Search size={18} /></span>
        <span className="ws-cmdk-label">快速跳转…</span>
        <kbd>⌘K</kbd>
      </button>

      <nav className="ws-nav ws-nav-scroll">
        {groups.map(g => (
          <div key={g.id} className="ws-nav-group">
            <div className="ws-nav-label">{g.label}</div>
            {g.items.map(n => {
              const Ic = I[n.icon] || I.Dot;
              const badge = n.liveBadge ? reviewBadge : n.badge;
              return (
                <button key={n.id} className={`ws-item ${view === n.id ? "is-active" : ""}`} onClick={() => go(n.id)} title={n.label}>
                  <span className="ws-item-ic"><Ic size={19} /></span>
                  <span className="ws-item-label">{n.label}</span>
                  {badge && <span className="ws-item-badge">{badge}</span>}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="ws-rail-foot">
        <div className="ws-mode-switch" role="tablist" aria-label="界面模式">
          <button className={`ws-mode-btn ${mode === "writer" ? "is-active" : ""}`} onClick={() => setTweak("mode", "writer")} title="作家模式 · 只显示日常写作">
            <I.Pen size={15} /><span>作家</span>
          </button>
          <button className={`ws-mode-btn ${mode === "advanced" ? "is-active" : ""}`} onClick={() => setTweak("mode", "advanced")} title="高级模式 · 显示生产与运维工具">
            <I.Layout size={15} /><span>高级</span>
          </button>
        </div>
        <button className="ws-foot-btn" onClick={() => setTweak("theme", t.theme === "night" ? "day" : "night")} title="切换昼夜">
          <span className="ws-item-ic">{t.theme === "night" ? <I.Sun size={18} /> : <I.Moon size={18} />}</span>
          <span>{t.theme === "night" ? "白昼" : "夜灯"}</span>
        </button>
        <button className="ws-foot-btn" onClick={() => window.dispatchEvent(new CustomEvent("ws:tweaks-open"))} title="舒适度设置">
          <span className="ws-item-ic"><I.Sliders size={18} /></span>
          <span>调节舒适度</span>
        </button>
      </div>
    </aside>
  );
}

/* WsReview (待办收件箱) lives in ws-review.jsx, loaded before this file. */

/* createRoot 挂载已移至 main.jsx（Phase 1 工程化） */
/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { App };
