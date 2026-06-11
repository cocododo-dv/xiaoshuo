/* global React, LF2_BOOK, LF2_NEXT, LF2_CHAPTERS, LF2_TARGET, LF2_THREADS, LF2_LOOPS, LF2_RISKS, LF2_CANON, LF2_ARCS, LF2_ACTS, LF2_CLR, lf2ThreadLast, lf2ThreadStalled, lf2Derive */
/* ==========================================================
   长篇控制塔 v3 — 扩展数据层（在 LF2 单一数据源之上）
   补齐四个关键能力：
   ① 伏笔双向     —— 不止「埋了没收（逾期）」，还有「有揭晓无铺垫（空降）」
   ② 因果脊柱     —— 承重事件之间的因果链；断链 = AI 最爱的逻辑塌方
   ③ 读者认知态   —— 悬疑公平性：读者已知 / 角色已知 / 真相，线索是否提前铺设
   ④ 记忆预算     —— 真实系统有向量库(RAG)：强约束(占预算·永在场) vs 可检索(召回·不占预算)
   并把「交接回执」做成真·草稿审计（逐条比对 + 正文证据句 + 新引入待归档）。
   命名前缀 LF3_ / lf3。
   ========================================================== */

const LF3_BUDGET_CAP = 2400;           // 第 N+1 章「长程记忆」token 预算上限
const LF3_TITLE = "潮汐档案";

/* ---------- ① 空降回收：有揭晓 / 揭示，但全书找不到铺垫 ---------- */
const LF3_ORPHANS = [
  { id: "o1", reveal: "周岚早就认识林岑的父亲", revealCh: 7, sev: "high",
    why: "第 7 章周岚一句台词暗示她与父亲旧识，但前六章无任何铺垫——读者会觉得「凭空冒出」。",
    fix: "在第 1–6 章补一处不起眼的照面 / 物证，让揭示有根。" },
  { id: "o2", reveal: "档案室有第二把钥匙", revealCh: 8, sev: "medium",
    why: "第 8 章顺手用了「第二把钥匙」开门，此前从未出现这把钥匙的存在。",
    fix: "在第 6 章「周岚的钥匙」里多给一个镜头，或改写本章用已知途径。" },
];

/* ---------- ② 因果脊柱：承重事件的因果链 ---------- */
const LF3_CAUSAL = [
  { id: "k1", cause: "父亲销毁值班录像", causeCh: 3, effect: "林岑只能靠盐钟追线索", effectCh: 7, load: true, status: "ok" },
  { id: "k2", cause: "周岚调走档案 No.31", causeCh: 6, effect: "档案箱里出现替换件", effectCh: 8, load: true, status: "ok" },
  { id: "k3", cause: "林岑拿到门禁权限", causeCh: null, effect: "第 8 章独自进入档案室", effectCh: 8, load: true, status: "break",
    why: "第 8 章林岑独自刷卡进入档案室，但全书从未交代她如何获得门禁——因缺前因，这个动作悬空。",
    fix: "在第 5–7 章补一处「拿到 / 借到门禁」的因，或改为周岚带入。" },
];

/* ---------- ③ 读者认知态：悬疑公平性账本 ---------- */
/* truth=真相; planted=线索铺设章(null=尚未铺设); reveal=向读者揭晓章(null=未揭晓);
   knows=已知此真相的角色; fair=揭晓前是否已对读者公平铺设 */
const LF3_CLUES = [
  { id: "q1", q: "父亲是否被人改写记录", truth: "是，被档案学院高层授意", planted: 2, reveal: 7, knows: ["林岑", "周岚"], fair: true },
  { id: "q2", q: "盐钟 No.31 指向什么", truth: "父亲藏下的备份档案柜编号", planted: 1, reveal: null, knows: ["（无）"], fair: true, pending: true },
  { id: "q3", q: "谁动了楼梯间", truth: "周岚的助手，第二组脚印的主人", planted: 2, reveal: null, knows: ["周岚"], fair: false,
    note: "脚印第 2 章已埋，但「主人是谁」至今未给读者任何可推理的线索——若第 9 章直接揭晓即为「不公平」。" },
  { id: "q4", q: "母亲是否知情", truth: "知情且参与了掩盖", planted: null, reveal: 20, knows: ["周岚母亲"], fair: false,
    note: "计划第 20 章揭晓，但目前零铺垫。需在中段开始埋。" },
];

