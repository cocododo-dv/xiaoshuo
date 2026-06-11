/* global React, I */
const { useState: useSt9, useRef: useRef9, useEffect: useEf9 } = React;

/* ==========================================================
   成稿中心 — Manuscript Center
   一本书在这里一章章成形：左侧按状态分组的章节，右侧
   沉浸式成稿阅读器，顶部「整书进度」书脊条 + 统一导出。
   ========================================================== */

const M_BOOK = {
  title: "潮汐档案",
  kind: "悬疑 · 长篇",
  goalWords: 120000,
  planChapters: 24,
};

const M_CH = [
  { id: "ch01", n: "01", title: "盐钟残片",   state: "approved", words: 5840, scenes: 5, ver: "v12", at: "5 月 8 日",  by: "周岚" },
  { id: "ch02", n: "02", title: "潮汐记录室", state: "approved", words: 6210, scenes: 4, ver: "v9",  at: "5 月 10 日", by: "周岚" },
  { id: "ch03", n: "03", title: "被改写的人", state: "approved", words: 5970, scenes: 5, ver: "v11", at: "5 月 11 日", by: "周岚" },
  { id: "ch04", n: "04", title: "回声讲堂",   state: "approved", words: 5500, scenes: 4, ver: "v7",  at: "今天 09:12", by: "你" },
  { id: "ch05", n: "05", title: "夜班指南",   state: "review",   words: 4820, scenes: 4, ver: "v18" },
  { id: "ch06", n: "06", title: "周岚的钥匙", state: "draft",    words: 5180, scenes: 5, ver: "v3" },
  { id: "ch07", n: "07", title: "三号档案箱", state: "draft",    words: 4900, scenes: 4, ver: "v2" },
  { id: "ch08", n: "08", title: "返回的潮声", state: "writing",  words: 1240, scenes: 5, ver: "v1", sceneDone: 1 },
];

/* 每章真实正文（成稿阅读器读取） */
const M_BODY = {
  ch04: {
    drama: {
      promise: "林岑会被迫直面父亲是潮汐事件「被改写」的核心证人。",
      thrust: "从「未确认」推进到「至少有第二份证据」。",
      turn:   "由「守护父亲名声」转向「先承认父亲也错了」。",
      after:  "把第二份备份独自留下，标签写一行字，没签名。",
    },
    scenes: [
      { idx: "01", title: "傍晚 · 通勤", paras: [
        "雨在地铁出口停下来。林岑站在风口处把伞收起来，水珠从骨架上滑下来，沿着她的袖口流到指缝里。她抬头看了一眼老馆的顶楼，那里有一扇灯还亮着——周岚的办公室。",
        "她没有立刻进去。她在台阶下站了一会儿，像是在确认自己真的要把那片残片带上楼。",
      ]},
      { idx: "02", title: "馆门 · 例行", paras: [
        "她从员工通道刷卡进去，门卡的电子音在长廊里听起来格外刺耳。值班员看了她一眼，没有问。她走过中央天井，玻璃顶外面是橙色的城市光，淹没了头顶的星。",
      ]},
      { idx: "03", title: "夜班修复台 · 二次发现", paras: [
        "林岑把今天的最后一片残片放进恒温箱时，馆里的钟已经过了十一点。",
        "她从来不喜欢这一段时间。十一点之后，老馆的中央空调会进入夜间模式，机器声变得安静，安静到她能听见自己的手指敲在键盘上的回响。",
        "盐钟箱内壁的湿度计是 47%，她记下来——和昨天同一时刻完全一样。可档案编号却差了一位。她盯着那行数字看了很久，才意识到这不是录入错误。这是有人改过。",
      ]},
    ],
  },
  ch01: {
    drama: {
      promise: "一片不该存在的残片，把林岑拉回十二年前的潮汐夜。",
      thrust: "从「整理遗物」推进到「发现遗物在说谎」。",
      turn:   "由「相信记录」转向「怀疑记录的人」。",
      after:  "她第一次把父亲的名字，从受害者那一栏划掉。",
    },
    scenes: [
      { idx: "01", title: "清晨 · 旧物", paras: [
        "纸箱在阁楼上放了十二年，封口的胶带一碰就碎成粉。林岑没有戴手套，她想用指尖记住父亲最后碰过的东西。",
        "最上面是一只盐钟——玻璃壳裂了一道缝，盐粒早就板结成块，再也不会流动。可箱底压着的那片残片，编号却比盐钟晚了整整三年。",
      ]},
      { idx: "02", title: "正午 · 比对", paras: [
        "她把残片拿到窗边。阳光穿过裂缝，在桌面投下一道细盐似的白线。她忽然发现，残片背面有一行极小的刻字，不是父亲的笔迹。",
      ]},
    ],
  },
  ch02: {
    drama: {
      promise: "记录室里每一份档案都完好，唯独属于父亲那一格是空的。",
      thrust: "从「查找」推进到「确认有人先一步清空」。",
      turn:   "由「独自调查」转向「不得不去找周岚」。",
      after:  "空格里只剩一张借阅卡，签名被涂黑。",
    },
    scenes: [
      { idx: "01", title: "潮汐记录室", paras: [
        "记录室在地下二层，常年恒温十八度。林岑推开门，灯一排排次第亮起，像有人替她数着步子。",
        "第七排，父亲的那一格，是空的。不是被取走的空——取走会留登记。是被抹掉的空，连灰尘都被人擦得太干净。",
      ]},
    ],
  },
  ch03: {
    drama: {
      promise: "被改写的不只是档案，还有当年所有在场者的证词。",
      thrust: "从「单点异常」推进到「系统性篡改」。",
      turn:   "由「找真相」转向「先怀疑自己的记忆」。",
      after:  "她发现自己的证词，也被人替她改过一个字。",
    },
    scenes: [
      { idx: "01", title: "证词卷宗", paras: [
        "六份证词，六种笔迹，却用着同一个词去描述那天的海——「安静」。林岑念出声来的时候，自己都觉得不对。那天的海怎么会安静。",
      ]},
      { idx: "02", title: "深夜 · 回放", paras: [
        "她调出十二年前的值班录像。画面里的小女孩站在防波堤上，背对镜头。她认得那件红雨衣。那是她自己。",
        "可她从来不记得，那天自己去过堤上。",
      ]},
    ],
  },
  ch05: {
    scenes: [
      { idx: "01", title: "交班 · 夜班指南", paras: [
        "夜班的第一条规矩写在白板上，已经被擦得发灰：十一点后不要单独下地下二层。林岑用袖子把它擦掉了，又自己写了一遍——这一次，她想知道为什么。",
      ]},
      { idx: "02", title: "走廊 · 脚步", paras: [
        "走廊尽头的声控灯亮了一下，又灭了。没有风。林岑数着自己的心跳，一直数到那盏灯第二次亮起来。",
      ]},
    ],
  },
  ch06: {
    scenes: [
      { idx: "01", title: "草稿 · 周岚的钥匙", paras: [
        "（本章为草稿，尚未送审。）周岚的钥匙串上有一把锈得发黑的旧钥匙，从不解释打开的是哪扇门。林岑第一次注意到它，是在她说「你父亲也有一把一样的」之后。",
      ]},
    ],
  },
  ch07: {
    scenes: [
      { idx: "01", title: "草稿 · 三号档案箱", paras: [
        "（本章为草稿，尚未送审。）三号档案箱的锁是新的，箱子却是旧的。林岑蹲在它面前，忽然不确定自己是想打开它，还是害怕打开它。",
      ]},
    ],
  },
};

