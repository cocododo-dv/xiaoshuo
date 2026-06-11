/* global React, I */
/* ==========================================================
   ws-deep — 深改引擎 + 写作台深改面板（原独立「深改台」并入写作台）
   ----------------------------------------------------------
   · wrDeepScan(el, sid)      诊断当前场正文 → issues
   · wrDeepMark / wrDeepUnmark  在编辑器里标注 / 清除风险高亮
   · wrDeepAdopt(el, issue, cand) 把候选写回正文 DOM（调用方负责落盘）
   · WrDeepDrawer             写作台右栏的诊断面板（问题 + 候选 + 决定日志）
   诊断 = 启发式规则（任何作品可用）+ 演示作品的精修条目（带改写候选）。
   ========================================================== */
const { useState: useDX, useEffect: useDXE } = React;

const dxKey = (base) => (window.wsKey ? window.wsKey(base) : base);

/* ---- 决定日志 / 忽略清单（按场景持久化）---- */
function wrDxLog(sid) {
  try { return JSON.parse(localStorage.getItem(dxKey("wr-deep-log:" + sid))) || []; } catch (e) { return []; }
}
function wrDxPushLog(sid, text) {
  const list = [{ at: Date.now(), text }, ...wrDxLog(sid)].slice(0, 30);
  try { localStorage.setItem(dxKey("wr-deep-log:" + sid), JSON.stringify(list)); } catch (e) {}
  return list;
}
function wrDxSkips(sid) {
  try { return new Set(JSON.parse(localStorage.getItem(dxKey("wr-deep-skip:" + sid))) || []); } catch (e) { return new Set(); }
}
function wrDxAddSkip(sid, key) {
  const s = wrDxSkips(sid); s.add(key);
  try { localStorage.setItem(dxKey("wr-deep-skip:" + sid), JSON.stringify([...s])); } catch (e) {}
}
function wrDxClearSkips(sid) {
  try { localStorage.removeItem(dxKey("wr-deep-skip:" + sid)); } catch (e) {}
}

/* ---- 演示作品的精修条目（带改写候选；find 必须命中正文才显示）---- */
const WR_DEEP_CURATED = {
  ch08s3: [
    {
      id: "cu-echo", kind: "echo", sev: "high",
      find: "机器声变得安静，安静到她能听见自己的手指敲在键盘上的回响。",
      title: "「安静，安静到」回响节奏过重",
      hint: "短句重复让节奏过于刻意。三个改法各保留一种声音质感。",
      cands: [
        { label: "改换连接", text: "连机器声都收回去了；她坐在原地，能听见自己的手指敲在键盘上的回响。" },
        { label: "继电器版", text: "机器声变得几乎听不见，只剩继电器在盐钟箱里偶尔咔嗒一下，像旧打字机的最后一个键。" },
        { label: "水滴版",   text: "机器声退到一边。盐钟箱的冷凝水滴落在底盘上，一滴一滴，像谁在背后小心地数她的呼吸。" },
      ],
    },
    {
      id: "cu-dump", kind: "dump", sev: "mid",
      find: "今天上午从地下室搬上来的那一批，她已经处理完了四件，只剩这一件——一枚边缘磨损的盐钟铭牌，铭牌背后压着一张手写的备份单。",
      title: "一段同时介绍三件物品",
      hint: "信息堆叠，考虑让铭牌成为唯一入口。",
      cands: [
        { label: "收束版", text: "上午那一批她已经处理完了，只剩这一件——一枚边缘磨损的盐钟铭牌。铭牌背后压着一张手写的备份单。" },
      ],
    },
    {
      id: "cu-rdn", kind: "rdn", sev: "low",
      find: "她也认得馆里所有人的字迹。这是她做这份工作的本事。",
      title: "「做这份工作的本事」与第 1 章呼应",
      hint: "可删，让上一句「她认得父亲的字迹」留有余地。",
      cands: [{ label: "删去这两句", text: "" }],
    },
  ],
};
function wrDeepCurated(sid) {
  try { if (window.WsWorks && window.WsWorks.activeId() !== "tide") return []; } catch (e) {}
  return WR_DEEP_CURATED[sid] || [];
}

const WR_DX_KINDS = {
  echo: { tag: "ECH", label: "回响" },
  vague:{ tag: "VAG", label: "抽象" },
  dump: { tag: "DMP", label: "堆叠" },
  rdn:  { tag: "RDN", label: "重复" },
};