/* ---------- ④ 记忆预算：可检索池（存于全书向量库，相关才召回，不占预算） ---------- */
const LF3_RETRIEVE = [
  { id: "rv1", text: "档案学院走廊的钟摆声 · 环境母题", ch: 2, tone: "slate", reason: "氛围细节，相关章节才需要" },
  { id: "rv2", text: "林岑住在城南旧公寓 7 楼", ch: 1, tone: "slate", reason: "次要设定，写到家时召回" },
  { id: "rv3", text: "阿恪是法医出身 · 善验物证", ch: 1, tone: "slate", reason: "阿恪在场时召回" },
  { id: "rv4", text: "盐钟铭牌背面的备份单（已回收）", ch: 1, tone: "sage", reason: "已结清，仅作背景" },
  { id: "rv5", text: "第 3 章雨夜的潮汐时刻表", ch: 3, tone: "slate", reason: "时间线细节" },
];

/* ---------- token 成本估算（演示用） ---------- */
const LF3_COST = {
  canon: 70, conflict: 130, overdue: 120, promise: 90, thread: 80, tension: 50, arc: 75, orphan: 110, causal: 115, fair: 105,
};

/* ---------- 草稿审计：第 9 章草稿 vs 交接契约 ---------- */
const LF3_AUDIT = {
  ch: 9,
  honored: [
    { id: "h1", label: "锁定设定", text: "林岑 · 年龄 = 28 岁", tone: "sage",
      evidence: "她在借阅登记簿年龄栏写下「28」，笔尖顿了一下，又描深了那个 8。", at: "第 9 章 · 段 4" },
    { id: "h2", label: "锁定设定", text: "盐钟 · 材质 = 铜", tone: "sage",
      evidence: "铜制的盐钟在掌心里发凉，No.31 的刻痕硌着她的指腹。", at: "第 9 章 · 段 9" },
    { id: "h3", label: "逾期回收", text: "楼梯间的第二组脚印", tone: "sage", key: true,
      evidence: "第二组脚印停在三楼转角，比父亲的鞋码小了半号——有人在他之后下过楼。", at: "第 9 章 · 段 21" },
    { id: "h4", label: "守住承诺", text: "「No.31」核心谜面持续悬置", tone: "sage",
      evidence: "她把盐钟扣回掌心。No.31，到底是哪一格抽屉的号码？", at: "第 9 章 · 段 27" },
    { id: "h5", label: "统一设定", text: "周岚 · 身份 = 档案学院督察", tone: "sage",
      evidence: "周岚亮出督察证件时，林岑瞥见她指节上一道旧疤。", at: "第 9 章 · 段 13" },
    { id: "h6", label: "本章张力", text: "命中目标张力 0.66 ≥ 0.64", tone: "sage",
      evidence: "节奏在脚印发现处收紧，章末留下未开的抽屉。", at: "全章" },
  ],
  drifted: [
    { id: "d1", label: "AI 漂移", tone: "rose", sev: "high",
      what: "周岚办公室位置前后不一", detail: "第 9 章写「三楼档案室」，与第 6 章已确立的「地下档案室」冲突。",
      line: "她跟着周岚走进三楼档案室，铁柜在顶灯下泛着冷光。", at: "第 9 章 · 段 12",
      fixes: ["统一为地下档案室（以第 6 章为准）", "钉入下一轮交接复核"] },
    { id: "d2", label: "人物弧停滞", tone: "gold", sev: "medium",
      what: "阿恪仍未获成长点", detail: "交接要求给阿恪一个成长动作，本章他仅以一通电话出场，自第 6 章起仍是平线。",
      line: "「证物我看过了，没问题。」阿恪在电话那头说，挂了。", at: "第 9 章 · 段 18",
      fixes: ["第 10 章给阿恪一次选择 / 代价", "保留并钉入下一轮"] },
  ],
  introduced: [
    { id: "n1", kind: "新地点", tone: "rose", text: "三楼档案室", note: "与第 6 章「地下档案室」冲突——即上方漂移的来源。",
      actions: ["归并入设定锚点（待统一）"] },
    { id: "n2", kind: "新承诺", tone: "gold", text: "档案箱里的一张旧照片", note: "林岑翻出一张未加说明的旧照片——新悬念，尚未排定回收章。",
      actions: ["送入下一轮交接 · 排期回收"] },
    { id: "n3", kind: "新设定", tone: "slate", text: "父亲工牌编号 = A-7", note: "本章首次出现的既定事实，建议锁定以防后文漂移。",
      actions: ["锁定为设定锚点"] },
  ],
};

