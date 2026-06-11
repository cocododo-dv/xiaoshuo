/* global React, I, CT_LAYERS, CT_TRACK, CT_STATE, CT_SPINE, CT_CONTINUITY, CT_MATERIALIZE, CT_RUBRIC_DIMS, ctLayer, ctLayerName, ctBlastRadius, ctHealthColor */
/* ==========================================================
   构思控制塔 — 面板：脊柱 / 连续性 / 质量矩阵 / 下游 / 检视
   ========================================================== */
const { useState: usePS } = React;

/* ====== 故事脊柱（单一真相源）====== */
function CTSpinePanel({ spine = CT_SPINE, onJump }) {
  const bindTone = { ok: "sage", weak: "gold", missing: "rose" };
  const bindLabel = { ok: "已落位", weak: "占位待强化", missing: "未落场" };
  const unresolved = spine.disasters.reduce((a, d) => a + d.bindings.filter(b => b.status !== "ok").length, 0);
  return (
    <section className="ct-panel ct-spine-panel">
      <header className="ct-panel-h">
        <span className="ct-panel-h-ic"><I.Activity size={14} /></span>
        <div>
          <h3 className="ct-panel-title">故事脊柱 · 单一真相源</h3>
          <p className="ct-panel-sub">三灾难 + 道德前提锚定在 03；下游情节层只能引用，不能各自改写。</p>
        </div>
      </header>

      <div className="ct-premise">
        <span className="ct-premise-false">{spine.premiseF}</span>
        <I.ArrowRight size={13} />
        <span className="ct-premise-true">{spine.premiseT}</span>
        <span className="ct-premise-flip">{spine.flipAt} 翻转</span>
      </div>

      <div className="ct-disasters">
        {spine.disasters.map((d, i) => (
          <div key={i} className={`ct-disaster tone-${d.tone}`}>
            <div className="ct-disaster-head">
              <span className="ct-disaster-id">{d.id}</span>
              <span className="ct-disaster-act">{d.act}</span>
              {d.flip && <span className="ct-disaster-flip">道德前提翻转</span>}
            </div>
            <div className="ct-disaster-title">{d.title}</div>
            <div className="ct-disaster-effect">{d.effect}</div>
            <div className="ct-binds">
              <span className="ct-binds-label">向下游绑定</span>
              {d.bindings.map((b, j) => (
                <button key={j} className={`ct-bind ct-bind-${bindTone[b.status]}`} onClick={() => onJump && onJump(b.layer)}>
                  <span className="ct-bind-layer">{ctLayerName(b.layer)}</span>
                  <span className="ct-bind-at">{b.at}</span>
                  <span className="ct-bind-status">{bindLabel[b.status]}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="ct-spine-foot">
        <I.AlertTriangle size={13} />
        {unresolved > 0
          ? <span>灾二、灾三仍有 <b>{unresolved} 处未落场 / 占位</b>——下游 07 大纲与 09 场景列表需把它们具体化，脊柱才算贯通。</span>
          : <span>三灾难已全部落位，脊柱贯通。下游情节层与之绑定一致。</span>}
      </div>
    </section>
  );
}

/* ====== 检视：选中层 / 模拟修改影响 ====== */
function CTInspector({ layer, armed, onArm, onSelect, onCascade, editable, onEdit, onOpenStep }) {
  if (armed) return <CTBlastInspector armed={armed} onArm={onArm} onSelect={onSelect} onCascade={onCascade} />;
  if (!layer) return <CTInspectorEmpty />;
  const l = layer;
  const trk = CT_TRACK[l.track] || CT_TRACK.plot;
  const st = CT_STATE[l.state] || CT_STATE.empty;
  return (
    <section className="ct-panel ct-inspector">
      <header className="ct-insp-head">
        <span className="ct-insp-num" style={{ background: trk.wash, color: trk.color }}>{l.num}</span>
        <div className="ct-insp-titles">
          <h3 className="ct-panel-title">{l.name}</h3>
          <div className="ct-insp-tags">
            <span className="ct-tag" style={{ background: trk.wash, color: trk.color }}>{trk.label}链</span>
            <span className={`pill pill-${st.tone} text-xs`}><span className="pill-dot" />{st.label}</span>
            {l.gate && <span className="pill pill-crimson text-xs"><span className="pill-dot" />整理门槛</span>}
            {l.bindSpine && <span className="pill pill-gold text-xs"><span className="pill-dot" />绑定脊柱</span>}
          </div>
        </div>
      </header>

      <p className="ct-insp-artifact">{l.artifact}</p>
      {l.state === "stale" && (
        <div className="ct-insp-stale"><I.AlertTriangle size={13} /><span>{l.staleReason}</span></div>
      )}

      <div className="ct-insp-health">
        <div className="ct-insp-health-top">
          <span className="ct-insp-eyebrow">结构强度</span>
          <span className="ct-insp-score" style={{ color: ctHealthColor(l.health.score) }}>{l.health.score}<small>/100</small></span>
        </div>
        <div className="ct-dims">
          {CT_RUBRIC_DIMS.map(d => (
            <div key={d.key} className="ct-dim" title={d.q}>
              <span className="ct-dim-label">{d.short}</span>
              <span className="ct-dim-bar"><span style={{ width: `${l.health.dims[d.key]}%`, background: ctHealthColor(l.health.dims[d.key]) }} /></span>
              <span className="ct-dim-num">{l.health.dims[d.key]}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="ct-insp-deps">
        <div className="ct-insp-dep-col">
          <span className="ct-insp-eyebrow">上游（派生自）</span>
          {l.deps.length ? l.deps.map(k => (
            <button key={k} className="ct-dep-chip" onClick={() => onSelect(k)}><I.ArrowRight size={11} style={{ transform: "rotate(180deg)" }} />{ctLayerName(k)}</button>
          )) : <span className="ct-dep-none">根层 · 无上游</span>}
        </div>
        <div className="ct-insp-dep-col">
          <span className="ct-insp-eyebrow">下游（影响）</span>
          {l.feeds.length ? l.feeds.map(k => (
            <button key={k} className="ct-dep-chip" onClick={() => k !== "materialize" && onSelect(k)}>{k === "materialize" ? "整理成章节" : ctLayerName(k)}<I.ArrowRight size={11} /></button>
          )) : <span className="ct-dep-none">收尾层 · 无下游</span>}
        </div>
      </div>

      <div className="ct-insp-actions">
        <button className="btn btn-primary ct-insp-arm" onClick={() => onOpenStep && onOpenStep(l.key)}>
          <I.Layers size={14} /> 在逐步工作台打开本层
        </button>
        <div className="ct-insp-actions-row">
          {editable && (
            <button className="btn btn-accent btn-sm" onClick={() => onEdit(l.key)}>
              <I.Edit size={13} /> 总览内速改
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => onArm(l.key)}>
            <I.Zap size={13} /> 影响半径
          </button>
        </div>
      </div>
    </section>
  );
}

function CTInspectorEmpty() {
  return (
    <section className="ct-panel ct-inspector ct-insp-empty">
      <I.Layers size={22} />
      <p>点选左侧任一层查看<strong>结构强度、上下游依赖</strong>；点节点上的 <I.Zap size={12} /> 模拟一次修改，看它在系统里激起的涟漪。</p>
    </section>
  );
}

/* ====== 模拟修改 → 影响半径 + 级联重生成 ====== */
function CTBlastInspector({ armed, onArm, onSelect, onCascade }) {
  const l = ctLayer(armed);
  const blast = [...ctBlastRadius(armed)];
  const layerHits = blast.filter(k => k !== "materialize");
  const hitsMat = blast.includes("materialize");
  return (
    <section className="ct-panel ct-inspector ct-blast">
      <header className="ct-blast-head">
        <span className="ct-blast-ic"><I.Zap size={15} /></span>
        <div>
          <h3 className="ct-panel-title">影响半径 · 修改 {l.num} {l.name}</h3>
          <p className="ct-panel-sub">分形结构里，改一层会顺着派生链往下传导。</p>
        </div>
        <button className="ct-blast-x" onClick={() => onArm(null)} title="退出模拟"><span className="ct-x-glyph">×</span></button>
      </header>

      <div className="ct-blast-stat">
        <div className="ct-blast-stat-num">{layerHits.length}</div>
        <div className="ct-blast-stat-label">个下游层将被标记「需复核」{hitsMat && <span className="ct-blast-mat">· 并波及下游交付</span>}</div>
      </div>

      <ol className="ct-blast-chain">
        {layerHits.map((k, i) => {
          const t = ctLayer(k); const trk = CT_TRACK[t.track];
          return (
            <li key={k} className="ct-blast-item" onClick={() => onSelect(k)}>
              <span className="ct-blast-order">{i + 1}</span>
              <span className="ct-blast-rail" style={{ background: trk.color }} />
              <span className="ct-blast-name">{t.num} {t.name}</span>
              {t.bindSpine && <span className="ct-blast-spine">含脊柱引用</span>}
              <span className="ct-blast-arrow"><I.AlertTriangle size={12} /></span>
            </li>
          );
        })}
        {hitsMat && (
          <li className="ct-blast-item is-mat">
            <span className="ct-blast-order">→</span>
            <span className="ct-blast-rail" style={{ background: "var(--ink-2)" }} />
            <span className="ct-blast-name">整理成章节结构 · 需重新整理</span>
          </li>
        )}
      </ol>

      <div className="ct-cascade-box">
        <div className="ct-cascade-copy">
          <strong>级联重生成</strong>
          <span>按依赖顺序逐层重生成下游候选，你再逐个确认——不会自动覆盖已确认内容。</span>
        </div>
        <button className="btn btn-accent btn-sm" onClick={() => onCascade(armed)}><I.Refresh size={13} /> 一键级联</button>
      </div>
    </section>
  );
}

/* ====== 质量矩阵：10 层 × 5 维 ====== */
function CTQualityMatrix({ layers = CT_LAYERS, onSelect }) {
  const dims = CT_RUBRIC_DIMS;
  const avg = (key) => Math.round(layers.reduce((a, l) => a + l.health.dims[key], 0) / layers.length);
  const sceneFlags = ((layers.find(l => l.key === "scenes") || {}).structFlags) || [];
  return (
    <div className="ct-quality">
      <div className="ct-quality-head">
        <h3 className="ct-panel-title">质量矩阵 · 10 层 × 5 维统一标尺</h3>
        <p className="ct-panel-sub">同一套评分维度横向铺开，结构弱点一眼可见。点格看诊断，点行进入该层。</p>
      </div>
      <div className="ct-matrix" style={{ gridTemplateColumns: `150px repeat(${dims.length}, 1fr) 64px` }}>
        <div className="ct-mx-corner" />
        {dims.map(d => <div key={d.key} className="ct-mx-colh" title={d.q}>{d.short}</div>)}
        <div className="ct-mx-colh ct-mx-colh-tot">总分</div>

        {layers.map(l => (
          <React.Fragment key={l.key}>
            <button className="ct-mx-rowh" onClick={() => onSelect(l.key)}>
              <span className="ct-mx-rowh-num">{l.num}</span>{l.name}
            </button>
            {dims.map(d => {
              const v = l.health.dims[d.key];
              return <div key={d.key} className="ct-mx-cell" style={{ background: ctCellBg(v) }} title={`${l.name} · ${d.short}：${v}`}><span>{v}</span></div>;
            })}
            <div className="ct-mx-tot" style={{ color: ctHealthColor(l.health.score) }}>{l.health.score}</div>
          </React.Fragment>
        ))}

        <div className="ct-mx-rowh ct-mx-rowh-avg">列均值</div>
        {dims.map(d => <div key={d.key} className="ct-mx-avg">{avg(d.key)}</div>)}
        <div className="ct-mx-avg ct-mx-avg-tot">{Math.round(layers.reduce((a, l) => a + l.health.score, 0) / layers.length)}</div>
      </div>
      <div className="ct-quality-foot">
        {sceneFlags.map((f, i) => (
          <span key={`sc${i}`} className={`ct-q-flag ${f.tone}`} onClick={() => onSelect("scenes")} style={{ cursor: "pointer" }}>
            <I.AlertTriangle size={12} /> 09 场景列表 · {f.t} —— {f.q}
          </span>
        ))}
        <span className="ct-q-flag rose"><I.AlertTriangle size={12} /> 07 长篇大纲「因果锁链」仅 54——二、三幕占位，灾难未压实</span>
        <span className="ct-q-flag rose"><I.AlertTriangle size={12} /> 08 角色全档案整体 58——草稿未补全，向 09 输出可写性偏低</span>
      </div>
    </div>
  );
}
function ctCellBg(v) {
  if (v >= 85) return "color-mix(in srgb, var(--sage) 26%, var(--paper-1))";
  if (v >= 75) return "color-mix(in srgb, var(--sage) 14%, var(--paper-1))";
  if (v >= 65) return "color-mix(in srgb, var(--gold) 18%, var(--paper-1))";
  if (v >= 55) return "color-mix(in srgb, var(--gold) 30%, var(--paper-1))";
  return "color-mix(in srgb, var(--rose) 26%, var(--paper-1))";
}

/* ====== 连续性引擎 ====== */
function CTContinuity({ items = CT_CONTINUITY, onSelect }) {
  const sevTone = { high: "rose", med: "gold", low: "slate" };
  const statusLabel = { conflict: "冲突", ok: "一致", unverifiable: "待补全" };
  const statusTone = { conflict: "rose", ok: "sage", unverifiable: "slate" };
  return (
    <div className="ct-continuity">
      <div className="ct-quality-head">
        <h3 className="ct-panel-title">连续性引擎 · 跨层事实校验</h3>
        <p className="ct-panel-sub">数字 / 年龄 / ID / 时间线在各层之间自动比对，冲突即时浮出，不靠人眼。</p>
      </div>
      <div className="ct-cont-list">
        {items.map(c => (
          <div key={c.id} className={`ct-cont-row is-${c.status}`}>
            <span className={`ct-cont-ic tone-${sevTone[c.severity]}`}>{React.createElement(I[c.icon] || I.Info, { size: 15 })}</span>
            <div className="ct-cont-body">
              <div className="ct-cont-top">
                <span className="ct-cont-kind">{c.kind}</span>
                <span className="ct-cont-fact">{c.fact}</span>
                <span className={`pill pill-${statusTone[c.status]} text-xs`}><span className="pill-dot" />{statusLabel[c.status]}</span>
              </div>
              <div className="ct-cont-values">
                {c.values.map((v, i) => (
                  <button key={i} className={`ct-cont-val ${c.status === "conflict" ? "is-bad" : ""}`} onClick={() => onSelect(v.layer)}>
                    <span className="ct-cont-val-layer">{v.label}</span>
                    <span className="ct-cont-val-num">{v.val}</span>
                  </button>
                ))}
              </div>
              <p className="ct-cont-note">{c.note}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ====== 下游交付：整理成章节结构（读 07/09/10 的真实数据 → 写入章节目录） ====== */
function CTDownstream({ layerMap, onSelect, onWriteScene, onOpenStep }) {
  const [, force] = React.useState(0);
  const [written, setWritten] = React.useState(null);
  React.useEffect(() => {
    const refresh = () => force(n => n + 1);
    const un = window.WsCatalog ? window.WsCatalog.subscribe(refresh) : null;
    window.addEventListener("ws:snow-saved", refresh);
    return () => { if (un) un(); window.removeEventListener("ws:snow-saved", refresh); };
  }, []);

  const state = window.s2ExportState ? window.s2ExportState() : null;
  const scaffolds = (state && state.scaffolds) || {};
  const preview = window.s2Materialize ? window.s2Materialize.preview(scaffolds) : { ok: false, reason: "构思数据不可用", chapters: [], total: 0 };
  const getState = (k) => (layerMap && layerMap[k] ? layerMap[k] : ctLayer(k)).state;
  const gateOk = CT_MATERIALIZE.gateLayers.every(k => getState(k) === "approved");
  const sidOf = (chTitle, scTitle) => (window.s2Materialize ? window.s2Materialize.sid(chTitle, scTitle) : null);
  const catCount = (() => { try { return window.WsCatalog.get().length; } catch (e) { return 0; } })();

  const writeIn = () => {
    if (!preview.ok) return;
    const msg = `把 ${preview.chapters.length} 章 / ${preview.total} 场写入章节目录？\n已有同名章 / 同名场会保留原样并跳过——不会覆盖你在编排台的修改。${catCount ? `\n（目录现有 ${catCount} 章）` : ""}`;
    if (!window.confirm(msg)) return;
    const r = window.s2Materialize.apply(preview);
    setWritten(r);
  };

  if (!preview.ok) {
    return (
      <div className="ct-downstream">
        <div className="ct-quality-head">
          <h3 className="ct-panel-title">下游交付 · 整理成章节结构</h3>
          <p className="ct-panel-sub">07 章节骨架 + 09 场景列表 + 10 场景规划 → 章节目录（写作 / 编排同源）。</p>
        </div>
        <div className="ct-mat-blank">
          <I.Layout size={24} />
          <div className="fw-600">{preview.reason}</div>
          <p className="text-muted text-sm">物化需要三样东西：07 的章、09 的场、10 的逐场 GCS / RDD 规划。</p>
          <div className="ct-mat-blank-acts">
            <button className="btn btn-primary btn-sm" onClick={() => onOpenStep && onOpenStep("outline")}>去 07 · 长篇大纲</button>
            <button className="btn btn-ghost btn-sm" onClick={() => onOpenStep && onOpenStep("scenes")}>去 09 · 场景列表</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ct-downstream">
      <div className="ct-quality-head">
        <h3 className="ct-panel-title">下游交付 · 整理成章节结构</h3>
        <p className="ct-panel-sub">实时读取 09 场景列表 + 10 场景规划，按脊柱锚点（灾一 / 二 / 三）把场分进 07 的章。主动场带 GCS，反应场带 RDD。</p>
      </div>

      <div className="ct-gate">
        <div className="ct-gate-head">
          <span className="ct-insp-eyebrow">门槛检查</span>
          <span className={`pill ${gateOk ? "pill-sage" : "pill-gold"} text-xs`}><span className="pill-dot" />{gateOk ? "门槛已满足" : "尚有未确认门槛 · 仍可先预览"}</span>
        </div>
        <div className="ct-gate-row">
          {CT_MATERIALIZE.gateLayers.map(k => {
            const l = ctLayer(k); const ok = getState(k) === "approved";
            return (
              <button key={k} className={`ct-gate-chip ${ok ? "is-ok" : "is-wait"}`} onClick={() => onSelect(k)}>
                {ok ? <I.Check size={12} /> : <I.Circle size={12} />}{l.num} {l.name}
              </button>
            );
          })}
        </div>
      </div>

      <div className="ct-chapters">
        {preview.chapters.map((ch, ci) => (
          <div key={ci} className="ct-chapter">
            <div className="ct-chapter-head">
              <span className="ct-chapter-id">CH{String(ci + 1).padStart(2, "0")}</span>
              <span className="ct-chapter-title">{ch.title}</span>
              {ch.spine && <span className="ct-scene-spine"><I.Activity size={10} />{ch.spine}</span>}
              <span className="ct-chapter-count">{ch.scenes.length} 场</span>
            </div>
            {ch.scenes.length === 0 && <div className="ct-mat-nosc">本章还没有分到场——在 09 给它对应的位置加场，或用脊柱标记锚定。</div>}
            <div className="ct-scenes">
              {ch.scenes.map(s => {
                const form = s.kind === "主动" ? "proactive" : "reactive";
                const hit = sidOf(ch.title, s.title);
                return (
                  <div key={s.srcId + s.title} className={`ct-scene form-${form}`}>
                    <div className="ct-scene-main">
                      <div className="ct-scene-top">
                        <span className="ct-scene-id">{s.srcId}</span>
                        <span className={`ct-scene-form form-${form}`}>{form === "proactive" ? "主动 · GCS" : "反应 · RDD"}</span>
                        <span className="ct-scene-pov">{s.pov || "POV 未定"}</span>
                        {s.spine && <span className="ct-scene-spine"><I.Activity size={10} />{s.spine}</span>}
                        {!s.planned && <span className="ct-scene-unplanned" title="10 场景规划里还没有这一场的 GCS/RDD"><I.AlertTriangle size={10} /> 10 未规划</span>}
                      </div>
                      <div className="ct-scene-title">{s.title}</div>
                      <div className="ct-scene-brief">{form === "proactive" ? "目标" : "反应"} {s.goal}{s.obstacle ? ` / ${form === "proactive" ? "冲突" : "两难"} ${s.obstacle}` : ""}{s.turn ? ` / ${form === "proactive" ? "挫败" : "决定"} ${s.turn}` : ""}</div>
                    </div>
                    {hit ? (
                      <button className="ct-scene-write" onClick={() => onWriteScene && onWriteScene({ id: hit.sid, chapter: `${hit.chId} ${hit.chTitle}`, form, spine: s.spine, brief: s.goal })} title="进入写作房间写这一场的正文">
                        <I.Pen size={13} /><span>写正文</span>
                      </button>
                    ) : (
                      <button className="ct-scene-write is-wait" onClick={writeIn} title="这一场还不在章节目录里——先整理写入，再来写正文">
                        <I.Layout size={13} /><span>待写入</span>
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="ct-materialize-bar">
        <div className="ct-mat-copy">
          <strong>{preview.chapters.length} 章 · {preview.total} 场{preview.planned < preview.total ? ` · ${preview.total - preview.planned} 场未规划` : " · 10 已全覆盖"}</strong>
          <span>{written
            ? `已写入：新增 ${written.newCh} 章 / ${written.newSc} 场${written.skipSc ? ` · 跳过同名 ${written.skipSc} 场` : ""} · 点任一场「写正文」即可进写作房间。`
            : "写入章节目录后，编排台 / 写作器 / 成稿中心读到的就是这份结构——构思→成稿不断线。"}</span>
        </div>
        <button className="btn btn-accent" onClick={writeIn} disabled={!preview.ok}><I.Layout size={14} /> {written ? "再次整理（增量）" : "整理成章节结构"}</button>
      </div>
      <style>{`
.ct-mat-blank { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 32px 24px; border: 1px dashed var(--line-1, #ddd); border-radius: 14px; color: var(--ink-2); }
.ct-mat-blank-acts { display: flex; gap: 8px; margin-top: 6px; }
.ct-mat-nosc { padding: 10px 14px; border: 1px dashed var(--line-1, #ddd); border-radius: 10px; font-size: 12px; color: var(--ink-3, #999); margin-bottom: 8px; }
.ct-scene-unplanned { display: inline-flex; align-items: center; gap: 3px; font-size: 10.5px; font-weight: 700; color: var(--gold); }
.ct-scene-write.is-wait { opacity: 0.75; }
      `}</style>
    </div>
  );
}

Object.assign(window, { CTSpinePanel, CTInspector, CTQualityMatrix, CTContinuity, CTDownstream });