/* ---------- 真实正文：从写作器落盘的 wr-doc 文档取段落 ---------- */
function manuDocParas(sid) {
  if (!sid) return null;
  let raw = null;
  try { raw = localStorage.getItem(window.wsKey ? window.wsKey("wr-doc:" + sid) : "wr-doc:" + sid); } catch (e) {}
  if (raw == null) return null;
  const div = document.createElement("div");
  div.innerHTML = raw;
  let paras = Array.from(div.querySelectorAll("p, li")).map(p => (p.textContent || "").trim()).filter(Boolean);
  if (!paras.length) { const t = (div.textContent || "").trim(); paras = t ? t.split(/\n+/).map(x => x.trim()).filter(Boolean) : []; }
  /* 写作器的占位文档不算正文 */
  if (paras.length === 1 && /^在这里开始写/.test(paras[0])) return null;
  return paras.length ? paras : null;
}
/* 目录戏剧卡 → 阅读器概要卡四字段 */
function manuDramaOf(c) {
  const d = (c && c.drama) || {};
  const pick = (v) => (v && v !== "—" ? v : "");
  if (!pick(d.promise) && !pick(d.spine) && !pick(d.arc) && !pick(d.aftertaste)) return null;
  return { promise: pick(d.promise), thrust: pick(d.spine), turn: pick(d.arc), after: pick(d.aftertaste) };
}
/* 章正文：优先写作器真实文档；潮汐档案种子章回落到演示归档 */
function manuBuildBody(catCh, isTide) {
  if (!catCh) return null;
  const scenes = [];
  (catCh.scenes || []).forEach((s, i) => {
    const paras = manuDocParas(s.sid);
    if (paras) scenes.push({ idx: String(i + 1).padStart(2, "0"), title: s.title, paras, live: true });
  });
  if (scenes.length) return { drama: manuDramaOf(catCh), scenes, live: true };
  const seed = isTide ? M_BODY[catCh.id] : null;
  if (seed) return { ...seed, drama: seed.drama || manuDramaOf(catCh) };
  return null;
}
/* ---------- 导出：编译真实内容并下载 ---------- */
function manuDownload(name, content, mime) {
  try {
    const blob = new Blob([content], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { try { URL.revokeObjectURL(a.href); a.remove(); } catch (e) {} }, 0);
    return true;
  } catch (e) { return false; }
}
function manuCompile(book, catChs, scopeIds, fmt, opts, isTide) {
  const sel = (catChs || []).filter(c => scopeIds.includes(c.id));
  const chunks = [];
  const bodies = sel.map(c => ({ c, body: manuBuildBody(c, isTide) }));
  if (fmt === "md") {
    chunks.push(`# ${book.title}\n`);
    if (book.kind) chunks.push(`> ${book.kind}\n`);
    if (opts.toc) {
      chunks.push("\n## 目录\n");
      sel.forEach(c => chunks.push(`- 第 ${c.n} 章 · ${c.title}`));
      chunks.push("");
    }
    bodies.forEach(({ c, body }) => {
      chunks.push(`\n## 第 ${c.n} 章 · ${c.title}\n`);
      if (body && body.scenes) body.scenes.forEach(s => {
        chunks.push(`### ${s.idx} · ${s.title}\n`);
        s.paras.forEach(p => chunks.push(p + "\n"));
      });
      else chunks.push("（本章尚无正文）\n");
      if (opts.appendix) {
        const d = manuDramaOf(c);
        if (d) chunks.push(`> 戏剧卡 — 承诺：${d.promise || "—"}；推进：${d.thrust || "—"}；转变：${d.turn || "—"}；余味：${d.after || "—"}\n`);
      }
    });
    return { name: `${book.title}.md`, content: chunks.join("\n"), mime: "text/markdown;charset=utf-8" };
  }
  if (fmt === "txt") {
    chunks.push(book.title + "\n");
    bodies.forEach(({ c, body }) => {
      chunks.push(`\n\n第 ${c.n} 章 · ${c.title}\n`);
      if (body && body.scenes) body.scenes.forEach(s => { chunks.push(""); s.paras.forEach(p => chunks.push("    " + p)); });
      else chunks.push("（本章尚无正文）");
    });
    return { name: `${book.title}.txt`, content: chunks.join("\n"), mime: "text/plain;charset=utf-8" };
  }
  /* Word 兼容的 HTML .doc */
  const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let html = `<html xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${esc(book.title)}</title></head><body style="font-family:serif">`;
  html += `<h1>${esc(book.title)}</h1>`;
  if (opts.toc) html += "<h2>目录</h2><ul>" + sel.map(c => `<li>第 ${esc(c.n)} 章 · ${esc(c.title)}</li>`).join("") + "</ul>";
  bodies.forEach(({ c, body }) => {
    html += `<h2>第 ${esc(c.n)} 章 · ${esc(c.title)}</h2>`;
    if (body && body.scenes) body.scenes.forEach(s => {
      html += `<h3>${esc(s.idx)} · ${esc(s.title)}</h3>` + s.paras.map(p => `<p>${esc(p)}</p>`).join("");
    });
    else html += "<p>（本章尚无正文）</p>";
    if (opts.appendix) {
      const d = manuDramaOf(c);
      if (d) html += `<blockquote><p>戏剧卡 — 承诺：${esc(d.promise || "—")}；推进：${esc(d.thrust || "—")}；转变：${esc(d.turn || "—")}；余味：${esc(d.after || "—")}</p></blockquote>`;
    }
  });
  html += "</body></html>";
  return { name: `${book.title}.doc`, content: html, mime: "application/msword;charset=utf-8" };
}