/* ========== 派生 ========== */

/* 统一战情板：在 LF2 六类之上，新增 空降 / 断链 / 不公平 三类 */
function lf3Issues(d, loops, canon) {
  const out = [];
  const now = d.now;
  // 1) AI 漂移（最高优先）
  canon.filter(c => c.status === "conflict").forEach(c => out.push({
    id: "conf-" + c.id, fam: "drift", kind: "conflict", tone: c.drift ? "rose" : "gold",
    icon: c.drift ? "Cpu" : "AlertTriangle", label: c.drift ? "AI 漂移" : "连续性冲突",
    title: c.conflictText || `${c.subject} 前后不一`,
    meta: `第 ${c.conflictCh} 章引入${c.fresh ? " · 本轮新发现" : " · 待统一锁定"}`,
    sev: c.drift ? "high" : "medium", action: "统一并锁定", ref: { type: "canon", id: c.id } }));
  // 2) 悬念逾期
  d.overdue.forEach(l => out.push({
    id: "od-" + l.id, fam: "overdue", kind: "overdue", tone: "rose", icon: "Clock", label: "悬念逾期",
    title: l.title, meta: `第 ${l.setup} 章埋设 · 计划第 ${l.payoff} 章回收 · 已越过现在`, sev: "high",
    action: "钉入交接", ref: { type: "loop", id: l.id } }));
  // 3) 空降回收（NEW）
  LF3_ORPHANS.forEach(o => out.push({
    id: "orph-" + o.id, fam: "orphan", kind: "orphan", tone: "crimson", icon: "Zap", label: "空降回收",
    title: o.reveal, meta: `第 ${o.revealCh} 章揭示 · 全书无铺垫`, sev: o.sev,
    action: "去补铺垫", ref: { type: "orphan", id: o.id } }));
  // 4) 因果断链（NEW）
  LF3_CAUSAL.filter(k => k.status === "break").forEach(k => out.push({
    id: "caus-" + k.id, fam: "causal", kind: "causal", tone: "rose", icon: "GitBranch", label: "因果断链",
    title: `${k.effect}（缺前因）`, meta: `承重事件 · 第 ${k.effectCh} 章悬空`, sev: "high",
    action: "去补前因", ref: { type: "causal", id: k.id } }));
  // 5) 不公平揭晓（NEW）
  LF3_CLUES.filter(c => !c.fair && !c.pending).forEach(c => out.push({
    id: "fair-" + c.id, fam: "fair", kind: "fair", tone: "gold", icon: "Eye", label: "线索不公平",
    title: c.q, meta: c.reveal ? `计划第 ${c.reveal} 章揭晓 · 尚无可推理线索` : "未铺设可推理线索", sev: "medium",
    action: "去埋线索", ref: { type: "clue", id: c.id } }));
  // 5b) 结构 / 时序 连续性提示（非设定类）
  LF2_RISKS.filter(r => !r.canon && !r.drift).forEach(r => out.push({
    id: "cont-" + r.id, fam: "continuity", kind: "continuity", tone: "slate", icon: "ShieldCheck", label: "连续性提示",
    title: r.text, meta: `第 ${r.ch} 章 · ${r.type}`, sev: r.sev,
    action: "查看", ref: { type: "risk", id: r.id } }));
  // 6) 线索停滞
  d.stalledThreads.forEach(t => out.push({
    id: "stall-" + t.id, fam: "stall", kind: "stall", tone: "gold", icon: "GitBranch", label: "线索停滞",
    title: t.name, meta: `已 ${now - lf2ThreadLast(t)} 章未推进`, sev: "medium",
    action: "钉入交接", ref: { type: "thread", id: t.id } }));
  // 7) 张力泄气
  LF2_CHAPTERS.filter(c => !c.planned && c.pace < LF2_TARGET[c.n - 1] - 0.05).forEach(c => out.push({
    id: "dip-" + c.n, fam: "dip", kind: "dip", tone: "slate", icon: "Activity", label: "张力泄气",
    title: `第 ${c.n} 章实际张力 ${c.pace.toFixed(2)}，低于目标 ${LF2_TARGET[c.n - 1].toFixed(2)}`,
    meta: "中段最易泄气 · 影响下一章基准", sev: "low", action: "设为目标", ref: { type: "chapter", id: c.n } }));
  // 8) 人物弧停滞
  d.arcStalled.forEach(a => out.push({
    id: "arc-" + a.name, fam: "arc", kind: "arc", tone: "slate", icon: "Users", label: "人物弧停滞",
    title: `${a.name} ${a.state}`, meta: "角色停止成长，读者会失去投入", sev: "low",
    action: "查看", ref: { type: "arc", id: a.name } }));
  const rank = { high: 0, medium: 1, low: 2 };
  return out.sort((a, b) => rank[a.sev] - rank[b.sev]);
}

