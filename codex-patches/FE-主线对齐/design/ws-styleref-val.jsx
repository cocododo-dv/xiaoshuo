/* global React, I */
const { useState: useStSRV } = React;

/* ==========================================================
   风格参考 · 回测校验 stage + ValidationReportCard
   Three-way concurrent validation:
     quantitative (自适应阈值) / semantic (radar) / plagiarism (n-gram)
     + forbidden_pattern hits
   Lives in same bundle scope → can read SR_METRICS etc.
   ========================================================== */

const SRV_SAMPLE_TEXT =
  "他没有应声，弯下腰，把那枚铜板从砖缝里抠出来，又用袖子擦了擦。天色已经暗下去，巷口的风把一张旧报纸卷起来，贴在墙根，又慢慢滑落。他站直了，望了望那扇关着的门，终于没有敲，转身走进了愈来愈浓的暮色里。";

/* ---- quantitative report (自适应 tolerance) ---- */
const SRV_QUANT = [
  { name: "平均句长",      target: 16.8, std: 11.2, actual: 18.2, unit: "字" },
  { name: "句长标准差",    target: 11.2, std: 3.1,  actual: 10.4, unit: "" },
  { name: "短句率",        target: 0.41, std: 0.09, actual: 0.38, unit: "", pct: true },
  { name: "对话占比",      target: 0.23, std: 0.07, actual: 0.05, unit: "", pct: true },
  { name: "比喻密度/千",   target: 3.2,  std: 1.8,  actual: 2.1, unit: "" },
  { name: "文言词比率",    target: 0.14, std: 0.05, actual: 0.16, unit: "", pct: true },
  { name: "视觉感官/千",   target: 8.1,  std: 2.6,  actual: 9.4, unit: "" },
  { name: "破折号/千",     target: 2.4,  std: 1.1,  actual: 1.8, unit: "" },
];

const SRV_FLOORS = {
  "平均句长": 3.0, "句长标准差": 2.0, "短句率": 0.05, "对话占比": 0.05,
  "比喻密度/千": 1.0, "文言词比率": 0.03, "视觉感官/千": 1.5, "破折号/千": 0.8,
};

/* ---- semantic radar (6 axes) ---- */
const SRV_RADAR = [
  { axis: "语言贴合", v: 0.86 },
  { axis: "叙事贴合", v: 0.78 },
  { axis: "场景贴合", v: 0.71 },
  { axis: "情感基调", v: 0.82 },
  { axis: "连贯性",   v: 0.90 },
  { axis: "原创度",   v: 0.94 },
];

const SRV_FORBIDDEN = [
  { statement: "排比堆叠的华丽长句抒情", triggered: false },
  { statement: "「眼睛像星星」式陈词滥调比喻", triggered: false },
  { statement: "对话后追加大段情绪解释", triggered: false },
  { statement: "成语连缀替代描写", triggered: true, excerpt: "愈来愈浓的暮色里", note: "轻度：「愈来愈浓」接近成语化抒情，建议改具象。" },
];

const SRV_PLAG = {
  passed: true,
  maxRun: 6,
  threshold: 12,
  ngram: 8,
  flags: [
    { run: 6, text: "把那枚铜板从砖缝里", source: "近似：呐喊 P-145「摸出四文大钱」", level: "ok" },
  ],
};