/* ---- 诊断：精修条目 + 启发式规则 ---- */
function wrDeepScan(el, sid) {
  if (!el) return [];
  const paras = Array.from(el.querySelectorAll("p, blockquote"));
  const texts = paras.map(p => (p.textContent || "").trim());
  const issues = [];
  const skips = wrDxSkips(sid);

  wrDeepCurated(sid).forEach(cu => {
    const pid = texts.findIndex(t => t.includes(cu.find));
    if (pid >= 0) issues.push({ ...cu, pid, key: cu.id });
  });

  texts.forEach((t, pid) => {
    if (!t || /^在这里开始写/.test(t)) return;
    /* 贴邻叠句：「安静，安静到」式回响 */
    const m = t.match(/([\u4e00-\u9fa5]{2,5})([，、；]?)\1/);
    if (m && !issues.some(it => it.pid === pid && it.find && it.find.includes(m[0]))) {
      issues.push({
        key: "echo:" + pid + ":" + m[1], kind: "echo", sev: "mid", pid, find: m[0],
        title: `「${m[1]}${m[2] || ""}${m[1]}」贴邻重复`,
        hint: "短语回响节奏偏刻意，考虑改换连接或删一处。",
      });
    }
    /* 段落偏长 */
    if (t.length > 170 && !issues.some(it => it.pid === pid && it.kind === "dump")) {
      issues.push({
        key: "dump:" + pid, kind: "dump", sev: "low", pid,
        title: `第 ${pid + 1} 段偏长（${t.length} 字）`,
        hint: "单段信息密度偏高，考虑拆段或删减一件物事。",
      });
    }
    /* 连续三句同字开头 */
    const sents = t.split(/(?<=[。！？!?])/).filter(s => s.trim());
    for (let i = 0; i + 2 < sents.length; i++) {
      const c = sents[i].trim()[0];
      if (c && sents[i + 1].trim()[0] === c && sents[i + 2].trim()[0] === c) {
        if (!issues.some(it => it.pid === pid && it.kind === "rdn")) issues.push({
          key: "rdn:" + pid + ":" + c, kind: "rdn", sev: "low", pid,
          title: `连续三句以「${c}」开头`,
          hint: "句首重复读起来平，考虑改写其中一句的主语或语序。",
        });
        break;
      }
    }
  });

  const sevRank = { high: 0, mid: 1, low: 2 };
  return issues.filter(it => !skips.has(it.key))
    .sort((a, b) => (sevRank[a.sev] ?? 2) - (sevRank[b.sev] ?? 2) || a.pid - b.pid);
}

/* ---- 编辑器内标注 ---- */
function wrDeepUnmark(el) {
  if (!el) return;
  el.querySelectorAll("mark.wr-dx").forEach(mk => {
    const parent = mk.parentNode;
    while (mk.firstChild) parent.insertBefore(mk.firstChild, mk);
    parent.removeChild(mk);
    parent.normalize();
  });
  el.querySelectorAll(".wr-dx-para").forEach(p => {
    p.classList.remove("wr-dx-para", "is-active");
    p.removeAttribute("data-dx");
  });
}
function wrDeepMark(el, issues, activeKey) {
  if (!el) return;
  wrDeepUnmark(el);
  const paras = Array.from(el.querySelectorAll("p, blockquote"));
  issues.forEach(it => {
    const p = paras[it.pid];
    if (!p) return;
    let wrapped = false;
    if (it.find) {
      const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const i = node.nodeValue.indexOf(it.find);
        if (i >= 0) {
          try {
            const range = document.createRange();
            range.setStart(node, i); range.setEnd(node, i + it.find.length);
            const mk = document.createElement("mark");
            mk.className = `wr-dx k-${it.kind}${it.key === activeKey ? " is-active" : ""}`;
            mk.setAttribute("data-dx", it.key);
            range.surroundContents(mk);
            wrapped = true;
          } catch (e) {}
          break;
        }
      }
    }
    if (!wrapped) {
      p.classList.add("wr-dx-para");
      if (it.key === activeKey) p.classList.add("is-active");
      p.setAttribute("data-dx", it.key);
    }
  });
}

/* ---- 采纳：候选写回正文 DOM（纯 DOM 操作，调用方负责高亮重建与落盘）---- */
function wrDeepAdopt(el, issue, cand) {
  if (!el) return false;
  wrDeepUnmark(el);
  const paras = Array.from(el.querySelectorAll("p, blockquote"));
  const p = paras[issue.pid];
  if (!p) return false;
  const t = p.textContent || "";
  if (!issue.find || !t.includes(issue.find)) return false;
  const next = t.replace(issue.find, cand.text);
  if (!next.trim()) p.remove();
  else p.textContent = next;
  return true;
}