/* 交接简报（含记忆预算）：每条带 token 成本 + 模式（enforce 强约束 / retrieve 可检索）。
   modes = { [id]: 'enforce' | 'retrieve' } 覆盖默认。 */
function lf3Brief(loops, canon, modes) {
  const now = LF2_BOOK.now, next = LF2_NEXT;
  const d = lf2Derive(loops, canon);
  const m = modes || {};
  const strata = [];
  const push = (key, title, icon, items) => { if (items.length) strata.push({ key, title, icon, items }); };

  push("canon", "设定锚点 · 不可矛盾", "Lock",
    canon.filter(c => c.pinned || c.status === "conflict").map(c => ({
      id: "ho-" + c.id, tone: c.status === "conflict" ? "rose" : "crimson",
      label: c.status === "conflict" ? "统一设定" : "锁定设定",
      text: `${c.subject} = ${c.value}` + (c.status === "conflict" ? `（修正第 ${c.conflictCh} 章漂移）` : ""),
      source: `第 ${c.source} 章确立`, cost: c.status === "conflict" ? LF3_COST.conflict : LF3_COST.canon,
      lock: c.status === "conflict" || c.critical })));

  const promises = [...d.overdue, ...d.pinned.filter(l => l.payoff != null && l.payoff >= now && l.payoff - now <= 4 && !d.overdue.includes(l))];
  push("promise", "到期承诺 · 必须回收", "Clock",
    promises.map(l => ({
      id: "ho-" + l.id, tone: l.payoff < now ? "rose" : "gold",
      label: l.payoff < now ? "逾期回收" : "守住承诺", text: l.title,
      source: l.payoff < now ? `第 ${l.setup} 章埋设 · 已逾期` : `计划第 ${l.payoff} 章前回收`,
      cost: LF3_COST.overdue, lock: l.payoff < now })));

  push("thread", "待推进 · 别让线索断更", "GitBranch",
    d.stalledThreads.map(t => ({
      id: "ho-" + t.id, tone: "gold", label: "推进线索",
      text: t.name, source: `已 ${now - lf2ThreadLast(t)} 章未触及`, cost: LF3_COST.thread })));

  strata.push({ key: "tension", title: "张力目标 · 别泄气", icon: "Activity", items: [{
    id: "ho-tension", tone: "slate", label: "本章张力",
    text: `第 ${next} 章目标张力 ${LF2_TARGET[next - 1].toFixed(2)}`, source: "承上启下 · 维持悬置", cost: LF3_COST.tension, soft: true }] });

  push("arc", "人物状态 · 进入本章", "Users",
    LF2_ARCS.map(a => ({
      id: "ho-arc-" + a.name, tone: a.stalledFrom ? "rose" : "slate",
      label: a.stalledFrom ? "需给成长点" : "保持弧线",
      text: `${a.name} · ${a.state}`, source: a.role, cost: LF3_COST.arc, lock: !!a.stalledFrom, soft: !a.stalledFrom })));

  // 默认模式：lock 强制 enforce；soft（张力 / 健康人物弧）默认下放可检索池；其余默认 enforce
  const all = strata.flatMap(s => s.items);
  all.forEach(it => { it.mode = m[it.id] || (it.lock ? "enforce" : (it.soft ? "retrieve" : "enforce")); });
  const enforce = all.filter(it => it.mode === "enforce");
  const retrieve = all.filter(it => it.mode === "retrieve");
  const used = enforce.reduce((a, it) => a + it.cost, 0);
  return { next, strata, all, enforce, retrieve, used, cap: LF3_BUDGET_CAP, over: used > LF3_BUDGET_CAP };
}

Object.assign(window, {
  LF3_BUDGET_CAP, LF3_TITLE, LF3_ORPHANS, LF3_CAUSAL, LF3_CLUES, LF3_RETRIEVE, LF3_COST, LF3_AUDIT,
  lf3Issues, lf3Brief,
});