window.SrValidation = function SrValidation({ book, go }) {
  const [mode, setMode] = useStSRV("async_full");
  const [done, setDone] = useStSRV(true);
  const [running, setRunning] = useStSRV(false);

  const verdict = computeVerdict();

  const run = () => {
    setRunning(true);
    setDone(false);
    setTimeout(() => { setRunning(false); setDone(true); }, 1400);
  };

  return (
    <div className="srv">
      <div className="srv-main">
        {/* Input */}
        <div className="card">
          <div className="card-head">
            <div><div className="card-title">回测输入</div><div className="card-sub">粘贴或选择一段生成文本，对 {book.author}画像三路并发校验</div></div>
            <div className="seg">
              <button className={`seg-btn ${mode==="sync_only"?"is-active":""}`} onClick={()=>setMode("sync_only")}>同步快路径</button>
              <button className={`seg-btn ${mode==="async_full"?"is-active":""}`} onClick={()=>setMode("async_full")}>全量三路</button>
            </div>
          </div>
          <textarea className="srv-input textarea" defaultValue={SRV_SAMPLE_TEXT} />
          <div className="srv-input-foot">
            <div className="srv-mode-hint">
              {mode === "sync_only"
                ? <span><I.Zap size={12} /> 仅量化 + 抄袭，毫秒级返回（qc 落盘 gate 用），语义后台异步补算</span>
                : <span><I.Beaker size={12} /> 量化 + 语义 + 抄袭 + 禁忌 四路并发，语义走 LLM</span>}
            </div>
            <button className="btn btn-accent" onClick={run} disabled={running}>
              {running ? <><span className="step-spin-dark" style={{width:13,height:13}} /> 回测中…</> : <><I.Play size={13} /> 运行回测</>}
            </button>
          </div>
        </div>

        {/* Report */}
        {running && (
          <div className="card srv-running">
            <div className="srv-run-rows">
              <div className="srv-run-row"><span className="step-spin-dark" /><span>量化对齐 · 本地计算</span></div>
              <div className="srv-run-row"><span className="step-spin-dark" /><span>语义评分 · critic LLM</span></div>
              <div className="srv-run-row"><span className="step-spin-dark" /><span>抄袭检测 · Rabin-Karp</span></div>
              <div className="srv-run-row"><span className="step-spin-dark" /><span>禁忌检查 · 逐条判定</span></div>
            </div>
          </div>
        )}
        {done && !running && <window.ValidationReportCard verdict={verdict} mode={mode} />}
      </div>

      {/* Side: verdict + auto-rewrite */}
      <aside className="srv-side">
        <div className={`srv-verdict v-${verdict.kind}`}>
          <div className="srv-verdict-icon">
            {verdict.kind === "pass" && <I.CheckCircle size={26} />}
            {verdict.kind === "partial" && <I.AlertTriangle size={26} />}
            {verdict.kind === "fail" && <I.X size={26} />}
            {verdict.kind === "plagiarism" && <I.Ban size={26} />}
          </div>
          <div className="srv-verdict-label">{verdict.label}</div>
          <div className="srv-verdict-sub">{verdict.sub}</div>
        </div>

        <div className="card-flat">
          <div className="ctx-head" style={{marginBottom:10}}><I.Target size={13} /><span>四路汇总</span></div>
          <ul className="srv-summary">
            <li><span>量化对齐</span><b className="srv-sum-val ok">{Math.round(quantPassRate()*100)}%</b></li>
            <li><span>语义评分</span><b className="srv-sum-val ok">8.2</b></li>
            <li><span>抄袭检测</span><b className="srv-sum-val ok">通过</b></li>
            <li><span>禁忌触发</span><b className="srv-sum-val warn">1 项（轻）</b></li>
          </ul>
        </div>

        <div className="card-flat srv-rewrite">
          <div className="ctx-head" style={{marginBottom:10}}><I.Wand size={13} /><span>自动改写建议</span></div>
          <div className="srv-rewrite-item">
            <span className="pill pill-gold text-xs"><span className="pill-dot" />禁忌</span>
            <p>把「愈来愈浓的暮色」改为具象动作或物件，避免成语化抒情。</p>
          </div>
          <div className="srv-rewrite-item">
            <span className="pill pill-slate text-xs"><span className="pill-dot" />量化</span>
            <p>对话占比 5%（目标 23%±9），可在段中补一句短对话。</p>
          </div>
          <button className="btn btn-primary btn-sm" style={{width:"100%", marginTop:8}}><I.Refresh size={13} /> 带建议重写（最多 2 轮）</button>
          <p className="text-xs text-muted mt-2" style={{textAlign:"center"}}>partial 自动重试；fail / 抄袭 直接进审核。</p>
        </div>

        <button className="btn btn-accent btn-lg" style={{width:"100%"}} onClick={() => go && go("apply")}>
          <I.ArrowRight size={15} /> 进入注入应用
        </button>
      </aside>

      <style dangerouslySetInnerHTML={{ __html: srvCss }} />
    </div>
  );
};