/* ==========================================================
   WrDeepDrawer — 写作台右栏 · 深改面板
   ========================================================== */
function WrDeepDrawer({ open, issues, activeKey, onPick, onAdopt, onIgnore, onRescan, onEditDraft, onUndo, canUndo, log, onClose }) {
  const active = issues.find(it => it.key === activeKey) || issues[0] || null;
  const cands = (active && active.cands) || [];
  return (
    <aside className={`wr-drawer right wr-dxd ${open ? "show" : ""}`}>
      <header className="wr-drawer-head">
        <span className="wr-drawer-title"><I.Microscope size={15} /> 深改 · 诊断 {issues.length} 项</span>
        <div className="flex items-center gap-1" style={{ marginLeft: "auto" }}>
          <button className="btn btn-quiet btn-sm" onClick={onRescan} title="重新诊断本场"><I.Refresh size={13} /></button>
          <button className="wr-drawer-x" onClick={onClose} title="收起"><I.X size={15} /></button>
        </div>
      </header>

      <div className="wr-dxd-scroll">
        {issues.length === 0 ? (
          <div className="wr-dxd-clear">
            <I.CheckCircle size={22} />
            <div className="wr-dxd-clear-t">本场没有发现待改的句段</div>
            <p>改过的内容已直接写回正文。可以回到起草姿态继续写，或换一场再诊断。</p>
          </div>
        ) : (
          <>
            <ul className="wr-dxd-list">
              {issues.map(it => {
                const k = WR_DX_KINDS[it.kind] || WR_DX_KINDS.rdn;
                return (
                  <li key={it.key}>
                    <button className={`wr-dxd-row ${active && active.key === it.key ? "is-active" : ""}`} onClick={() => onPick(it.key)}>
                      <span className={`wr-dxd-mark sev-${it.sev}`}>{k.tag}</span>
                      <span className="wr-dxd-body">
                        <span className="wr-dxd-t">{it.title}</span>
                        <span className="wr-dxd-h">{it.hint}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>

            {active && (
              <div className="wr-dxd-cands">
                <div className="wr-dxd-sub">{cands.length ? `改写候选 · ${cands.length}` : "这一项没有现成候选"}</div>
                {cands.map((c, i) => (
                  <article key={i} className="wr-dxd-cand">
                    <header className="wr-dxd-cand-head">
                      <span className="wr-dxd-cand-label">{c.label}</span>
                    </header>
                    {c.text
                      ? <p className="wr-dxd-cand-text">{c.text}</p>
                      : <p className="wr-dxd-cand-text is-del">（删去原句，让上文收住）</p>}
                    <div className="wr-dxd-cand-acts">
                      <button className="btn btn-accent btn-sm" onClick={() => onAdopt(active, c)}><I.Check size={13} /> 采纳 · 写回正文</button>
                    </div>
                  </article>
                ))}
                <div className="wr-dxd-row-acts">
                  {!cands.length && (
                    <button className="btn btn-ghost btn-sm" onClick={() => onEditDraft(active)}><I.Pen size={13} /> 回起草修改这一段</button>
                  )}
                  <button className="btn btn-quiet btn-sm" onClick={() => onIgnore(active)}>忽略这一项</button>
                </div>
              </div>
            )}
          </>
        )}

        {(canUndo || (log && log.length > 0)) && (
          <div className="wr-dxd-log">
            <div className="wr-dxd-sub">最近决定</div>
            {canUndo && (
              <button className="btn btn-ghost btn-sm" style={{ width: "100%", marginBottom: 8 }} onClick={onUndo}>
                <I.Refresh size={13} /> 撤销上一次采纳
              </button>
            )}
            <ul>
              {(log || []).slice(0, 6).map((d, i) => (
                <li key={i} className="wr-dxd-dec">
                  <span className="wr-dxd-dec-t">{new Date(d.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>
                  <span className="wr-dxd-dec-x">{d.text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="wr-dxd-note">采纳即写回本场正文并自动保存；忽略的条目不再提示，可点 <I.Refresh size={11} style={{ verticalAlign: "-1px" }} /> 重新诊断找回。</div>
      </div>
    </aside>
  );
}

Object.assign(window, {
  wrDeepScan, wrDeepMark, wrDeepUnmark, wrDeepAdopt,
  wrDxLog, wrDxPushLog, wrDxAddSkip, wrDxClearSkips,
  WrDeepDrawer,
});