const M_TONE = {
  approved: { tone: "sage",    label: "已批准", short: "终稿" },
  review:   { tone: "gold",    label: "审阅中", short: "待批" },
  draft:    { tone: "slate",   label: "草稿",   short: "草稿" },
  writing:  { tone: "crimson", label: "写作中", short: "在写" },
  plan:     { tone: "slate",   label: "计划中", short: "计划" },
};

function WsManuscripts({ go }) {
  /* 章节列表派生自 WsCatalog（与主页 / 写作器 / 编排台同源）；
     ver / at / by 等演示装饰仅对「潮汐档案」种子章节生效。 */
  const isTide = !window.WsWorks || window.WsWorks.activeId() === "tide";
  const M_DECOR = isTide ? Object.fromEntries(M_CH.map(c => [c.id, c])) : {};
  /* 订阅目录：批准 / 退回等动作写穿 WsCatalog 后这里自动刷新 */
  const catChs = window.useCatalogChapters ? window.useCatalogChapters() : (window.WsCatalog ? window.WsCatalog.get() : null);
  const chs = catChs
    ? catChs.filter(c => c.state !== "planned").map(c => {
        const deco = M_DECOR[c.id] || {};
        const scenes = (c.scenes || []).length;
        const liveAt = c.approvedAt ? new Date(c.approvedAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : null;
        return {
          id: c.id, n: c.n, title: c.title, state: c.state,
          words: (c.words && c.words.cur) || 0, scenes,
          ver: deco.ver || "v1", at: liveAt || deco.at, by: liveAt ? "你" : deco.by,
          sceneDone: (c.scenes || []).filter(s => s.state === "done").length,
        };
      })
    : M_CH;

  const work = window.WsWorks ? window.WsWorks.active() : null;
  const book = {
    title: work ? work.title : M_BOOK.title,
    kind: work ? work.genre : M_BOOK.kind,
    goalWords: work ? work.wordsTarget : M_BOOK.goalWords,
    planChapters: Math.max(work ? (work.chaptersTotal || 0) : M_BOOK.planChapters, (catChs || M_CH).length),
  };

  const approvedWords = chs.filter(c => c.state === "approved").reduce((s, c) => s + c.words, 0);
  const approvedCount = chs.filter(c => c.state === "approved").length;
  const reviewCount   = chs.filter(c => c.state === "review").length;
  const flowCount     = chs.filter(c => c.state === "draft" || c.state === "writing").length;
  const pct = Math.round((approvedWords / Math.max(1, book.goalWords)) * 100);

  const [pickedId, setPicked] = useSt9(() => {
    const w = chs.find(c => c.state === "review") || chs.find(c => c.state === "writing");
    return (w || chs[0] || {}).id;
  });
  const [view, setView] = useSt9("read");
  const [returnOpen, setReturnOpen] = useSt9(false);
  const picked = chs.find(c => c.id === pickedId) || chs[0];
  const catPicked = (catChs || []).find(c => c.id === (picked && picked.id)) || null;
  /* 正文：优先写作器真实文档，潮汐档案种子章回落演示归档 */
  const body = catPicked ? manuBuildBody(catPicked, isTide) : (isTide ? M_BODY[pickedId] : null);
  /* 状态流转：全部写穿目录单一真相源；批准时盖上真实时间戳 */
  const setChapterState = (id, state) => {
    if (!window.WsCatalog) return;
    window.WsCatalog.set(window.WsCatalog.get().map(c => (c.id === id ? { ...c, state, ...(state === "approved" ? { approvedAt: Date.now() } : {}) } : c)));
  };
  /* 送审闸门：由控制塔下发的章，章级审计（跨场连续性）未过时不默认放行 */
  const auditPending = (c) => { try { return !!(c && isTide && parseInt(c.n, 10) === 9 && window.Lf7Bridge && !window.Lf7Bridge.isArchived(9) && window.Lf7Bridge.state().handoff9); } catch (e) { return false; } };
  const [gateArm, setGateArm] = useSt9(false);
  useEf9(() => { setGateArm(false); }, [pickedId]);
  const submitToReview = () => {
    if (!picked) return;
    if (auditPending(picked) && !gateArm) { setGateArm(true); return; }
    setGateArm(false);
    setChapterState(picked.id, "review");
  };
  /* 退回小修 = 理由 + 定位 + 待办，三者缺一不可；可顺手直达写作台深改姿态 */
  const doReturn = ({ reason, sid, sceneTitle, openDeep }) => {
    setChapterState(picked.id, "draft");
    if (window.rvPush) window.rvPush({
      kind: "qc", priority: 1,
      title: `第 ${picked.n} 章退回小修：${picked.title}`,
      where: `第 ${picked.n} 章${sceneTitle ? " · " + sceneTitle : ""}`,
      source: "成稿中心",
      detail: reason,
      actions: [
        { label: "直达深改 · 定位本场", intent: "primary", op: "nav", to: "writer", scene: sid, posture: "deep" },
        { label: "查看本章", intent: "ghost", op: "nav", to: "manuscripts" },
        { label: "标记完成", intent: "quiet", op: "resolve" },
      ],
    });
    setReturnOpen(false);
    if (openDeep && go) {
      go("writer");
      setTimeout(() => {
        if (sid) window.dispatchEvent(new CustomEvent("ws:writer-scene", { detail: sid }));
        window.dispatchEvent(new CustomEvent("ws:writer-posture", { detail: "deep" }));
      }, 90);
    }
  };

  const exportChapter = (c) => {
    const out = manuCompile({ title: `${book.title} · 第 ${c.n} 章 ${c.title}`, kind: book.kind }, catChs || [], [c.id], "md", { toc: false, appendix: false }, isTide);
    manuDownload(out.name, out.content, out.mime);
  };

  // 选中没有正文/对比能力的章节时，回退到「正文」标签
  useEf9(() => {
    if (!picked) return;
    if (picked.state === "writing") { setView("read"); }
    if (view === "diff" && picked.state !== "approved" && picked.state !== "review") setView("read");
  }, [pickedId]); // eslint-disable-line

  /* 空白作品：还没有任何成稿 */
  if (!picked) {
    return (
      <div className="ms-page" data-screen-label="manuscripts · empty">
        <div style={{ display: "grid", placeItems: "center", minHeight: "70vh", textAlign: "center" }}>
          <div style={{ maxWidth: 420, display: "grid", gap: 14, justifyItems: "center" }}>
            <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, color: "var(--ink-1)" }}>成稿中心还是空的</div>
            <p style={{ color: "var(--ink-3)", fontSize: 14, lineHeight: 1.8, margin: 0 }}>写出第一章后，章节会在这里一章章成形、送审、定稿。</p>
            <button className="btn btn-accent" onClick={() => go && go("writer")}><I.Pen size={15} /> 去写作</button>
          </div>
        </div>
      </div>
    );
  }

  const groups = [
    { key: "approved", label: "已批准终稿", items: chs.filter(c => c.state === "approved") },
    { key: "flow",     label: "流转中",     items: chs.filter(c => c.state === "review" || c.state === "draft") },
    { key: "writing",  label: "写作中",     items: chs.filter(c => c.state === "writing") },
  ];

  return (
    <div className="ms-page" data-screen-label="manuscripts">
      <ManuHero
        book={book} chapters={chs}
        stats={{ approvedWords, approvedCount, reviewCount, flowCount, pct }}
        pickedId={pickedId} onPick={setPicked}
        exportCtx={{ catChs: catChs || [], isTide, book, chs, pickedId }}
      />

      <div className="ms-cols">
        <aside className="ms-list">
          {groups.map(g => g.items.length > 0 && (
            <div key={g.key} className="ms-list-group">
              <div className="ms-list-grouphd">
                <span>{g.label}</span>
                <span className="ms-list-groupn">{g.items.length}</span>
              </div>
              <ul className="ms-list-items">
                {g.items.map(c => (
                  <li key={c.id}>
                    <button className={`ms-list-row ${pickedId === c.id ? "is-active" : ""}`} onClick={() => setPicked(c.id)}>
                      <span className="ms-list-num">{c.n}</span>
                      <span className="ms-list-body">
                        <span className="ms-list-title text-serif">{c.title}</span>
                        <span className="ms-list-meta">
                          {c.words ? `${c.words.toLocaleString()} 字` : "未起稿"} · {c.scenes} 场
                          {c.state === "writing" && ` · 第 ${c.sceneDone}/${c.scenes} 场`}
                        </span>
                      </span>
                      <ManuState s={c.state} />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </aside>

        <section className="ms-reader">
          <header className="ms-reader-head">
            <div className="ms-reader-id">
              <div className="ms-reader-eyebrow">第 {picked.n} 章 · {picked.ver}</div>
              <h1 className="ms-reader-title text-serif">{picked.title}</h1>
              <div className="ms-reader-sub">
                {picked.scenes} 场 · {picked.words ? `${picked.words.toLocaleString()} 字` : "—"}
                {picked.state === "approved" && <span> · <I.Lock size={11} style={{verticalAlign:"-1px"}} /> 已批准{picked.at ? `于 ${picked.at} · ${picked.by}` : ""}</span>}
                {picked.state === "writing" && <span> · 已完成 {picked.sceneDone}/{picked.scenes} 场</span>}
              </div>
            </div>
            <div className="ms-reader-tools">
              <ManuState s={picked.state} big />
              {picked.state !== "writing" && (
                <div className="seg">
                  <button className={`seg-btn ${view === "read" ? "is-active" : ""}`} onClick={() => setView("read")}>正文</button>
                  <button className={`seg-btn ${view === "structure" ? "is-active" : ""}`} onClick={() => setView("structure")}>结构</button>
                  {(picked.state === "approved" || picked.state === "review") && isTide && M_BODY[picked.id] &&
                    <button className={`seg-btn ${view === "diff" ? "is-active" : ""}`} onClick={() => setView("diff")}>对比</button>}
                </div>
              )}
            </div>
          </header>

          {picked.state === "writing"
            ? <ManuWriting picked={picked} go={go} gate={auditPending(picked) ? (gateArm ? "armed" : "pending") : null} onSubmit={submitToReview} />
            : (
              <>
                {view === "read"      && <ManuRead picked={picked} body={body} />}
                {view === "structure" && <ManuStructure picked={picked} body={body} catCh={catPicked} />}
                {view === "diff"      && <ManuDiff picked={picked} />}
              </>
            )}

          <footer className="ms-reader-foot">
            <ManuFootNote picked={picked} />
            <div className="flex gap-2">
              {picked.state === "review" && (
                <>
                  <button className="btn btn-ghost" onClick={() => setReturnOpen(true)}>退回小修</button>
                  <button className="btn btn-accent" onClick={() => setChapterState(picked.id, "approved")}><I.Check size={14} /> 批准为终稿</button>
                </>
              )}
              {picked.state === "draft" && (
                <button className="btn btn-accent" onClick={() => setChapterState(picked.id, "review")}>送入审阅</button>
              )}
              {picked.state === "approved" && (
                <>
                  <button className="btn btn-quiet btn-sm" onClick={() => exportChapter(picked)}><I.Download size={13} /> 导出本章</button>
                  <button className="btn btn-ghost" onClick={() => setChapterState(picked.id, "draft")}><I.Refresh size={13} /> 重新打开</button>
                </>
              )}
              {picked.state === "writing" && (
                <button className="btn btn-accent" onClick={() => go("writer")}><I.Pen size={13} /> 回写作房间续写</button>
              )}
            </div>
          </footer>
        </section>
      </div>

      {returnOpen && <ManuReturnModal picked={picked} catCh={catPicked} onClose={() => setReturnOpen(false)} onConfirm={doReturn} />}
    </div>
  );
}

/* ---------- Hero · 整书进度 ---------- */
function ManuHero({ book, chapters, stats, pickedId, onPick, exportCtx }) {
  const cells = [];
  for (let i = 0; i < book.planChapters; i++) {
    const ch = chapters[i];
    cells.push(ch ? { ...ch } : { id: `plan${i}`, n: String(i + 1).padStart(2, "0"), state: "plan", plan: true });
  }
  return (
    <header className="ms-hero">
      <div className="ms-hero-top">
        <div className="ms-hero-id">
          <div className="page-eyebrow" style={{margin:0}}>成稿中心 · MANUSCRIPT</div>
          <h1 className="ms-hero-title text-serif">{book.title}</h1>
          <span className="ms-hero-kind">{book.kind}</span>
        </div>

        <div className="ms-hero-stats">
          <Stat v={stats.approvedWords.toLocaleString()} k="已定稿字数" sub={`占目标 ${stats.pct}%`} />
          <Stat v={`${stats.approvedCount}/${book.planChapters}`} k="已批准章" sub="终稿锁定" />
          <Stat v={stats.reviewCount} k="待你批准" sub="审阅中" tone={stats.reviewCount ? "gold" : ""} />
          <Stat v={(book.goalWords - stats.approvedWords).toLocaleString()} k="距整书目标" sub={`${book.goalWords.toLocaleString()} 字`} />
        </div>

        <ManuExport ctx={exportCtx} />
      </div>

      <div className="ms-spine" role="img" aria-label={`整书 ${book.planChapters} 章进度`}>
        {cells.map(c => (
          <button
            key={c.id}
            className={`ms-spine-cell tone-${M_TONE[c.state].tone} ${c.state} ${pickedId === c.id ? "is-picked" : ""} ${c.plan ? "is-plan" : ""}`}
            title={`第 ${c.n} 章${c.title ? " · " + c.title : ""} — ${M_TONE[c.state].label}`}
            onClick={() => !c.plan && onPick(c.id)}
            disabled={c.plan}
          >
            <span className="ms-spine-n">{c.n}</span>
          </button>
        ))}
      </div>
      <div className="ms-spine-legend">
        <Leg tone="sage" label="已批准终稿" />
        <Leg tone="gold" label="审阅中" />
        <Leg tone="slate" label="草稿" />
        <Leg tone="crimson" label="写作中" />
        <Leg tone="plan" label="计划中" />
      </div>
    </header>
  );
}

function Stat({ v, k, sub, tone }) {
  return (
    <div className={`ms-stat ${tone ? "ms-stat-" + tone : ""}`}>
      <div className="ms-stat-v text-serif">{v}</div>
      <div className="ms-stat-k">{k}</div>
      <div className="ms-stat-sub">{sub}</div>
    </div>
  );
}
function Leg({ tone, label }) {
  return <span className="ms-leg"><span className={`ms-leg-dot tone-${tone}`} />{label}</span>;
}

/* ---------- 统一导出（真实编译：目录 + 写作器正文） ---------- */
function ManuExport({ ctx }) {
  const [open, setOpen] = useSt9(false);
  const [fmt, setFmt] = useSt9("md");
  const [scope, setScope] = useSt9("approved");
  const [toc, setToc] = useSt9(true);
  const [appendix, setAppendix] = useSt9(false);
  const [done, setDone] = useSt9("");
  const ref = useRef9(null);

  useEf9(() => {
    if (!open) return;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const { catChs = [], isTide, book = {}, chs = [], pickedId } = ctx || {};
  const approvedIds = chs.filter(c => c.state === "approved").map(c => c.id);
  const scopeIds =
    scope === "approved" ? approvedIds :
    scope === "current"  ? (pickedId ? [pickedId] : []) :
    chs.map(c => c.id);
  const scopeWords = chs.filter(c => scopeIds.includes(c.id)).reduce((s, c) => s + (c.words || 0), 0);
  const canExport = scopeIds.length > 0;

  const run = () => {
    if (!canExport) return;
    const out = manuCompile(book, catChs, scopeIds, fmt, { toc, appendix }, isTide);
    if (manuDownload(out.name, out.content, out.mime)) {
      setDone(`已生成「${out.name}」`);
      setTimeout(() => { setDone(""); setOpen(false); }, 1400);
    }
  };

  return (
    <div className="ms-export" ref={ref}>
      <button className={`btn btn-accent ms-export-btn ${open ? "is-open" : ""}`} onClick={() => setOpen(o => !o)}>
        <I.UploadCloud size={15} /> 统一导出
      </button>
      {open && (
        <div className="ms-export-pop">
          <div className="ms-export-hd">统一导出 · 发布</div>

          <div className="ms-export-field">
            <div className="ms-export-lab">范围</div>
            <div className="seg seg-block">
              <button className={`seg-btn ${scope === "all" ? "is-active" : ""}`} onClick={() => setScope("all")}>全书</button>
              <button className={`seg-btn ${scope === "approved" ? "is-active" : ""}`} onClick={() => setScope("approved")}>仅已批准 · {approvedIds.length}</button>
              <button className={`seg-btn ${scope === "current" ? "is-active" : ""}`} onClick={() => setScope("current")}>当前章</button>
            </div>
          </div>

          <div className="ms-export-field">
            <div className="ms-export-lab">格式</div>
            <div className="seg seg-block">
              {[["md","Markdown"],["txt","纯文本"],["doc","Word"]].map(([k, l]) => (
                <button key={k} className={`seg-btn ${fmt === k ? "is-active" : ""}`} onClick={() => setFmt(k)}>{l}</button>
              ))}
            </div>
          </div>

          <div className="ms-export-field">
            <div className="ms-export-lab">选项</div>
            <label className="ms-export-opt"><input type="checkbox" checked={toc} onChange={e => setToc(e.target.checked)} /> 生成目录</label>
            <label className="ms-export-opt"><input type="checkbox" checked={appendix} onChange={e => setAppendix(e.target.checked)} /> 附戏剧卡附录</label>
          </div>

          <div className="ms-export-foot">
            <span className="text-muted text-xs">{done || (canExport ? `约 ${scopeWords.toLocaleString()} 字 · ${scopeIds.length} 章` : "该范围内没有章节")}</span>
            <button className="btn btn-accent btn-sm" disabled={!canExport} onClick={run}><I.Download size={13} /> 生成并下载</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- 状态药丸 ---------- */
function ManuState({ s, big }) {
  const m = M_TONE[s] || M_TONE.draft;
  return <span className={`pill pill-${m.tone} ${big ? "" : "text-xs"}`}><span className="pill-dot" />{m.label}</span>;
}

function ManuFootNote({ picked }) {
  const note = {
    approved: <span><I.Lock size={12} style={{verticalAlign:"-2px"}} /> 已锁定终稿 · 不可编辑。需要修改请「重新打开」或回到章节编排。</span>,
    review:   <span>{picked.scenes} 场已成稿。检查无误后批准为终稿，章节将汇入整书。</span>,
    draft:    <span>草稿已写 {picked.words.toLocaleString()} 字。送审后才能进入批准流程。</span>,
    writing:  <span>第 {picked.sceneDone}/{picked.scenes} 场正在写。全部场景完成后才能进入审阅。</span>,
  };
  return <div className="text-muted text-sm">{note[picked.state]}</div>;
}

/* ---------- 正文阅读器 ---------- */
function ManuRead({ picked, body }) {
  if (!body || !body.scenes) {
    return <div className="ms-empty"><I.BookOpen size={26} /><div>本章正文尚未归档。</div></div>;
  }
  return (
    <article className="ms-read">
      <div className="ms-read-chno">第 {picked.n} 章</div>
      <h2 className="ms-read-htitle text-serif">{picked.title}</h2>
      {body.scenes.map((s, i) => (
        <div key={i} className="ms-scene">
          <header className="ms-scene-head">
            <span className="ms-scene-idx">{s.idx}</span>
            <span className="ms-scene-title">{s.title}</span>
          </header>
          {s.paras.map((p, j) => <p key={j} className="ms-scene-p">{p}</p>)}
        </div>
      ))}
      <div className="ms-read-end">— 章节结束 —</div>
    </article>
  );
}

/* ---------- 写作中占位 ---------- */
function ManuWriting({ picked, go, onSubmit, gate }) {
  const total = Math.max(1, picked.scenes || 0);
  const allDone = picked.scenes > 0 && picked.sceneDone >= picked.scenes;
  return (
    <div className="ms-writing">
      <div className="ms-writing-card">
        <div className="ms-writing-mark">{allDone ? <I.CheckCircle size={20} /> : <I.Pen size={20} />}</div>
        <h3 className="text-serif" style={{fontSize:19, margin:0}}>{allDone ? "全部场景已成稿" : "本章仍在写作"}</h3>
        <p className="text-muted text-sm" style={{maxWidth:380, lineHeight:1.7}}>
          {allDone
            ? <>「{picked.title}」的 {picked.scenes} 场全部完成，共 {picked.words.toLocaleString()} 字。送入审阅后即可批准为终稿。</>
            : <>「{picked.title}」已写 {picked.words.toLocaleString()} 字，完成 {picked.sceneDone}/{picked.scenes} 场。全部场景成稿后，会自动出现在成稿中心等待审阅。</>}
        </p>
        <div className="ms-writing-bar">
          <div className="ms-writing-fill" style={{width: `${((picked.sceneDone || 0) / total) * 100}%`}} />
        </div>
        {allDone
          ? (gate ? (
            <div style={{ display: "grid", gap: 10, justifyItems: "center" }}>
              <p className="text-sm" style={{ margin: 0, maxWidth: 380, lineHeight: 1.7, color: gate === "armed" ? "var(--rose)" : "var(--ink-3)" }}>
                {gate === "armed"
                  ? "再次点击「仍要送审」将跳过章级审计直接送审——设定漂移 / 承诺回收将无人把关。"
                  : "本章由控制塔下发起草——送审前需先通过章级审计（跨场连续性把关）。"}
              </p>
              <div className="flex gap-2">
                <button className="btn btn-accent btn-sm" onClick={() => go("longform")}><I.ShieldCheck size={13} /> 去控制塔章级审计</button>
                <button className="btn btn-ghost btn-sm" onClick={onSubmit}>{gate === "armed" ? "仍要送审（带病）" : "跳过审计送审"}</button>
              </div>
            </div>
          ) : <button className="btn btn-accent btn-sm" onClick={onSubmit}><I.Check size={13} /> 送入审阅</button>)
          : <button className="btn btn-accent btn-sm" onClick={() => go("writer")}><I.Pen size={13} /> 回写作房间续写</button>}
      </div>
    </div>
  );
}

/* ---------- 结构 ---------- */
function ManuStructure({ picked, body, catCh }) {
  const drama = (body && body.drama) || manuDramaOf(catCh);
  /* 场景拼接：优先目录真实场景（含状态/字数），种子章回落演示归档 */
  const rows = catCh && (catCh.scenes || []).length
    ? catCh.scenes.map((s, i) => {
        const paras = manuDocParas(s.sid);
        return {
          idx: String(i + 1).padStart(2, "0"), title: s.title,
          meta: paras ? `${paras.join("").length} 字 · 已归档` : (typeof s.words === "number" && s.words > 0 ? `${s.words.toLocaleString()} 字` : "未展开"),
          done: !!paras || s.state === "done",
        };
      })
    : (body && body.scenes ? body.scenes.map(s => ({ idx: s.idx, title: s.title, meta: `${s.paras.join("").length} 字 · 已归档`, done: true })) : []);
  return (
    <div className="ms-struct">
      {drama && (
        <div className="card">
          <div className="card-head"><div className="card-title">戏剧卡 · 概要</div></div>
          <div className="ms-struct-grid">
            <div><div className="ms-struct-k">核心承诺</div><div className="ms-struct-v">{drama.promise || "—"}</div></div>
            <div><div className="ms-struct-k">主线推进</div><div className="ms-struct-v">{drama.thrust || "—"}</div></div>
            <div><div className="ms-struct-k">人物变化</div><div className="ms-struct-v">{drama.turn || "—"}</div></div>
            <div><div className="ms-struct-k">结尾余味</div><div className="ms-struct-v">{drama.after || "—"}</div></div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head"><div className="card-title">场景拼接 · {rows.length} 场</div></div>
        <ul className="ms-struct-scenes">
          {rows.map((s, i) => (
            <li key={i} className={s.done ? "" : "is-ghost"}>
              <span className="ms-scene-idx">{s.idx}</span>
              <span className={s.done ? "text-serif fw-600" : "text-muted"}>{s.title}</span>
              <span className="text-muted text-sm">{s.meta}</span>
              {s.done ? <I.Check size={13} style={{color: "var(--sage)"}} /> : <I.Dot size={13} />}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ---------- 对比 ---------- */
function ManuDiff({ picked }) {
  return (
    <div className="ms-diff">
      <div className="ms-diff-head">
        <span className="text-muted text-sm">对比</span>
        {window.WsDemoTag && <window.WsDemoTag note="版本对比为演示数据：写作器暂未保留历史版本，接入后这里会显示真实 diff。" />}
        <select className="select" style={{maxWidth: 190}} defaultValue="cur">
          <option value="cur">{picked.ver} · 当前</option>
          <option>v17 · 1 小时前</option>
          <option>v16 · 今早 09:14</option>
        </select>
        <I.ArrowRight size={14} style={{color:"var(--ink-3)"}} />
        <select className="select" style={{maxWidth: 190}} defaultValue="prev">
          <option value="prev">v17 · 1 小时前</option>
          <option>v16 · 今早 09:14</option>
        </select>
        <span className="ms-diff-stat"><span className="d-add-dot" />+2 句</span>
        <span className="ms-diff-stat"><span className="d-del-dot" />−1 句</span>
      </div>
      <div className="ms-diff-body">
        <p className="ms-diff-p"><span className="d-same">林岑把今天的最后一片残片放进恒温箱时，馆里的钟已经过了十一点。</span></p>
        <p className="ms-diff-p">
          <span className="d-same">她从来不喜欢这一段时间。十一点之后，老馆的中央空调会进入夜间模式，</span>
          <span className="d-del">机器声变得很轻</span>
          <span className="d-add">机器声变得安静</span>
          <span className="d-same">，安静到她能听见自己的手指敲在键盘上的回响。</span>
        </p>
        <p className="ms-diff-p">
          <span className="d-add">盐钟箱内壁的湿度计是 47%，她记下来——和昨天同一时刻完全一样。可档案编号却差了一位。</span>
        </p>
      </div>
    </div>
  );
}

/* ---------- 退回小修 · 理由 + 定位 + 待办 ---------- */
function ManuReturnModal({ picked, catCh, onClose, onConfirm }) {
  const scenes = (catCh && catCh.scenes) || [];
  const [reason, setReason] = useSt9("");
  const [sid, setSid] = useSt9(() => (scenes[0] ? scenes[0].sid : null));
  const [openDeep, setOpenDeep] = useSt9(true);
  const ref = useRef9(null);
  useEf9(() => { if (ref.current) ref.current.focus(); }, []);
  useEf9(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const sceneTitle = (scenes.find(s => s.sid === sid) || {}).title || "";
  const can = reason.trim().length > 0;
  return (
    <div className="mr-scrim" onClick={onClose}>
      <div className="mr-card" role="dialog" aria-modal="true" aria-label="退回小修" onClick={(e) => e.stopPropagation()}>
        <header className="mr-head">
          <div>
            <div className="mr-title text-serif">退回小修 · 第 {picked.n} 章 {picked.title}</div>
            <div className="mr-sub">章状态回到「草稿」，并生成一条带定位的修订待办</div>
          </div>
          <button className="mr-x" onClick={onClose} title="取消"><I.X size={16} /></button>
        </header>

        <label className="mr-field">
          <span className="mr-k">退回理由 <em>必填</em></span>
          <textarea ref={ref} className="mr-area" rows={3} value={reason}
            placeholder="写清楚为什么退、改哪里——这段话会原样出现在待办里。"
            onChange={(e) => setReason(e.target.value)} />
        </label>

        {scenes.length > 0 && (
          <div className="mr-field">
            <span className="mr-k">定位到场</span>
            <div className="mr-scenes">
              {scenes.map((s, i) => (
                <button key={s.sid} className={`mr-scene ${sid === s.sid ? "is-sel" : ""}`} onClick={() => setSid(s.sid)}>
                  <span className="mr-scene-n">{String(i + 1).padStart(2, "0")}</span>{s.title}
                </button>
              ))}
            </div>
          </div>
        )}

        <label className="mr-check">
          <input type="checkbox" checked={openDeep} onChange={(e) => setOpenDeep(e.target.checked)} />
          退回后直接在写作台·深改姿态中打开这一场
        </label>

        <footer className="mr-foot">
          <button className="btn btn-ghost" onClick={onClose}>取消</button>
          <button className="btn btn-accent" disabled={!can} onClick={() => onConfirm({ reason: reason.trim(), sid, sceneTitle, openDeep })}>
            退回并生成待办
          </button>
        </footer>
      </div>
    </div>
  );
}

Object.assign(window, { WsManuscripts });