/* ============ ValidationReportCard ============ */
window.ValidationReportCard = function ValidationReportCard({ verdict, mode }) {
  return (
    <div className="vrc">
      {/* Quantitative */}
      <div className="card">
        <div className="card-head">
          <div><div className="card-title">量化对齐</div><div className="card-sub">自适应阈值 = max(σ × 1.25, 绝对下限)</div></div>
          <span className="pill pill-sage"><span className="pill-dot" />{SRV_QUANT.filter(passQuant).length} / {SRV_QUANT.length} 通过</span>
        </div>
        <div className="vrc-quant">
          {SRV_QUANT.map((m, i) => <QuantBar key={i} m={m} />)}
        </div>
      </div>

      <div className="vrc-row">
        {/* Semantic radar */}
        <div className="card">
          <div className="card-head">
            <div><div className="card-title">语义评分</div><div className="card-sub">critic LLM · 强制引用证据</div></div>
            {mode === "sync_only"
              ? <span className="pill pill-slate text-xs"><span className="pill-dot" />异步补算中</span>
              : <span className="pill pill-sage text-xs"><span className="pill-dot" />8.2 / 10</span>}
          </div>
          {mode === "sync_only" ? (
            <div className="vrc-async">
              <span className="step-spin-dark" />
              <span className="text-muted text-sm">语义路径后台运行中，完成后入库供审核查看…</span>
            </div>
          ) : (
            <RadarChart data={SRV_RADAR} />
          )}
        </div>

        {/* Plagiarism */}
        <div className="card">
          <div className="card-head">
            <div><div className="card-title">抄袭检测</div><div className="card-sub">Rabin-Karp · {SRV_PLAG.ngram}-gram · 阈值 {SRV_PLAG.threshold} 字</div></div>
            <span className={`pill ${SRV_PLAG.passed ? "pill-sage" : "pill-crimson"}`}><span className="pill-dot" />{SRV_PLAG.passed ? "通过" : "命中"}</span>
          </div>
          <div className="vrc-plag-meter">
            <div className="vrc-plag-track">
              <div className="vrc-plag-fill" style={{width: (SRV_PLAG.maxRun / SRV_PLAG.threshold * 100) + "%"}} />
              <div className="vrc-plag-threshold" style={{left: "100%"}} />
            </div>
            <div className="vrc-plag-legend">
              <span>最长连续重叠 <b className="tab-num">{SRV_PLAG.maxRun}</b> 字</span>
              <span className="text-muted">阈值 {SRV_PLAG.threshold} 字</span>
            </div>
          </div>
          <div className="vrc-plag-flags">
            {SRV_PLAG.flags.map((f, i) => (
              <div key={i} className={`vrc-plag-flag lv-${f.level}`}>
                <span className="vrc-plag-run">{f.run} 字</span>
                <div className="vrc-plag-body">
                  <p className="vrc-plag-text text-serif">「…{f.text}…」</p>
                  <p className="vrc-plag-src">{f.source}</p>
                </div>
                {f.level === "ok" && <span className="pill pill-sage text-xs"><span className="pill-dot" />安全</span>}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Forbidden */}
      <div className="card">
        <div className="card-head">
          <div><div className="card-title">禁忌模式检查</div><div className="card-sub">对每条 forbidden_pattern 判断是否触发</div></div>
          <span className={`pill ${SRV_FORBIDDEN.some(f=>f.triggered) ? "pill-gold" : "pill-sage"}`}>
            <span className="pill-dot" />{SRV_FORBIDDEN.filter(f=>f.triggered).length} 触发 / {SRV_FORBIDDEN.length}
          </span>
        </div>
        <ul className="vrc-forbidden">
          {SRV_FORBIDDEN.map((f, i) => (
            <li key={i} className={`vrc-fb ${f.triggered ? "is-hit" : ""}`}>
              <span className="vrc-fb-mark">
                {f.triggered ? <I.AlertTriangle size={14} /> : <I.Check size={14} />}
              </span>
              <div className="vrc-fb-body">
                <span className="vrc-fb-statement">{f.statement}</span>
                {f.triggered && (
                  <div className="vrc-fb-hit">
                    <span className="vrc-fb-excerpt text-serif">「{f.excerpt}」</span>
                    <span className="vrc-fb-note">{f.note}</span>
                  </div>
                )}
              </div>
              <span className={`pill text-xs ${f.triggered ? "pill-gold" : "pill-sage"}`}>
                <span className="pill-dot" />{f.triggered ? "触发" : "清白"}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

/* ---- helpers ---- */
function tol(m) { return Math.max(m.std * 1.25, SRV_FLOORS[m.name] || 0.1); }
function passQuant(m) { return Math.abs(m.actual - m.target) <= tol(m); }
function quantPassRate() { return SRV_QUANT.filter(passQuant).length / SRV_QUANT.length; }
function computeVerdict() {
  if (!SRV_PLAG.passed) return { kind: "plagiarism", label: "抄袭风险", sub: "最长重叠超阈值，直接进审核" };
  const hardForbidden = SRV_FORBIDDEN.some(f => f.triggered && f.severity === "error");
  if (hardForbidden) return { kind: "fail", label: "未通过", sub: "触发硬性禁忌模式" };
  const qr = quantPassRate();
  if (qr >= 0.8) return { kind: "partial", label: "基本通过", sub: "量化达标，1 项轻度禁忌待修" };
  return { kind: "partial", label: "部分通过", sub: "建议带修改重写一轮" };
}

/* ---- QuantBar: target band + actual marker ---- */
function QuantBar({ m }) {
  const t = tol(m);
  // map to a track: center on target, ±2.5*tol visible range
  const range = t * 2.6;
  const lo = m.target - range, hi = m.target + range;
  const toPct = (v) => Math.max(2, Math.min(98, ((v - lo) / (hi - lo)) * 100));
  const bandLo = toPct(m.target - t), bandHi = toPct(m.target + t);
  const actualPct = toPct(m.actual);
  const pass = passQuant(m);
  const fmt = (v) => m.pct ? (v*100).toFixed(0) + "%" : v.toFixed(m.pct ? 2 : 1);
  return (
    <div className="qbar">
      <div className="qbar-head">
        <span className="qbar-name">{m.name}</span>
        <span className={`qbar-verdict ${pass ? "ok" : "off"}`}>
          {pass ? <I.Check size={11} /> : <I.AlertTriangle size={11} />}
          实测 {fmt(m.actual)}
        </span>
      </div>
      <div className="qbar-track">
        <div className="qbar-band" style={{left: bandLo + "%", width: (bandHi - bandLo) + "%"}} />
        <div className="qbar-target" style={{left: toPct(m.target) + "%"}} />
        <div className={`qbar-actual ${pass ? "ok" : "off"}`} style={{left: actualPct + "%"}} />
      </div>
      <div className="qbar-foot">
        <span>目标 {fmt(m.target)} ± {m.pct ? (t*100).toFixed(0)+"%" : t.toFixed(1)}</span>
        <span className={pass ? "ok" : "off"}>偏离 {(Math.abs(m.actual - m.target) / t).toFixed(2)}×</span>
      </div>
    </div>
  );
}

/* ---- RadarChart (SVG polygon) ---- */
function RadarChart({ data }) {
  const size = 240, cx = size/2, cy = size/2, R = 86;
  const n = data.length;
  const angle = (i) => (Math.PI * 2 * i / n) - Math.PI/2;
  const pt = (i, r) => [cx + Math.cos(angle(i)) * R * r, cy + Math.sin(angle(i)) * R * r];
  const poly = data.map((d, i) => pt(i, d.v).join(",")).join(" ");
  return (
    <div className="vrc-radar">
      <svg viewBox={`0 0 ${size} ${size}`} className="vrc-radar-svg">
        {[0.25, 0.5, 0.75, 1].map((r, i) => (
          <polygon key={i}
            points={data.map((_, j) => pt(j, r).join(",")).join(" ")}
            fill="none" stroke="var(--line-2)" strokeWidth="1" />
        ))}
        {data.map((_, i) => {
          const [x, y] = pt(i, 1);
          return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--line-1)" strokeWidth="1" />;
        })}
        <polygon points={poly} fill="var(--crimson)" fillOpacity="0.18" stroke="var(--crimson)" strokeWidth="2" strokeLinejoin="round" />
        {data.map((d, i) => {
          const [x, y] = pt(i, d.v);
          return <circle key={i} cx={x} cy={y} r="3.5" fill="var(--crimson)" stroke="var(--paper-0)" strokeWidth="1.5" />;
        })}
        {data.map((d, i) => {
          const [x, y] = pt(i, 1.18);
          return (
            <text key={i} x={x} y={y} fontSize="11" fill="var(--ink-2)" textAnchor="middle" dominantBaseline="middle" fontFamily="var(--font-sans)">{d.axis}</text>
          );
        })}
      </svg>
      <div className="vrc-radar-legend">
        {data.map((d, i) => (
          <div key={i} className="vrc-radar-leg">
            <span className="vrc-radar-leg-name">{d.axis}</span>
            <span className="vrc-radar-leg-val tab-num">{(d.v*10).toFixed(1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const srvCss = `
.srv { display: grid; grid-template-columns: 1fr 300px; gap: 18px; align-items: start; }
.srv-main { display: flex; flex-direction: column; gap: 16px; }
.srv-input { min-height: 96px; font-size: 15px; line-height: 1.8; }
.srv-input-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; }
.srv-mode-hint { font-size: 12px; color: var(--ink-3); display: flex; align-items: center; }
.srv-mode-hint span { display: inline-flex; align-items: center; gap: 6px; }

.srv-side { display: flex; flex-direction: column; gap: 14px; position: sticky; top: 0; }
.srv-verdict { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 22px; border-radius: 14px; text-align: center; }
.srv-verdict.v-pass { background: var(--sage-wash); color: var(--sage); }
.srv-verdict.v-partial { background: var(--gold-wash); color: var(--gold); }
.srv-verdict.v-fail { background: var(--rose-wash); color: var(--rose); }
.srv-verdict.v-plagiarism { background: var(--crimson-wash); color: var(--crimson); }
.srv-verdict-label { font-family: var(--font-serif); font-size: 20px; font-weight: 600; margin-top: 4px; }
.srv-verdict-sub { font-size: 12.5px; opacity: 0.85; }
.srv-summary { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.srv-summary li { display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
.srv-sum-val { font-family: var(--font-serif); font-size: 15px; }
.srv-sum-val.ok { color: var(--sage); }
.srv-sum-val.warn { color: var(--gold); }
.srv-rewrite-item { display: flex; flex-direction: column; gap: 4px; padding: 10px; background: var(--paper-0); border-radius: 8px; margin-bottom: 8px; }
.srv-rewrite-item p { font-size: 12.5px; line-height: 1.5; color: var(--ink-1); }

/* ValidationReportCard */
.vrc { display: flex; flex-direction: column; gap: 16px; }
.vrc-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 16px; align-items: start; }
.vrc-quant { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px 24px; }

.qbar { display: flex; flex-direction: column; gap: 5px; }
.qbar-head { display: flex; justify-content: space-between; align-items: baseline; }
.qbar-name { font-size: 12.5px; font-weight: 600; color: var(--ink-1); }
.qbar-verdict { display: inline-flex; align-items: center; gap: 3px; font-size: 11.5px; font-variant-numeric: tabular-nums; }
.qbar-verdict.ok { color: var(--sage); }
.qbar-verdict.off { color: var(--gold); }
.qbar-track { position: relative; height: 10px; background: var(--paper-2); border-radius: 5px; }
.qbar-band { position: absolute; top: 0; bottom: 0; background: var(--sage-wash); border-radius: 3px; }
.qbar-target { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--ink-3); border-radius: 1px; }
.qbar-actual { position: absolute; top: 50%; width: 12px; height: 12px; border-radius: 50%; transform: translate(-50%, -50%); border: 2px solid var(--paper-0); box-shadow: var(--shadow-sm); }
.qbar-actual.ok { background: var(--sage); }
.qbar-actual.off { background: var(--gold); }
.qbar-foot { display: flex; justify-content: space-between; font-size: 11px; color: var(--ink-3); }
.qbar-foot .ok { color: var(--sage); }
.qbar-foot .off { color: var(--gold); }

/* Radar */
.vrc-radar { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
.vrc-radar-svg { width: 190px; height: 190px; flex-shrink: 0; }
.vrc-radar-legend { display: flex; flex-direction: column; gap: 6px; flex: 1 1 150px; min-width: 140px; }
.vrc-radar-leg { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 4px 10px; background: var(--paper-0); border-radius: 6px; }
.vrc-radar-leg-name { font-size: 12.5px; color: var(--ink-2); white-space: nowrap; }
.vrc-radar-leg-val { font-family: var(--font-serif); font-weight: 600; color: var(--crimson); }
.vrc-async { display: flex; align-items: center; gap: 12px; padding: 30px 16px; justify-content: center; }
.step-spin-dark { width: 18px; height: 18px; border: 2px solid var(--line-2); border-top-color: var(--crimson); border-radius: 50%; animation: spin 0.8s linear infinite; }
.srv-running { padding: 18px 20px; }
.srv-run-rows { display: flex; flex-direction: column; gap: 12px; }
.srv-run-row { display: flex; align-items: center; gap: 12px; font-size: 13.5px; color: var(--ink-2); }
.srv-run-row .step-spin-dark { width: 15px; height: 15px; }

/* Plagiarism */
.vrc-plag-meter { margin-bottom: 14px; }
.vrc-plag-track { position: relative; height: 8px; background: var(--paper-2); border-radius: 4px; margin-bottom: 8px; }
.vrc-plag-fill { position: absolute; left: 0; top: 0; bottom: 0; background: var(--sage); border-radius: 4px; }
.vrc-plag-threshold { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--rose); }
.vrc-plag-legend { display: flex; justify-content: space-between; font-size: 12px; color: var(--ink-2); }
.vrc-plag-legend b { font-family: var(--font-serif); font-size: 14px; }
.vrc-plag-flags { display: flex; flex-direction: column; gap: 8px; }
.vrc-plag-flag { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 8px; flex-wrap: wrap; }
.vrc-plag-run { font-family: var(--font-mono); font-size: 11px; padding: 2px 7px; border-radius: 4px; background: var(--sage-wash); color: var(--sage); flex-shrink: 0; }
.vrc-plag-body { flex: 1 1 160px; min-width: 140px; }
.vrc-plag-text { font-size: 13px; color: var(--ink-1); white-space: normal; }
.vrc-plag-src { font-size: 11.5px; color: var(--ink-3); margin-top: 2px; }

/* Forbidden */
.vrc-forbidden { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.vrc-fb { display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: center; padding: 12px 14px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 10px; }
.vrc-fb.is-hit { border-left: 3px solid var(--gold); }
.vrc-fb-mark { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 999px; background: var(--sage-wash); color: var(--sage); }
.vrc-fb.is-hit .vrc-fb-mark { background: var(--gold-wash); color: var(--gold); }
.vrc-fb-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.vrc-fb-statement { font-size: 13.5px; color: var(--ink-1); }
.vrc-fb-hit { display: flex; flex-direction: column; gap: 2px; padding: 6px 10px; background: var(--gold-wash); border-radius: 6px; }
.vrc-fb-excerpt { font-size: 13px; color: #6a4d1d; }
.vrc-fb-note { font-size: 11.5px; color: #6a4d1d; opacity: 0.85; }

@media (max-width: 1280px) {
  .srv { grid-template-columns: 1fr; }
  .srv-side { position: static; }
  .vrc-row, .vrc-quant { grid-template-columns: 1fr; }
  .vrc-radar { flex-direction: column; }
}
`;
