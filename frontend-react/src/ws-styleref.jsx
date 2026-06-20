import React from "react";
import { I } from "./icons.jsx";
import { WsDemoTag } from "./ws-catalog.jsx";
import { WsWorks } from "./ws-works.jsx";
import { rvPush } from "./ws-review.jsx";

/* global React, I */
const { useState: useStSR } = React;

/* ==========================================================
   风格参考 — Style Reference Module
   Pipeline: 书库 → 维度矩阵(抽取) → 风格画像 → 注入应用
   Signature: 4 层 × 16 sub-dim DimensionMatrix
   ========================================================== */

/* ---- 4 layers × 4 sub-dims = 16 sub-dimensions ---- */
const SR_LAYERS = [
  {
    id: "language", name: "语言层", abbr: "语", input: "high",
    subs: [
      { id: "sentence_structure", name: "句式结构", conf: "high",   obs: 7, fp: 2, q: 18 },
      { id: "vocabulary",         name: "词汇选择", conf: "high",   obs: 6, fp: 1, q: 15 },
      { id: "rhetoric",           name: "修辞手法", conf: "medium", obs: 4, fp: 3, q: 11 },
      { id: "punctuation",        name: "标点节奏", conf: "high",   obs: 5, fp: 0, q: 9  },
    ],
  },
  {
    id: "narrative", name: "叙事层", abbr: "叙", input: "medium",
    subs: [
      { id: "perspective",         name: "叙事视角", conf: "high",   obs: 5, fp: 1, q: 12 },
      { id: "pacing",              name: "节奏控制", conf: "medium", obs: 4, fp: 2, q: 8  },
      { id: "time_handling",       name: "时间处理", conf: "medium", obs: 3, fp: 1, q: 7  },
      { id: "information_density", name: "信息密度", conf: "low",    obs: 2, fp: 0, q: 4  },
    ],
  },
  {
    id: "scene", name: "场景层", abbr: "景", input: "high",
    subs: [
      { id: "environment",        name: "环境描写", conf: "high",   obs: 6, fp: 1, q: 14 },
      { id: "character_portrayal",name: "人物刻画", conf: "high",   obs: 5, fp: 2, q: 13 },
      { id: "dialogue",           name: "对话写法", conf: "medium", obs: 4, fp: 1, q: 10 },
      { id: "sensory_priority",   name: "感官优先", conf: "medium", obs: 3, fp: 0, q: 6  },
    ],
  },
  {
    id: "theme", name: "主题层", abbr: "题", input: "skip",
    subs: [
      { id: "emotional_tone",      name: "情感基调", conf: "skip", obs: 0, fp: 0, q: 0 },
      { id: "values",              name: "价值取向", conf: "skip", obs: 0, fp: 0, q: 0 },
      { id: "motifs",              name: "母题意象", conf: "skip", obs: 0, fp: 0, q: 0 },
      { id: "narrative_philosophy",name: "叙事哲学", conf: "skip", obs: 0, fp: 0, q: 0 },
    ],
  },
];

/* ---- findings for a couple of sub-dims (rich), with evidence ---- */
const SR_FINDINGS = {
  "language.sentence_structure": {
    observations: [
      { id: "o1", conf: "high", statement: "以短句为主，常用单句独立成段，制造冷峻停顿。", evidence: [
        { p: "P-142", quote: "我到现在终于没有见——大约孔乙己的确死了。", dims: ["language.sentence_structure", "theme.emotional_tone"] },
        { p: "P-088", quote: "然而我的母亲虽然高兴，也藏着许多凄凉的神情。", dims: ["language.sentence_structure"] },
      ]},
      { id: "o2", conf: "high", statement: "并列短句之间多用逗号顿连，少用关联词，节奏靠停顿而非连接词推进。", evidence: [
        { p: "P-051", quote: "他不回答，对柜里说，温两碗酒，要一碟茴香豆。", dims: ["language.sentence_structure", "scene.dialogue"] },
        { p: "P-203", quote: "苍黄的天底下，远近横着几个萧索的荒村，没有一些活气。", dims: ["language.sentence_structure", "scene.environment"] },
      ]},
      { id: "o3", conf: "medium", statement: "偶用长句铺陈，但长句内部仍以短促分句切分，不堆砌从句。", evidence: [
        { p: "P-019", quote: "这是鲁镇的习惯，本家和朋友们家里有事，便须用钱去雇人来做。", dims: ["language.sentence_structure"] },
        { p: "P-167", quote: "我冒了严寒，回到相隔二千余里，别了二十余年的故乡去。", dims: ["language.sentence_structure"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f1", statement: "作者从不使用排比堆叠的华丽长句来抒情。", evidence: [
        { kind: "author_avoidance", note: "全文 sentence_length_std=12.1，长句率仅 6%，且无连续三句以上排比。" },
        { kind: "counter_example", synthetic: true, quote: "（反例）天是那样蓝，云是那样白，风是那样柔，心是那样静……", note: "此类抒情排比与原作冷峻克制完全相悖。" },
      ]},
      { id: "f2", statement: "作者从不在对话后追加大段情绪解释。", evidence: [
        { kind: "paragraph_quote", p: "P-051", quote: "他不回答，对柜里说，温两碗酒。", note: "对话后直接接动作，不解释心理。" },
        { kind: "author_avoidance", note: "dialogue 段后接 psychology 段的比例仅 4%，远低于通俗小说。" },
      ]},
    ],
  },
  "language.rhetoric": {
    observations: [
      { id: "o4", conf: "medium", statement: "比喻克制、具象，多取自乡土与日常器物，避免抽象修饰。", evidence: [
        { p: "P-210", quote: "圆规一面愤愤的回转身，一面絮絮的说，慢慢向外走。", dims: ["language.rhetoric", "scene.character_portrayal"] },
        { p: "P-233", quote: "他的脸色却变作灰黄，仿佛石像一般。", dims: ["language.rhetoric"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f3", statement: "作者从不使用「眼睛像星星」式陈词滥调比喻。", evidence: [
        { kind: "author_avoidance", note: "metaphor_density 不低，但 cliché 比喻命中为 0。" },
        { kind: "counter_example", synthetic: true, quote: "（反例）她的眼睛像夜空中最亮的星。", note: "陈词滥调，与原作具象取喻习惯相悖。" },
      ]},
      { id: "f4", statement: "作者从不在比喻后追加解释性句子。", evidence: [
        { kind: "paragraph_quote", p: "P-233", quote: "他的脸色却变作灰黄，仿佛石像一般。", note: "喻体之后直接收束，不解释。" },
        { kind: "author_avoidance", note: "比喻句后接「这说明…」「仿佛在告诉…」类解释句为 0。" },
      ]},
    ],
  },
  "language.vocabulary": {
    observations: [
      { id: "o5", conf: "high", statement: "白话为底，少量文言虚词（之、乎、者）点染，形成半文半白的克制语感。", evidence: [
        { p: "P-007", quote: "孔乙己是站着喝酒而穿长衫的唯一的人。", dims: ["language.vocabulary"] },
        { p: "P-061", quote: "多乎哉？不多也。", dims: ["language.vocabulary", "scene.dialogue"] },
      ]},
      { id: "o6", conf: "high", statement: "名词偏向具体器物与乡土事物，抽象名词使用率低。", evidence: [
        { p: "P-044", quote: "温两碗酒，要一碟茴香豆。", dims: ["language.vocabulary"] },
        { p: "P-219", quote: "深蓝的天空中挂着一轮金黄的圆月，下面是海边的沙地。", dims: ["language.vocabulary", "scene.environment"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f5", statement: "作者从不堆砌情绪形容词来替代描写。", evidence: [
        { kind: "author_avoidance", note: "「悲痛欲绝/震撼人心」类成语命中为 0；情绪靠动作与白描呈现。" },
        { kind: "counter_example", synthetic: true, quote: "（反例）他悲痛欲绝，心如刀绞，泪如雨下。", note: "成语连缀抒情与原作相悖。" },
      ]},
    ],
  },
  "language.punctuation": {
    observations: [
      { id: "o9", conf: "high", statement: "破折号用于语气延宕与冷峻收束，常落在段末制造停顿。", evidence: [
        { p: "P-142", quote: "我到现在终于没有见——大约孔乙己的确死了。", dims: ["language.punctuation"] },
        { p: "P-198", quote: "然而圆规很不平，显出鄙夷的神色——仿佛嗤笑法国人不知道拿破仑。", dims: ["language.punctuation", "language.rhetoric"] },
      ]},
      { id: "o10", conf: "medium", statement: "问号多为反诘，不为求答，强化叙述者的冷眼。", evidence: [
        { p: "P-061", quote: "不多不多！多乎哉？不多也。", dims: ["language.punctuation"] },
      ]},
    ],
    forbidden_patterns: [],
  },
  "narrative.perspective": {
    observations: [
      { id: "o11", conf: "high", statement: "多用限知的第一人称「我」，与事件保持冷静、略带愧疚的距离。", evidence: [
        { p: "P-003", quote: "我那时年纪小，只当作一种好玩的事看。", dims: ["narrative.perspective"] },
        { p: "P-188", quote: "我也还记得，但是模糊了，仿佛一幅画。", dims: ["narrative.perspective", "narrative.time_handling"] },
      ]},
      { id: "o12", conf: "high", statement: "叙述者既是见证者也是反思者，事后追忆的口吻贯穿全篇。", evidence: [
        { p: "P-002", quote: "这是二十多年前的事，现在想来，倒已有些模糊。", dims: ["narrative.perspective"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f6", statement: "作者从不切换为全知视角直接剖白人物内心。", evidence: [
        { kind: "author_avoidance", note: "人物心理一律由外部动作与「我」的推测呈现，无上帝视角内心独白。" },
      ]},
    ],
  },
  "narrative.pacing": {
    observations: [
      { id: "o13", conf: "medium", statement: "以场景白描推进，关键转折处反而放慢、留白。", evidence: [
        { p: "P-140", quote: "中秋过后，秋风是一天凉比一天，看看将近初冬。", dims: ["narrative.pacing", "narrative.time_handling"] },
        { p: "P-145", quote: "他从破衣袋里摸出四文大钱，放在我手里。", dims: ["narrative.pacing"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f7", statement: "作者从不用悬念钩子强行加速章节结尾。", evidence: [
        { kind: "author_avoidance", note: "段末多为静景或动作收束，无「欲知后事如何」式悬念。" },
      ]},
    ],
  },
  "narrative.time_handling": {
    observations: [
      { id: "o14", conf: "medium", statement: "时间靠节气与季节标记，以追忆框架嵌套当下。", evidence: [
        { p: "P-140", quote: "中秋过后，秋风是一天凉比一天。", dims: ["narrative.time_handling"] },
        { p: "P-002", quote: "这是二十多年前的事。", dims: ["narrative.time_handling", "narrative.perspective"] },
      ]},
    ],
    forbidden_patterns: [],
  },
  "narrative.information_density": {
    observations: [
      { id: "o15", conf: "low", statement: "信息密度偏低，靠重复细节累积印象而非一次性交代。", evidence: [
        { p: "P-007", quote: "孔乙己是站着喝酒而穿长衫的唯一的人。", dims: ["narrative.information_density"] },
      ]},
    ],
    forbidden_patterns: [],
  },
  "scene.environment": {
    observations: [
      { id: "o16", conf: "high", statement: "环境白描冷色调为主，以萧索荒凉烘托人物处境。", evidence: [
        { p: "P-203", quote: "苍黄的天底下，远近横着几个萧索的荒村，没有一些活气。", dims: ["scene.environment"] },
        { p: "P-219", quote: "深蓝的天空中挂着一轮金黄的圆月，下面是海边的沙地。", dims: ["scene.environment", "scene.sensory_priority"] },
      ]},
      { id: "o17", conf: "high", statement: "环境描写极简，几笔勾勒即收，不作长段铺陈。", evidence: [
        { p: "P-040", quote: "鲁镇的酒店的格局，是和别处不同的。", dims: ["scene.environment"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f8", statement: "作者从不用唯美辞藻堆叠风景。", evidence: [
        { kind: "author_avoidance", note: "环境段平均句长 14 字，形容词密度低，无「美轮美奂」式渲染。" },
      ]},
    ],
  },
  "scene.character_portrayal": {
    observations: [
      { id: "o18", conf: "high", statement: "人物以标志性动作与外貌细节定型，反复出现强化印象。", evidence: [
        { p: "P-045", quote: "孔乙己一到店，所有喝酒的人便都看着他笑。", dims: ["scene.character_portrayal"] },
        { p: "P-210", quote: "圆规一面愤愤的回转身，一面絮絮的说。", dims: ["scene.character_portrayal", "language.rhetoric"] },
      ]},
      { id: "o19", conf: "medium", statement: "用绰号与外号代称人物，带阶层与反讽意味。", evidence: [
        { p: "P-209", quote: "人都叫伊「豆腐西施」。", dims: ["scene.character_portrayal"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f9", statement: "作者从不为人物写「完美无瑕」的理想化外貌。", evidence: [
        { kind: "author_avoidance", note: "外貌描写均带缺陷或衰败细节，无理想化美化。" },
      ]},
    ],
  },
  "scene.dialogue": {
    observations: [
      { id: "o20", conf: "medium", statement: "对话简短、口语化，常以一句定人物身份与处境。", evidence: [
        { p: "P-061", quote: "「不多不多！多乎哉？不多也。」", dims: ["scene.dialogue", "language.vocabulary"] },
        { p: "P-052", quote: "「温一碗酒。」", dims: ["scene.dialogue"] },
      ]},
    ],
    forbidden_patterns: [
      { id: "f10", statement: "作者从不在对话中夹带大段说明性独白。", evidence: [
        { kind: "author_avoidance", note: "单句对话占比 78%，无超过三句的连续独白。" },
      ]},
    ],
  },
  "scene.sensory_priority": {
    observations: [
      { id: "o21", conf: "medium", statement: "感官以视觉为主，辅以少量触觉（寒冷），听觉嗅觉克制。", evidence: [
        { p: "P-219", quote: "深蓝的天空中挂着一轮金黄的圆月。", dims: ["scene.sensory_priority"] },
        { p: "P-167", quote: "我冒了严寒，回到相隔二千余里的故乡去。", dims: ["scene.sensory_priority"] },
      ]},
    ],
    forbidden_patterns: [],
  },
};

/* ---- hard metrics (sample, 鲁迅) ---- */
const SR_METRICS = [
  { name: "平均句长",      key: "avg_sentence_length",     mean: 16.8, std: 11.2, unit: "字" },
  { name: "句长标准差",    key: "sentence_length_std",     mean: 11.2, std: 3.1,  unit: "" },
  { name: "短句率(≤10)",   key: "short_sentence_ratio",    mean: 0.41, std: 0.09, unit: "", pct: true },
  { name: "对话占比",      key: "dialogue_ratio",          mean: 0.23, std: 0.07, unit: "", pct: true },
  { name: "比喻密度/千字", key: "metaphor_density_per_1k", mean: 3.2,  std: 1.8,  unit: "" },
  { name: "文言词比率",    key: "classical_word_ratio",    mean: 0.14, std: 0.05, unit: "", pct: true },
  { name: "视觉感官/千字", key: "sensory_visual_per_1k",   mean: 8.1,  std: 2.6,  unit: "" },
  { name: "破折号密度/千", key: "dash_em_density_per_1k",  mean: 2.4,  std: 1.1,  unit: "" },
];

const SR_PARA_DIST = [
  { type: "叙述", key: "narration", v: 0.34 },
  { type: "对话", key: "dialogue", v: 0.23 },
  { type: "环境", key: "description_env", v: 0.14 },
  { type: "心理", key: "psychology", v: 0.11 },
  { type: "动作", key: "action", v: 0.09 },
  { type: "人物", key: "description_char", v: 0.06 },
  { type: "转场", key: "transition", v: 0.03 },
];

/* ---- books ---- */
let SR_BOOKS = [
  { id: "b1", title: "呐喊 · 短篇集", author: "鲁迅", chars: 81200, status: "ready",   profiles: 1, run: "16/16 抽取完成", color: "crimson" },
  { id: "b2", title: "断魂枪 · 月牙儿", author: "老舍", chars: 52400, status: "extracting", profiles: 0, run: "11/16 抽取中", color: "gold" },
  { id: "b3", title: "边城（节选）", author: "沈从文", chars: 30100, status: "ready",   profiles: 1, run: "12/16（题材层语料不足）", color: "slate" },
  { id: "b4", title: "荷塘月色 · 背影", author: "朱自清", chars: 18600, status: "pending", profiles: 0, run: "排队中", color: "sage" },
];

const SR_STAGES = [
  { id: "overview",   name: "概览",     icon: "Activity" },
  { id: "matrix",     name: "维度矩阵", icon: "Grid" },
  { id: "profile",    name: "风格画像", icon: "Sparkles" },
  { id: "validation", name: "回测校验", icon: "Flask" },
  { id: "apply",      name: "注入应用", icon: "Sliders" },
];

/* ---- per-subdim metric anchor (for matrix hover tooltip) ---- */
const SR_SUBDIM_TIP = {
  "language.sentence_structure": { metric: "平均句长 16.8 字 · 短句率 41%", sample: "我到现在终于没有见——大约孔乙己的确死了。" },
  "language.vocabulary":         { metric: "文言词比率 14% · 抽象名词率 9%", sample: "孔乙己是站着喝酒而穿长衫的唯一的人。" },
  "language.rhetoric":           { metric: "比喻密度 3.2/千 · cliché 命中 0", sample: "他的脸色却变作灰黄，仿佛石像一般。" },
  "language.punctuation":        { metric: "破折号 2.4/千 · 反诘问号占 71%", sample: "不多不多！多乎哉？不多也。" },
  "narrative.perspective":       { metric: "第一人称 92% · 限知视角", sample: "我那时年纪小，只当作一种好玩的事看。" },
  "narrative.pacing":            { metric: "场景/概述比 2.3 · 转折留白", sample: "中秋过后，秋风是一天凉比一天。" },
  "narrative.time_handling":     { metric: "追忆框架 · 节气标记 5 处", sample: "这是二十多年前的事。" },
  "narrative.information_density":{ metric: "信息密度偏低 · 重复累积", sample: "孔乙己是站着喝酒而穿长衫的唯一的人。" },
  "scene.environment":           { metric: "环境段均长 14 字 · 冷色调", sample: "苍黄的天底下，远近横着几个萧索的荒村。" },
  "scene.character_portrayal":   { metric: "标志动作复现 · 绰号代称", sample: "圆规一面愤愤的回转身，一面絮絮的说。" },
  "scene.dialogue":              { metric: "单句对话 78% · 口语化", sample: "「温一碗酒。」" },
  "scene.sensory_priority":      { metric: "视觉 8.1/千 · 触觉 2.1/千", sample: "深蓝的天空中挂着一轮金黄的圆月。" },
};

/* ---- extraction cost / coverage trend (last 14 runs) ---- */
const SR_TREND = [3, 5, 4, 8, 6, 9, 12, 10, 14, 11, 13, 16, 12, 16];

/* ==========================================================
   深层页真后端：hook + 真实数据映射器
   有真书(book.real)→ 懒加载并订阅 sr:deep-changed；映射器把
   stats_json / findings 映成各 stage 需要的形状，缺数据返 null → 调用方回退演示。
   ========================================================== */
function useSrDeep(book) {
  const isReal = !!(book && book.real);
  const [deep, setDeep] = React.useState(() => (isReal && window.srDeepFor ? window.srDeepFor(book.id) : null));
  React.useEffect(() => {
    if (!isReal) { setDeep(null); return; }
    const sync = () => setDeep(window.srDeepFor ? window.srDeepFor(book.id) : null);
    sync();
    if (window.srLoadDeep) window.srLoadDeep(book.id);
    window.addEventListener("sr:deep-changed", sync);
    return () => window.removeEventListener("sr:deep-changed", sync);
  }, [isReal, book && book.id]);
  return deep;
}

const SR_PARA_LABEL = {
  narration: "叙述", dialogue: "对话", description_env: "环境", psychology: "心理",
  action: "动作", description_char: "人物", transition: "转场", flashback: "闪回",
};
const SR_INPUT_LABEL = { skip: "语料不足", low: "偏少", medium: "适中", high: "充足" };

function srStatsOf(deep) { return (deep && deep.book && deep.book.stats_json) || null; }

/* stats_json.metrics（26 项）按 SR_METRICS 的展示名/单位取真实 mean/std；缺项跳过 */
function srRealMetrics(stats) {
  const m = (stats && stats.metrics) || {};
  return SR_METRICS.map(d => {
    const real = m[d.key];
    if (!real || real.mean == null) return null;
    return { ...d, mean: Number(real.mean), std: Number(real.std) };
  }).filter(Boolean);
}

/* stats_json.paragraph_type_distribution → [{type,key,v}]（降序） */
function srRealParaDist(stats) {
  const dist = (stats && stats.paragraph_type_distribution) || {};
  return Object.entries(dist)
    .map(([key, v]) => ({ type: SR_PARA_LABEL[key] || key, key, v: Number(v) || 0 }))
    .sort((a, b) => b.v - a.v);
}

function WsStyleRef({ go }) {
  const [bookId, setBookId] = useStSR("b1");
  const [stage, setStage] = useStSR("matrix");
  const [headerBusy, setHeaderBusy] = useStSR(null);
  const [delBusy, setDelBusy] = useStSR(null);
  const book = SR_BOOKS.find(b => b.id === bookId) || SR_BOOKS[0];

  /* FE-ALIGN F5 授权接缝：书库由后端背书，变化时重渲染 */
  const [, setSrPing] = useStSR(0);
  React.useEffect(() => {
    const f = () => setSrPing(p => p + 1);
    window.addEventListener("sr:books-changed", f);
    return () => window.removeEventListener("sr:books-changed", f);
  }, []);

  const busyRef = React.useRef(null);
  const runHeaderAction = (id) => {
    if (headerBusy) return;
    setHeaderBusy(id);
    /* 真实书走后端动作（LLM 未启用时弹明确引导）；演示书保留原模拟节奏 */
    if (book && book.real && window.srBookAction) {
      window.srBookAction(id, book.id).finally(() => setHeaderBusy(null));
      return;
    }
    clearTimeout(busyRef.current);
    busyRef.current = setTimeout(() => setHeaderBusy(null), 1400);
  };
  React.useEffect(() => () => clearTimeout(busyRef.current), []);

  /* 删除参考书（仅真实书）：confirm → DELETE 端点（级联清除全部衍生数据）→ 刷新书库。
     删的若是当前选中书，切到刷新后剩余的第一本（srDeleteBook 内部已 srSyncBooks 重置 SR_BOOKS；
     删光最后一本时书库回落演示书，next 即演示书首项）。 */
  const onDeleteBook = async (b) => {
    if (delBusy || !b || !window.srDeleteBook) return;
    const ok = window.confirm(
      `确认删除参考书《${b.title}》？\n\n` +
      "将一并清除它的全部衍生数据（抽取 findings、证据引文、风格画像、注入绑定、回测报告），此操作不可恢复。"
    );
    if (!ok) return;
    // 删的若是当前选中书，删后切到原位置的邻居（srDeleteBook 内部已 srSyncBooks 重置 SR_BOOKS）。
    const wasActive = bookId === b.id;
    const idx = SR_BOOKS.findIndex(x => x.id === b.id);
    setDelBusy(b.id);
    try {
      await window.srDeleteBook(b.id);
      if (wasActive && SR_BOOKS.length) {
        const next = SR_BOOKS[Math.min(Math.max(idx, 0), SR_BOOKS.length - 1)];
        if (next) setBookId(next.id);
      }
    } catch (e) {
      window.alert("删除失败：" + ((e && e.message) || e));
    } finally {
      setDelBusy(null);
    }
  };

  return (
    <div className="sr-page" data-screen-label="styleref">
      <div className="sr-cols">
        {/* Left: books */}
        <aside className="sr-books">
          <header className="sr-books-head">
            <div>
              <div className="page-eyebrow" style={{margin:0, display:"flex", alignItems:"center", gap:8}}>风格参考 {WsDemoTag && <WsDemoTag note="书库/导入/删除/抽取启动已接后端 style-reference v2（LLM 未启用时启动抽取会给明确引导）。维度矩阵/画像/回测/注入展示的是 LLM 抽取产物，启用前为演示数据。" />}</div>
              <h2 className="text-serif" style={{fontSize:18, margin:"4px 0 0"}}>参考书库</h2>
            </div>
            <button className="btn btn-accent btn-sm" onClick={() => window.srImportBook && window.srImportBook()}><I.Plus size={13} /></button>
          </header>

          <ul className="sr-book-list">
            {SR_BOOKS.map(b => (
              <li key={b.id} className="sr-book-item">
                <button className={`sr-book ${bookId === b.id ? "is-active" : ""}`} onClick={() => setBookId(b.id)}>
                  <span className={`sr-book-spine spine-${b.color}`} />
                  <span className="sr-book-body">
                    <span className="sr-book-title text-serif">{b.title}</span>
                    <span className="sr-book-author">{b.author} · {(b.chars/10000).toFixed(1)} 万字</span>
                    <span className="sr-book-run">{b.run}</span>
                  </span>
                  <SrBookState s={b.status} />
                </button>
                {b.real && (
                  <button
                    type="button"
                    className={`sr-book-del${delBusy === b.id ? " is-busy" : ""}`}
                    data-sr-del={b.id}
                    title="删除这本参考书"
                    aria-label={`删除参考书《${b.title}》`}
                    disabled={!!delBusy}
                    onClick={() => onDeleteBook(b)}
                  >
                    {delBusy === b.id
                      ? <span className="sr-spin" style={{ display: "inline-flex" }}><I.Refresh size={13} /></span>
                      : <I.Trash size={13} />}
                  </button>
                )}
              </li>
            ))}
          </ul>

          <div className="sr-books-import" style={{ cursor: "pointer" }} onClick={() => window.srImportBook && window.srImportBook()}>
            <I.FileInput size={16} />
            <div>
              <div className="fw-600 text-sm">导入参考书</div>
              <div className="text-xs text-muted">epub · docx · txt · md</div>
            </div>
          </div>
          <p className="sr-safe-note">
            <I.ShieldCheck size={12} />
            <span>只学习抽象风格画像，不复刻原文表达、人物或桥段。</span>
          </p>
        </aside>

        {/* Right: stage workspace */}
        <section className="sr-stage">
          <header className="sr-stage-head">
            <div className="flex items-center gap-3">
              <div className={`sr-stage-mark spine-${book.color}`}>{book.author[0]}</div>
              <div>
                <h1 className="sr-stage-title text-serif">{book.title}</h1>
                <div className="text-muted text-sm">{book.author} · {book.chars.toLocaleString()} 字 · {book.run}</div>
              </div>
            </div>
            <div className="flex gap-2 items-center">
              <button className="btn btn-quiet btn-sm" disabled={!!headerBusy} onClick={() => runHeaderAction("reclassify")}>
                <span className={headerBusy === "reclassify" ? "sr-spin" : ""} style={{ display: "inline-flex" }}><I.Refresh size={13} /></span> {headerBusy === "reclassify" ? "重新分类中…" : "重新分类"}
              </button>
              <button className="btn btn-ghost btn-sm" disabled={!!headerBusy} onClick={() => runHeaderAction("rerun")}>
                {headerBusy === "rerun" ? <><span className="sr-spin" style={{ display: "inline-flex" }}><I.Refresh size={13} /></span> 重跑抽取中…</> : "重跑抽取"}
              </button>
            </div>
          </header>

          <nav className="sr-stepper" aria-label="风格参考流水线">
            {SR_STAGES.map((s, i) => {
              const Ic = I[s.icon] || I.Dot;
              const active = stage === s.id;
              const idx = SR_STAGES.findIndex(x => x.id === stage);
              const done = i < idx;
              return (
                <React.Fragment key={s.id}>
                  {i > 0 && <span className={`sr-step-line ${i <= idx ? "is-done" : ""}`} aria-hidden="true" />}
                  <button
                    className={`sr-step ${active ? "is-active" : ""} ${done ? "is-done" : ""}`}
                    onClick={() => setStage(s.id)}
                    aria-current={active ? "step" : undefined}
                  >
                    <span className="sr-step-mark">
                      {done ? <I.Check size={14} /> : <Ic size={15} />}
                    </span>
                    <span className="sr-step-text">
                      <span className="sr-step-idx">0{i + 1}</span>
                      <span className="sr-step-name">{s.name}</span>
                    </span>
                  </button>
                </React.Fragment>
              );
            })}
          </nav>

          <div className="sr-stage-body">
            {stage === "overview"   && <SrOverview book={book} go={setStage} />}
            {stage === "matrix"     && <SrMatrix go={setStage} book={book} />}
            {stage === "profile"    && <SrProfile book={book} go={setStage} />}
            {stage === "validation" && <window.SrValidation book={book} go={setStage} />}
            {stage === "apply"      && <SrApply go={setStage} book={book} />}
          </div>
        </section>
      </div>

      <style dangerouslySetInnerHTML={{ __html: srCss }} />
      <style dangerouslySetInnerHTML={{ __html: "@keyframes srSpin{to{transform:rotate(360deg)}}.sr-spin{animation:srSpin .9s linear infinite}.sr-stage-head .btn:disabled{opacity:.65;cursor:default}" }} />
    </div>
  );
};

function SrBookState({ s }) {
  const map = {
    ready:      { tone: "sage",  label: "已就绪" },
    extracting: { tone: "gold",  label: "抽取中" },
    pending:    { tone: "slate", label: "等待" },
  };
  const m = map[s] || map.pending;
  return <span className={`pill pill-${m.tone} text-xs`}><span className="pill-dot" />{m.label}</span>;
}

/* ============ Stage: Overview ============ */
function SrOverview({ book, go }) {
  const deep = useSrDeep(book);
  const stats = srStatsOf(deep);
  const realMetricsArr = stats ? srRealMetrics(stats) : [];
  const metrics = realMetricsArr.length ? realMetricsArr : SR_METRICS;
  const realInput = stats && stats.input_assessment;
  const inputRows = SR_LAYERS.map(l => ({ id: l.id, name: l.name, level: (realInput && realInput[l.id]) || l.input }));
  const realDistArr = stats ? srRealParaDist(stats) : [];
  const dist = realDistArr.length ? realDistArr : SR_PARA_DIST;
  const distMax = Math.max(...dist.map(d => d.v), 0.01);
  const calib = (stats && stats.classifier_calibration) || null;
  const isReal = !!stats;

  return (
    <div className="sr-overview">
      <div className="sr-ov-grid">
        <div className="card sr-ov-metrics">
          <div className="card-head">
            <div><div className="card-title">硬指标基线</div><div className="card-sub">全文计算 · {metrics.length} 项 · 用于抽取对齐与回测阈值</div></div>
            <span className={`pill ${isReal ? "pill-sage" : ""}`}><span className="pill-dot" />{isReal ? "实时" : "MetricsEngine"}</span>
          </div>
          <div className="sr-metric-grid">
            {metrics.map(m => (
              <div key={m.key} className="sr-metric">
                <div className="sr-metric-name">{m.name}</div>
                <div className="sr-metric-val tab-num">
                  {m.pct ? (m.mean*100).toFixed(0) + "%" : (Math.round(m.mean * 10) / 10)}
                  {m.unit && !m.pct && <span className="sr-metric-unit"> {m.unit}</span>}
                </div>
                <div className="sr-metric-std tab-num">σ {Math.round(m.std * 10) / 10}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><div><div className="card-title">输入量评估</div><div className="card-sub">按层设阈值</div></div></div>
          <div className="sr-input-list">
            {inputRows.map(l => (
              <div key={l.id} className="sr-input-row">
                <span className="sr-input-name">{l.name}</span>
                <span className={`sr-input-level lv-${l.level}`}>
                  {SR_INPUT_LABEL[l.level] || l.level}
                </span>
              </div>
            ))}
          </div>
          <div className="sr-calib">
            <div className="ctx-head" style={{marginBottom: 8}}><I.Target size={13} /><span>分类器校准</span></div>
            <ul className="meta-rows">
              <li><span>锚定集</span><strong>{calib ? `前 ${calib.anchor_size} 段 · 强模型` : "前 200 段 · 强模型"}</strong></li>
              <li><span>快模型一致率</span><strong className="tab-num">{calib && calib.fast_model_agreement != null ? Number(calib.fast_model_agreement).toFixed(2) : "—"}</strong></li>
              <li><span>是否降级</span><strong style={{color: calib && calib.fallback_to_strong ? "var(--gold)" : "var(--sage)"}}>{calib ? (calib.fallback_to_strong ? "是" : "否") : "否"}</strong></li>
            </ul>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><div><div className="card-title">段落类型分布</div><div className="card-sub">8 类 · {isReal ? "本书实测" : "LLM 分类器 + 锚定校准"}</div></div></div>
        <div className="sr-dist">
          {dist.map(d => (
            <div key={d.key} className="sr-dist-row">
              <span className="sr-dist-label">{d.type}</span>
              <div className="sr-dist-bar">
                <div className="sr-dist-fill" style={{width: (d.v / distMax * 100) + "%"}} />
              </div>
              <span className="sr-dist-val tab-num">{(d.v*100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>

      <div className="sr-ov-grid">
        <div className="card">
          <div className="card-head"><div><div className="card-title">抽取进度趋势</div><div className="card-sub">近 14 次 run 的 sub-dim 覆盖增长</div></div>
            <span className="pill pill-sage"><span className="pill-dot" />16/16 已覆盖</span>
          </div>
          <SrTrendChart data={SR_TREND} />
        </div>

        <div className="card">
          <div className="card-head"><div><div className="card-title">Evidence 重试链</div><div className="card-sub">两级重试 · 成本审计</div></div></div>
          <ul className="sr-retry">
            <li><span className="sr-retry-dot ok" /><span className="flex-1">初次抽取通过</span><b className="tab-num">47</b></li>
            <li><span className="sr-retry-dot l1" /><span className="flex-1">第一级定向补抽</span><b className="tab-num">9</b></li>
            <li><span className="sr-retry-dot l2" /><span className="flex-1">第二级整维重抽</span><b className="tab-num">2</b></li>
            <li><span className="sr-retry-dot drop" /><span className="flex-1">证据不足丢弃</span><b className="tab-num">1</b></li>
          </ul>
          <p className="text-xs text-muted mt-3">补抽成本 ≤ 完整抽取 30% · 全部 finding 强制 ≥2 证据。</p>
        </div>
      </div>
    </div>
  );
}

function SrTrendChart({ data }) {
  const max = Math.max(...data, 1);
  return (
    <div className="sr-trend">
      {data.map((v, i) => (
        <div key={i} className="sr-trend-col">
          <div className="sr-trend-bar" style={{height: (v / max * 100) + "%"}} />
        </div>
      ))}
    </div>
  );
}

/* ============ Stage: Dimension Matrix ============ */
/* 真实 finding(后端形状)→ FindingCard 期望形状 */
function srAdaptFinding(f) {
  return {
    id: f.finding_id,
    conf: f.confidence,
    statement: f.statement,
    review: f.status || "pending",
    vote: f.user_vote || null,   // 立项 B — 回显当前用户已投的票(跨刷新持久)
    evidence: (f.evidence || []).map(e => ({
      p: e.paragraph_id || null,
      quote: e.quote_text || "",
      kind: e.anchor_kind,
      synthetic: !!e.is_synthetic,
      note: null,
      dims: null,
    })),
  };
}

function SrMatrix({ go, book }) {
  const deep = useSrDeep(book);
  const realInput = (deep && deep.book && deep.book.stats_json && deep.book.stats_json.input_assessment) || null;
  const realMode = !!(deep && deep.runId && deep.dimCounts && Object.keys(deep.dimCounts).length > 0);
  const [cell, setCell] = useStSR("language.sentence_structure");
  const [kindFilter, setKindFilter] = useStSR("all");
  const [hover, setHover] = useStSR(null);
  const [synthBusy, setSynthBusy] = useStSR(false);

  // 有效单元数据：真模式叠加 dimCounts + input_assessment(skip)，否则用 SR_LAYERS 演示值
  const cellData = (layerId, sub) => {
    const path = `${layerId}.${sub.id}`;
    if (!realMode) return { path, name: sub.name, conf: sub.conf, obs: sub.obs, fp: sub.fp, q: sub.q, skip: sub.conf === "skip" };
    if (realInput && realInput[layerId] === "skip") return { path, name: sub.name, conf: "skip", obs: 0, fp: 0, q: 0, skip: true };
    const dc = deep.dimCounts[path];
    if (!dc) return { path, name: sub.name, conf: "low", obs: 0, fp: 0, q: 0, skip: false };
    return { path, name: sub.name, conf: dc.conf, obs: dc.obs, fp: dc.fp, q: dc.q, skip: false };
  };
  const cellsByLayer = SR_LAYERS.map(l => ({ layer: l, cells: l.subs.map(s => cellData(l.id, s)) }));

  // 抽屉 findings：真模式取 deep.findingsByDim[cell] 适配，否则 SR_FINDINGS
  const realGroup = realMode ? deep.findingsByDim[cell] : null;
  const findings = realMode
    ? (realGroup ? { observations: realGroup.observations.map(srAdaptFinding), forbidden_patterns: realGroup.forbidden_patterns.map(srAdaptFinding) } : null)
    : SR_FINDINGS[cell];
  const onReviewFinding = realMode
    ? (findingId, decision) => { if (window.srReviewFinding) window.srReviewFinding(findingId, decision, book.id).catch(() => {}); }
    : null;
  const onVoteFinding = realMode
    ? (findingId, vote) => { if (window.srFindingFeedback) window.srFindingFeedback(findingId, vote, book.id).catch(() => {}); }
    : null;

  // 2D keyboard navigation across the matrix (skip cells are not selectable)
  const grid = cellsByLayer.map(row => row.cells.map(c => ({ path: c.path, skip: c.skip })));
  React.useEffect(() => {
    const inField = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
    const findRC = (p) => {
      for (let r = 0; r < grid.length; r++) for (let c = 0; c < grid[r].length; c++) if (grid[r][c].path === p) return { r, c };
      return { r: 0, c: 0 };
    };
    const move = (dr, dc) => {
      let { r, c } = findRC(cell);
      for (let i = 0; i < 6; i++) {
        r += dr; c += dc;
        if (r < 0 || r >= grid.length || c < 0 || c >= grid[r].length) return;
        if (!grid[r][c].skip) { setCell(grid[r][c].path); return; }
      }
    };
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || inField(e.target)) return;
      if (e.key === "ArrowRight") { e.preventDefault(); move(0, 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); move(0, -1); }
      else if (e.key === "ArrowDown") { e.preventDefault(); move(1, 0); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1, 0); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cell, realMode]);

  const cellMeta = (() => {
    for (const row of cellsByLayer) for (const c of row.cells) if (c.path === cell) return { layer: row.layer, cell: c };
    return null;
  })();

  const totals = realMode
    ? Object.values(deep.dimCounts).reduce((a, d) => ({ obs: a.obs + d.obs, fp: a.fp + d.fp, q: a.q + d.q }), { obs: 0, fp: 0, q: 0 })
    : { obs: 52, fp: 14, q: 140 };
  const hasProfile = !!(deep && deep.profileId);

  const onSynth = async () => {
    if (!realMode || !deep.runId || hasProfile) { go && go("profile"); return; }
    if (synthBusy) return;
    setSynthBusy(true);
    try {
      await window.srSynthesize(deep.runId, book.id);
      go && go("profile");
    } catch (e) {
      if (e && (e.code === "STYLE_REFERENCE_LLM_REQUIRED" || e.code === "STYLE_REFERENCE_CLOUD_POLICY_BLOCKED")) {
        window.alert("合成风格画像需要启用 LLM（系统设置 → 模型与接入）。");
      } else { window.alert("合成失败：" + ((e && e.message) || e)); }
    } finally { setSynthBusy(false); }
  };

  return (
    <div className="sr-matrix-wrap">
      <style>{`
        .sr-matrix-kbd { margin-left: auto; display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: var(--ink-4); }
        .sr-matrix-kbd kbd { font-family: var(--font-mono); font-size: 10px; padding: 1px 5px; border-radius: 4px; background: var(--paper-2); border: 1px solid var(--line-1); color: var(--ink-3); }
        .sr-matrix-cells .sr-cell { transition: transform 180ms var(--ease-spring, ease), box-shadow 180ms var(--ease-soft, ease), border-color var(--t-fast), background var(--t-fast); }
        .sr-matrix-cells .sr-cell.is-active { transform: translateY(-2px); box-shadow: 0 0 0 2px var(--crimson), var(--shadow-md); }
        .sr-findings-scroll { animation: srDrawerIn 300ms var(--ease-out, ease) both; }
        @keyframes srDrawerIn { from { transform: translateX(12px); } to { transform: none; } }
      `}</style>
      <div className="sr-matrix-side">
        <div className="sr-matrix-legend">
          <span className="text-xs text-muted">置信度</span>
          <span className="sr-lg sr-lg-high">高</span>
          <span className="sr-lg sr-lg-medium">中</span>
          <span className="sr-lg sr-lg-low">低</span>
          <span className="sr-lg sr-lg-skip">不足</span>
          <span className="sr-matrix-kbd"><kbd>←</kbd><kbd>↑</kbd><kbd>↓</kbd><kbd>→</kbd> 选维度</span>
        </div>

        <div className="sr-matrix">
          {cellsByLayer.map(({ layer: l, cells }) => (
            <div key={l.id} className="sr-matrix-row">
              <div className="sr-matrix-rowhead">
                <span className="sr-matrix-abbr">{l.abbr}</span>
                <span className="sr-matrix-layer">{l.name}</span>
              </div>
              <div className="sr-matrix-cells">
                {cells.map(c => {
                  const tip = SR_SUBDIM_TIP[c.path];
                  const confLabel = c.conf === "high" ? "高置信" : c.conf === "medium" ? "中置信" : "低置信";
                  return (
                    <button
                      key={c.path}
                      className={`sr-cell conf-${c.conf} ${cell === c.path ? "is-active" : ""}`}
                      onClick={() => !c.skip && setCell(c.path)}
                      onMouseEnter={() => !c.skip && setHover(c.path)}
                      onMouseLeave={() => setHover(null)}
                      disabled={c.skip}
                    >
                      <span className="sr-cell-name">{c.name}</span>
                      {c.skip ? (
                        <span className="sr-cell-skip">语料不足</span>
                      ) : (
                        <span className="sr-cell-stats">
                          <span className="sr-cell-stat"><b>{c.obs}</b>观察</span>
                          <span className="sr-cell-stat"><b>{c.q}</b>引文</span>
                          {c.fp > 0 && <span className="sr-cell-stat fp"><b>{c.fp}</b>禁忌</span>}
                        </span>
                      )}
                      {hover === c.path && !c.skip && (
                        <span className="sr-cell-tip">
                          <span className="sr-cell-tip-conf">
                            <span className={`conf-dot conf-${c.conf}`} />
                            {confLabel} · {c.obs} 观察 / {c.q} 引文 / {c.fp} 禁忌
                          </span>
                          {!realMode && tip && <span className="sr-cell-tip-metric">{tip.metric}</span>}
                          {!realMode && tip && <span className="sr-cell-tip-quote">「{tip.sample}」</span>}
                          <span className="sr-cell-tip-hint">点击查看全部证据 →</span>
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="sr-matrix-foot">
          <div className="sr-matrix-foot-stat"><b className="tab-num">{totals.obs}</b> 观察</div>
          <div className="sr-matrix-foot-stat"><b className="tab-num">{totals.fp}</b> 禁忌模式</div>
          <div className="sr-matrix-foot-stat"><b className="tab-num">{totals.q}</b> 引文样本</div>
          <div className="flex-1" />
          <button className="btn btn-accent btn-sm" disabled={synthBusy} onClick={onSynth}>
            {synthBusy ? <><span className="sr-spin" style={{display:"inline-flex"}}><I.Refresh size={13} /></span> 合成中…</>
              : <><I.Sparkles size={13} /> {hasProfile ? "查看风格画像" : "合成风格画像"}</>}
          </button>
        </div>
      </div>

      {/* Findings drawer */}
      <aside className="sr-findings">
        {cellMeta && (
          <header className="sr-findings-head">
            <div>
              <div className="text-muted text-xs" style={{letterSpacing:"0.12em"}}>{cellMeta.layer.name} · {cellMeta.cell.name}</div>
              <h3 className="text-serif" style={{fontSize:17, margin:"3px 0 0"}}>{cellMeta.cell.name}</h3>
            </div>
            <span className={`pill pill-${cellMeta.cell.conf === "high" ? "sage" : cellMeta.cell.conf === "medium" ? "gold" : "slate"} text-xs`}>
              <span className="pill-dot" />{cellMeta.cell.conf === "high" ? "高置信" : cellMeta.cell.conf === "medium" ? "中置信" : "低置信"}
            </span>
          </header>
        )}

        <div className="sr-findings-filter">
          <button className={`sr-ff ${kindFilter === "all" ? "is-active" : ""}`} onClick={() => setKindFilter("all")}>全部</button>
          <button className={`sr-ff ${kindFilter === "obs" ? "is-active" : ""}`} onClick={() => setKindFilter("obs")}>
            <I.Check size={12} /> 观察 {findings?.observations.length || 0}
          </button>
          <button className={`sr-ff ${kindFilter === "fp" ? "is-active" : ""}`} onClick={() => setKindFilter("fp")}>
            <I.Ban size={12} /> 禁忌 {findings?.forbidden_patterns.length || 0}
          </button>
        </div>

        <div className="sr-findings-scroll" key={cell}>
          {!findings && (
            <div className="empty-state" style={{padding: 30}}>
              <I.Quote size={24} />
              <div className="mt-2 text-muted text-sm">{realMode ? "该维度暂无 finding（语料不足或尚未抽出）。" : "该维度暂无展开数据"}</div>
            </div>
          )}
          {findings && (kindFilter === "all" || kindFilter === "obs") && findings.observations.map(o => (
            <FindingCard key={o.id} kind="obs" finding={o} onReview={onReviewFinding ? (d) => onReviewFinding(o.id, d) : null} onVote={onVoteFinding ? (v) => onVoteFinding(o.id, v) : null} />
          ))}
          {findings && (kindFilter === "all" || kindFilter === "fp") && findings.forbidden_patterns.map(f => (
            <FindingCard key={f.id} kind="fp" finding={f} onReview={onReviewFinding ? (d) => onReviewFinding(f.id, d) : null} onVote={onVoteFinding ? (v) => onVoteFinding(f.id, v) : null} />
          ))}
        </div>
      </aside>
    </div>
  );
}

function FindingCard({ kind, finding, onReview, onVote }) {
  const isFp = kind === "fp";
  const [review, setReview] = useStSR(finding.review || "pending");
  const [vote, setVote] = useStSR(finding.vote || null);
  // deep 重载后 finding.review / vote 变化 → 同步(同 key 实例不会重跑 initializer)
  React.useEffect(() => { setReview(finding.review || "pending"); }, [finding.review]);
  React.useEffect(() => { setVote(finding.vote || null); }, [finding.vote]);
  const setReviewBoth = (next) => { setReview(next); if (onReview) onReview(next); };
  // 立项 B — 投票:真模式发 up/down(无 un-vote 语义,可改向,后端幂等),演示模式本地 toggle。
  const castVote = (v) => {
    if (onVote) { setVote(v); onVote(v); }
    else { setVote(vote === v ? null : v); }
  };
  return (
    <article className={`sr-finding ${isFp ? "is-fp" : ""} rev-${review}`}>
      <header className="sr-finding-head">
        <span className={`sr-finding-tag ${isFp ? "tag-fp" : "tag-obs"}`}>
          {isFp ? <I.Ban size={11} /> : <I.Check size={11} />}
          {isFp ? "禁忌模式" : "观察"}
        </span>
        {!isFp && finding.conf && (
          <span className={`pill text-xs pill-${finding.conf === "high" ? "sage" : "gold"}`}><span className="pill-dot" />{finding.conf === "high" ? "高" : "中"}</span>
        )}
        <span className={`sr-rev-state st-${review}`}>
          {review === "approved" ? "已通过" : review === "rejected" ? "已驳回" : "待审"}
        </span>
        <div className="flex gap-1" style={{marginLeft:"auto"}}>
          <button className={`sr-rev-btn ${review==="approved"?"on-ok":""}`} title="通过" onClick={()=>setReviewBoth(review==="approved"?"pending":"approved")}><I.Check size={13} /></button>
          <button className={`sr-rev-btn ${review==="rejected"?"on-no":""}`} title="驳回" onClick={()=>setReviewBoth(review==="rejected"?"pending":"rejected")}><I.X size={13} /></button>
        </div>
      </header>
      <p className="sr-finding-statement text-serif">{finding.statement}</p>
      <div className="sr-finding-evidence">
        <div className="sr-finding-evidence-label">证据 · {finding.evidence.length}{finding.evidence.length >= 2 ? " · 已满足 ≥2" : " · 不足"}</div>
        {finding.evidence.map((e, i) => (
          <div key={i} className="sr-ev">
            <div className="sr-ev-mark">
              {e.kind === "counter_example" || e.synthetic ? <span className="sr-ev-badge syn">合成反例</span>
                : e.kind === "author_avoidance" ? <span className="sr-ev-badge avoid">负空间</span>
                : <span className="sr-ev-badge quote">{e.p || "引文"}</span>}
            </div>
            {e.quote && <p className="sr-ev-quote text-serif">{e.quote}</p>}
            {e.note && <p className="sr-ev-note">{e.note}</p>}
            {e.dims && (
              <div className="sr-ev-dims">
                {e.dims.map(d => <span key={d} className="sr-ev-dim">{d}</span>)}
              </div>
            )}
          </div>
        ))}
      </div>
      <footer className="sr-finding-foot">
        <span className="text-xs text-muted">这条画像准吗？</span>
        <div className="sr-vote">
          <button className={`sr-vote-btn ${vote==="up"?"on":""}`} onClick={()=>castVote("up")} aria-label="赞">👍</button>
          <button className={`sr-vote-btn ${vote==="down"?"on":""}`} onClick={()=>castVote("down")} aria-label="踩">👎</button>
        </div>
        <span className="text-xs text-subtle" style={{marginLeft:"auto"}}>反馈聚合后更新 confidence</span>
      </footer>
    </article>
  );
}

/* ============ Stage: Profile ============ */
function SrProfile({ book, go }) {
  const [tab, setTab] = useStSR("summary");
  const deep = useSrDeep(book);
  const profile = deep && deep.profile;
  const pj = (profile && profile.profile_json) || null;
  const real = !!pj;
  const dimMeta = (path) => { for (const l of SR_LAYERS) for (const s of l.subs) if (`${l.id}.${s.id}` === path) return { abbr: l.abbr, name: s.name }; return { abbr: "·", name: path }; };
  const cov = (profile && profile.coverage_json) || {};
  const subDims = (pj && pj.sub_dimensions) || null;
  const realDimRows = subDims ? Object.entries(subDims).map(([path, d]) => ({ path, ...dimMeta(path), conf: (d && d.confidence) || "low", obs: (d && d.observation_count) || 0, fp: (d && d.forbidden_pattern_count) || 0, q: (d && d.quote_count) || 0 })) : null;
  const baseline = (pj && pj.metrics_baseline) || null;
  const realBaseline = baseline ? SR_METRICS.map(m => { const b = baseline[m.key]; if (!b || b.mean == null) return null; return { ...m, mean: Number(b.mean), std: Number(b.std) }; }).filter(Boolean).slice(0, 6) : null;
  const sampleIdx = (pj && pj.scene_samples_index) || null;
  const features = (pj && pj.style_features) || [];
  const demoDimRows = SR_LAYERS.filter(l => l.input !== "skip").flatMap(l => l.subs.filter(s => s.conf !== "skip").map(s => ({ path: `${l.id}.${s.id}`, abbr: l.abbr, name: s.name, conf: s.conf, obs: s.obs, fp: s.fp, q: s.q })));
  const dimRows = realDimRows || demoDimRows;

  return (
    <div className="sr-profile">
      <div className="sr-profile-main">
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{real ? (profile.title || `${book.author}风格画像`) : `${book.author}风格画像 · v3`}</div>
              <div className="card-sub">{real ? `${cov.findings_count || 0} finding / ${cov.quotes_count || 0} 引文聚合 · ${cov.sub_dim_count || 0} 维` : "由 52 观察 / 14 禁忌 / 140 引文聚合 · 12 维有效"}</div>
            </div>
            <span className={`pill ${real && profile.status !== "active" ? "pill-gold" : "pill-sage"}`}><span className="pill-dot" />{real ? (profile.status === "active" ? "已就绪" : profile.status) : "已就绪"}</span>
          </div>
          <p className="sr-profile-summary text-serif">
            {real
              ? (pj.narrative_summary || "（该画像尚无叙述性概述。）")
              : "冷峻、克制、白描见长。短句为骨，逗号顿连推进节奏，少用关联词与抒情排比。比喻具象、取自乡土器物，喻体之后即收，不作解释。叙述者多为限知的「我」，与事件保持冷静距离；对话后接动作而非心理剖白。整体以白描叠加细节制造反讽与悲悯，不依赖形容词堆砌。"}
          </p>
          {real && features.length > 0 && (
            <div style={{margin: "2px 0 4px"}}>
              {features.slice(0, 8).map((f, i) => (
                <span key={i} className="sr-pd-path" style={{display:"inline-block", margin:"2px 6px 2px 0", padding:"2px 8px", background:"var(--paper-2)", borderRadius:6, fontSize:12}}>{f}</span>
              ))}
            </div>
          )}

          <div className="sr-profile-tabs">
            <button className={`sr-pt ${tab === "summary" ? "is-active" : ""}`} onClick={() => setTab("summary")}>维度摘要</button>
            <button className={`sr-pt ${tab === "preview" ? "is-active" : ""}`} onClick={() => setTab("preview")}>预览示例</button>
          </div>

          {tab === "summary" && (
            <div className="sr-profile-dims">
              {dimRows.map(row => (
                <div key={row.path} className="sr-pd-row">
                  <span className="sr-pd-path">{row.abbr} · {row.name}</span>
                  <span className={`sr-pd-conf conf-dot conf-${row.conf}`} />
                  <span className="sr-pd-counts">{row.obs} 观察 · {row.fp} 禁忌 · {row.q} 引文</span>
                </div>
              ))}
              {realDimRows && realDimRows.length === 0 && <div className="text-xs text-muted" style={{padding:"8px 2px"}}>画像暂无维度摘要。</div>}
            </div>
          )}

          {tab === "preview" && <SrPreview profileId={real ? profile.profile_id : null} />}
        </div>
      </div>

      <aside className="sr-profile-side">
        <div className="card-flat">
          <div className="ctx-head" style={{marginBottom: 10}}><I.Target size={13} /><span>指标基线</span></div>
          <div className="sr-baseline">
            {(realBaseline && realBaseline.length ? realBaseline : SR_METRICS.slice(0, 5)).map(m => (
              <div key={m.key} className="sr-baseline-row">
                <span className="text-sm">{m.name}</span>
                <span className="tab-num fw-600">{m.pct ? (m.mean*100).toFixed(0)+"%" : (Math.round(m.mean*10)/10)} <span className="text-muted text-xs">±{Math.round(m.std*10)/10}</span></span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted mt-3">回测阈值 = max(σ × 1.25, 绝对下限)，自适应于本作。</p>
        </div>

        <div className="card-flat">
          <div className="ctx-head" style={{marginBottom: 10}}><I.Quote size={13} /><span>场景样例索引</span></div>
          <ul className="sr-sample-index">
            {sampleIdx ? (
              Object.entries(sampleIdx).filter(([, ids]) => (ids || []).length).length === 0
                ? <li><span className="text-muted text-xs">暂无样例索引</span></li>
                : Object.entries(sampleIdx).filter(([, ids]) => (ids || []).length).map(([t, ids]) => (
                    <li key={t}><span>{SR_PARA_LABEL[t] || t}</span><b className="tab-num">{(ids || []).length}</b></li>
                  ))
            ) : (
              <>
                <li><span>对话</span><b className="tab-num">10</b></li>
                <li><span>动作</span><b className="tab-num">6</b></li>
                <li><span>心理</span><b className="tab-num">8</b></li>
                <li><span>环境</span><b className="tab-num">14</b></li>
              </>
            )}
          </ul>
          <p className="text-xs text-muted mt-2">Few-shot 注入 O(1) 直读，不绕段落表。</p>
        </div>

        <button className="btn btn-accent btn-lg" style={{width:"100%"}} onClick={() => go && go("validation")}><I.ArrowRight size={15} /> 进入回测校验</button>
      </aside>
    </div>
  );
}

function SrPreview({ profileId }) {
  const demo = [
    { kind: "对话", verdict: "pass", text: "「茴香豆的茴字，怎样写的？」他显出极高兴的样子，将两个指头的长指甲敲着柜台。" },
    { kind: "环境", verdict: "partial", text: "灰白的天压在屋檐上，巷子空着，只有风把一张旧报纸卷起来，又放下。" },
    { kind: "动作", verdict: "pass", text: "他没有应声，弯下腰，把那枚铜板从砖缝里抠出来，又用袖子擦了擦。" },
  ];
  const [samples, setSamples] = useStSR(null);
  const [loading, setLoading] = useStSR(false);
  const [err, setErr] = useStSR(null);
  const run = React.useCallback(() => {
    if (!profileId) return;
    setLoading(true); setErr(null);
    window.srPreviewSamples(profileId)
      .then(r => setSamples((r && r.samples) || []))
      .catch(e => setErr(e && (e.code === "STYLE_REFERENCE_LLM_REQUIRED" || e.code === "STYLE_REFERENCE_CLOUD_POLICY_BLOCKED")
        ? "预览生成需要启用 LLM（系统设置 → 模型与接入）。"
        : ((e && e.message) || "预览生成失败")))
      .finally(() => setLoading(false));
  }, [profileId]);
  React.useEffect(() => { if (profileId) run(); }, [profileId, run]);

  const list = profileId
    ? (samples || []).map(s => ({ kind: SR_PARA_LABEL[s.paragraph_type] || s.paragraph_type, verdict: s.verdict || "partial", text: s.sample_text || "", error: s.error }))
    : demo;

  return (
    <div className="sr-preview">
      <div className="sr-preview-head">
        <span className="text-muted text-sm">{profileId ? "生成 3 段示例 + 自跑回测（sync_only）" : "apply 前自动生成 3 段示例 + 自跑回测"}</span>
        <button className="btn btn-quiet btn-sm" disabled={loading || !profileId} onClick={run}>
          {loading ? <><span className="sr-spin" style={{display:"inline-flex"}}><I.Refresh size={13} /></span> 生成中…</> : <><I.Refresh size={13} /> 重新生成</>}
        </button>
      </div>
      {err && <div className="sr-fewshot-warn"><I.Info size={13} /><span>{err}</span></div>}
      {profileId && !loading && !err && samples && samples.length === 0 && (
        <div className="text-xs text-muted" style={{padding:"10px 2px"}}>暂无预览样例。</div>
      )}
      {list.map((s, i) => (
        <article key={i} className="sr-pv-card">
          <header className="sr-pv-head">
            <span className="pill text-xs"><span className="pill-dot" />{s.kind}</span>
            {s.error ? <span className="pill pill-rose text-xs"><span className="pill-dot" />生成失败</span> : <VerdictPill v={s.verdict} />}
          </header>
          {s.text && <p className="sr-pv-text text-serif">{s.text}</p>}
        </article>
      ))}
    </div>
  );
}

function VerdictPill({ v }) {
  const map = {
    pass:       { tone: "sage",    label: "PASS" },
    partial:    { tone: "gold",    label: "PARTIAL" },
    fail:       { tone: "rose",    label: "FAIL" },
    plagiarism: { tone: "crimson", label: "抄袭" },
  };
  const m = map[v] || map.partial;
  return <span className={`pill pill-${m.tone} text-xs`} style={{fontFamily:"var(--font-mono)", letterSpacing:"0.05em"}}><span className="pill-dot" />{m.label}</span>;
}

/* ============ Stage: Apply / Inject ============ */
const SR_TASKS = [
  { id: "project_init", name: "项目初始化", def: "A", refresh: 0 },
  { id: "scene_generation", name: "场景生成", def: "mixed", refresh: 0 },
  { id: "fine_tuning", name: "精修小改", def: "B", refresh: 0 },
  { id: "long_form_continuation", name: "长文续写", def: "mixed", refresh: 1500 },
  { id: "key_chapter", name: "关键章节", def: "C", refresh: 2000 },
];

/* layered injection stack — base(project/global) ∪ character(pov+onstage) ∪ scene */
const SR_LAYER_STACK = [
  { rank: 3, scope: "global",    label: "全局基底", target: "默认风格", weight: 1, tokens: 320, tone: "slate",   frags: 2 },
  { rank: 2, scope: "project",   label: "项目层",   target: "潮汐档案", weight: 2, tokens: 540, tone: "crimson", frags: 4 },
  { rank: 1, scope: "character", label: "角色层 · POV", target: "林岑", weight: 3, tokens: 680, tone: "gold",    frags: 3, onstage: ["周岚"] },
  { rank: 0, scope: "scene",     label: "场景层",   target: "CH08·SC01", weight: 4, tokens: 880, tone: "sage",    frags: 3 },
];

const SR_FEWSHOT = {
  dialogue:    { id: "q_001", text: "「温一碗酒。」", note: "对话 · 单句定身份" },
  action:      { id: "q_067", text: "他从破衣袋里摸出四文大钱，放在我手里。", note: "动作 · 不解释心理" },
  description_env: { id: "q_203", text: "苍黄的天底下，远近横着几个萧索的荒村，没有一些活气。", note: "环境 · 冷色白描" },
};

const SR_BANNED_INIT = [
  { term: "文笔优美", hint: "改具体描写", scope: "generation", source: "preset" },
  { term: "震撼人心", hint: "用动作呈现", scope: "generation", source: "preset" },
  { term: "潮汐之子", hint: "源书专名", scope: "extraction", source: "user" },
];

function SrApply({ go, book }) {
  const [sub, setSub] = useStSR("strategy");
  const [strategy, setStrategy] = useStSR("mixed");
  const [taskType, setTaskType] = useStSR("scene_generation");
  const [applied, setApplied] = useStSR(null); // 已创建的审核条目描述
  const [intensity, setIntensity] = useStSR(80);
  const [scope, setScope] = useStSR("project");
  const [scopeRefId, setScopeRefId] = useStSR(null);   // 立项 A — scene/character 级绑定目标 id
  const [scopeOpts, setScopeOpts] = useStSR({ scene: [], character: [] });
  const [banned, setBanned] = useStSR(SR_BANNED_INIT);
  const [bannedInput, setBannedInput] = useStSR("");
  const [bannedScope, setBannedScope] = useStSR("generation");
  const [selectedDims, setSelectedDims] = useStSR(() => {
    const all = [];
    SR_LAYERS.forEach(l => l.input !== "skip" && l.subs.forEach(s => s.conf !== "skip" && all.push(`${l.id}.${s.id}`)));
    return all;
  });

  /* ---- 真后端深层数据：有真画像则注入应用走真后端，否则回退演示 ---- */
  const isRealBook = !!(book && book.real);
  const [deep, setDeep] = useStSR(() => (isRealBook ? srDeepFor(book.id) : null));
  React.useEffect(() => {
    if (!isRealBook) { setDeep(null); return; }
    const sync = () => setDeep(window.srDeepFor ? window.srDeepFor(book.id) : null);
    sync();
    if (window.srLoadDeep) window.srLoadDeep(book.id);
    window.addEventListener("sr:deep-changed", sync);
    return () => window.removeEventListener("sr:deep-changed", sync);
  }, [isRealBook, book && book.id]);
  const realProfileId = deep && deep.profileId;
  const realMode = !!realProfileId;
  const realBindings = (deep && deep.bindings) || [];
  // 立项 A — 当前活动项目 id(空安全:works 列表为空时 active() 可能 undefined)
  const activeProjId = (WsWorks && WsWorks.active && WsWorks.active() && WsWorks.active().id) || null;
  // 立项 A — scope 切换时清空已选目标(避免把 A scope 的目标误用到 B scope)
  React.useEffect(() => { setScopeRefId(null); }, [scope]);
  // 立项 A — 真模式按当前活动项目加载场景/角色选项(直取后端,不依赖 catalog 缓存状态)。
  // 依赖含 activeProjId:切换活动项目时刷新选项,避免跨项目数据陈旧。
  React.useEffect(() => {
    if (!realMode || !activeProjId) { setScopeOpts({ scene: [], character: [] }); return; }
    const pid = activeProjId;
    let alive = true;
    (async () => {
      try {
        const { apiGet } = await import("./lib/client.js");
        const [cat, lib] = await Promise.all([
          apiGet(`/api/v2/projects/${pid}/catalog`).catch(() => null),
          apiGet(`/api/v2/projects/${pid}/library`).catch(() => null),
        ]);
        if (!alive) return;
        const scenes = [];
        ((cat && cat.chapters) || []).forEach(c => (c.scenes || []).forEach(s => {
          if (s && s.scene_id) scenes.push({ id: s.scene_id, label: `${c.no ? c.no + "章·" : ""}${s.title || s.scene_id}` });
        }));
        const chars = ((lib && lib.characters) || []).map(c => ({
          id: c.character_id || c.id, label: c.name || c.display_name || c.character_id,
        })).filter(c => c.id);
        setScopeOpts({ scene: scenes, character: chars });
      } catch { if (alive) setScopeOpts({ scene: [], character: [] }); }
    })();
    return () => { alive = false; };
  }, [realMode, activeProjId]);

  /* ---- 真注入预览（dryrun，不写盘，debounce 350ms）---- */
  const [preview, setPreview] = useStSR(null);
  const [previewErr, setPreviewErr] = useStSR(null);
  const previewTimer = React.useRef(null);
  React.useEffect(() => {
    if (!realMode) { setPreview(null); setPreviewErr(null); return; }
    clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => {
      window.srInjectionPreview(realProfileId, {
        strategy, task_type: taskType, intensity,
        sub_dimensions: selectedDims,
        include_positive: true, include_forbidden: true, include_metric: strategy !== "C",
      }).then(r => { setPreview(r); setPreviewErr(null); })
        .catch(e => { setPreview(null); setPreviewErr((e && e.message) || "注入预览失败"); });
    }, 350);
    return () => clearTimeout(previewTimer.current);
  }, [realMode, realProfileId, strategy, taskType, intensity, selectedDims]);

  const toggleDim = (path) => setSelectedDims(prev => prev.includes(path) ? prev.filter(p => p !== path) : [...prev, path]);
  const task = SR_TASKS.find(t => t.id === taskType) || SR_TASKS[1];
  const obsCount = Math.round((intensity / 100) * 6 * (selectedDims.length / 12));
  const totalTokens = SR_LAYER_STACK.reduce((s, l) => s + l.tokens, 0);

  const addBanned = () => {
    const t = bannedInput.trim();
    if (!t) return;
    setBanned(prev => [...prev, { term: t, hint: "", scope: bannedScope, source: "user" }]);
    setBannedInput("");
  };

  return (
    <div className="sr-apply">
      <div className="sr-apply-main">
        <nav className="sr-apply-subtabs">
          <button className={`sr-ast ${sub==="strategy"?"is-active":""}`} onClick={()=>setSub("strategy")}><I.Sliders size={13} /> 策略与维度</button>
          <button className={`sr-ast ${sub==="layers"?"is-active":""}`} onClick={()=>setSub("layers")}><I.Layers size={13} /> 叠加层</button>
          <button className={`sr-ast ${sub==="fewshot"?"is-active":""}`} onClick={()=>setSub("fewshot")}><I.Quote size={13} /> Few-shot</button>
          <button className={`sr-ast ${sub==="banned"?"is-active":""}`} onClick={()=>setSub("banned")}><I.Ban size={13} /> 禁用词 <span className="sr-ast-count">{banned.length}</span></button>
        </nav>

        {sub === "strategy" && (
          <>
            <div className="card">
              <div className="card-head"><div><div className="card-title">注入策略</div><div className="card-sub">按任务类型选择 A / B / C / 混合，TaskType 自带默认</div></div></div>
              <div className="sr-task-row">
                {SR_TASKS.map(t => (
                  <button key={t.id} className={`sr-task ${taskType === t.id ? "is-active" : ""}`} onClick={() => { setTaskType(t.id); setStrategy(t.def); }}>
                    <span className="sr-task-name">{t.name}</span>
                    <span className="sr-task-def">默认 {t.def}{t.refresh > 0 ? ` · 每${t.refresh}字刷新` : ""}</span>
                  </button>
                ))}
              </div>
              <div className="sr-strat-row">
                <StratCard id="A" cur={strategy} on={setStrategy} title="System Prompt" desc="把观察 + 禁忌写进系统提示" />
                <StratCard id="B" cur={strategy} on={setStrategy} title="Few-shot" desc="从样例索引直读示范段落" />
                <StratCard id="C" cur={strategy} on={setStrategy} title="RAG" desc="三粒度向量召回（Phase 3）" />
                <StratCard id="mixed" cur={strategy} on={setStrategy} title="混合" desc="A+B 组合，预算分配" />
              </div>
            </div>

            <div className="card">
              <div className="card-head"><div><div className="card-title">风格强度</div><div className="card-sub">控制注入的观察数量与约束力度</div></div>
                <span className="sr-intensity-val tab-num">{intensity}%</span>
              </div>
              <input type="range" min="0" max="100" value={intensity} onChange={e=>setIntensity(parseInt(e.target.value))} className="sr-range" />
              <div className="sr-intensity-ticks"><span>轻微借鉴</span><span>均衡</span><span>强烈复刻</span></div>
              <div className="sr-intensity-readout">
                <I.Sparkles size={13} />
                <span>当前将注入约 <b>{Math.max(2, obsCount)}</b> 条观察 · <b>{selectedDims.length}</b> 个维度 · 禁忌红线 <b>全量</b> 固定保留</span>
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <div><div className="card-title">注入维度</div><div className="card-sub">勾选要参与注入的 sub-dim（{selectedDims.length} / 12 已选）</div></div>
                <button className="btn btn-quiet btn-sm" onClick={() => {
                  const all = [];
                  SR_LAYERS.forEach(l => l.input !== "skip" && l.subs.forEach(s => s.conf !== "skip" && all.push(`${l.id}.${s.id}`)));
                  setSelectedDims(selectedDims.length === all.length ? [] : all);
                }}>{selectedDims.length === 12 ? "全不选" : "全选"}</button>
              </div>
              <div className="sr-dimselect">
                {SR_LAYERS.map(l => (
                  <div key={l.id} className="sr-ds-layer">
                    <div className="sr-ds-layer-name">{l.name}</div>
                    <div className="sr-ds-cells">
                      {l.subs.map(s => {
                        const path = `${l.id}.${s.id}`;
                        const disabled = s.conf === "skip";
                        const on = selectedDims.includes(path);
                        return (
                          <button key={s.id} className={`sr-ds-cell ${on ? "is-on" : ""} ${disabled ? "is-disabled" : ""}`}
                            onClick={() => !disabled && toggleDim(path)} disabled={disabled}>
                            {on && <I.Check size={11} />}{s.name}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {sub === "layers" && (
          <div className="card">
            <div className="card-head">
              <div><div className="card-title">叠加注入层</div><div className="card-sub">由泛到具体加权全叠：scene &gt; character &gt; project &gt; global，越具体预算越大</div></div>
              <span className="pill"><span className="pill-dot" />{SR_LAYER_STACK.length} 层 · {totalTokens} tok</span>
            </div>

            <div className="sr-stack">
              {SR_LAYER_STACK.map((l, i) => (
                <div key={l.scope} className="sr-stack-layer">
                  <div className={`sr-stack-rank rank-${l.tone}`}>rank {l.rank}</div>
                  <div className="sr-stack-body">
                    <div className="sr-stack-top">
                      <span className={`pill pill-${l.tone} text-xs`}><span className="pill-dot" />{l.label}</span>
                      <span className="sr-stack-target text-serif">{l.scope === "project" && WsWorks ? WsWorks.active().title : l.target}</span>
                      {l.onstage && <span className="sr-stack-onstage">+ 在场 {l.onstage.join("、")}</span>}
                      <span className="sr-stack-frags">{l.frags} fragments</span>
                    </div>
                    <div className="sr-stack-budget">
                      <div className="sr-stack-budget-track">
                        <div className={`sr-stack-budget-fill fill-${l.tone}`} style={{width: (l.tokens / 880 * 100) + "%"}} />
                      </div>
                      <span className="sr-stack-weight">权重 ×{l.weight}</span>
                      <span className="sr-stack-tokens tab-num">{l.tokens} tok</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="sr-stack-note">
              <I.Info size={13} />
              <span>合并规则：base + 最具体增量逐层叠加；forbidden 行级去重；同一 metric 取最具体层；token 按 <b>weights=range(1,n+1)</b> 加权分配（scene 最大）。qc gate 单选时走 <code>resolve_active_binding</code> 透明返回合并后的单一 fragments。</span>
            </div>
          </div>
        )}

        {sub === "fewshot" && (
          <div className="card">
            <div className="card-head">
              <div><div className="card-title">Few-shot 示例（策略 B）</div><div className="card-sub">从 profile.scene_samples_index 按段类型 O(1) 直读，不绕段落表</div></div>
              <span className="pill pill-gold"><span className="pill-dot" />k = 5</span>
            </div>
            {strategy === "A" && (
              <div className="sr-fewshot-warn"><I.Info size={13} /><span>当前策略为 A（System Prompt），不注入 few-shot。切到 B 或 混合 以启用示例。</span></div>
            )}
            <div className="sr-fewshot-list">
              {Object.entries(SR_FEWSHOT).map(([k, v]) => (
                <div key={k} className="sr-fewshot-item">
                  <div className="sr-fewshot-meta">
                    <span className="pill text-xs"><span className="pill-dot" />{v.note}</span>
                    <span className="sr-fewshot-id">{v.id}</span>
                  </div>
                  <p className="sr-fewshot-text text-serif">{v.text}</p>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted mt-3">每 sub-dim 索引：对话 10 · 动作 6 · 心理 8 · 环境 14（见画像页样例索引）。</p>
          </div>
        )}

        {sub === "banned" && (
          <div className="card">
            <div className="card-head">
              <div><div className="card-title">禁用词编辑</div><div className="card-sub">generation = 生成时禁用 · extraction = 抽取时跳过含此词的段落</div></div>
            </div>
            <div className="sr-banned-add">
              <input className="input" placeholder="添加禁用词…" value={bannedInput}
                onChange={e=>setBannedInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&addBanned()} />
              <div className="seg">
                <button className={`seg-btn ${bannedScope==="generation"?"is-active":""}`} onClick={()=>setBannedScope("generation")}>generation</button>
                <button className={`seg-btn ${bannedScope==="extraction"?"is-active":""}`} onClick={()=>setBannedScope("extraction")}>extraction</button>
              </div>
              <button className="btn btn-primary btn-sm" onClick={addBanned}><I.Plus size={13} /> 添加</button>
            </div>
            <ul className="sr-banned-list">
              {banned.map((b, i) => (
                <li key={i} className="sr-banned-item">
                  <span className={`sr-banned-scope sc-${b.scope}`}>{b.scope === "generation" ? "生成" : "抽取"}</span>
                  <span className="sr-banned-term text-serif">{b.term}</span>
                  {b.hint && <span className="sr-banned-hint">→ {b.hint}</span>}
                  {b.source === "preset" && <span className="sr-banned-preset">预置</span>}
                  <button className="btn btn-quiet btn-sm" onClick={()=>setBanned(prev=>prev.filter((_,j)=>j!==i))}><I.X size={13} /></button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Right: bundle preview + bindings */}
      <aside className="sr-apply-side">
        <div className="card-flat sr-bundle">
          <div className="ctx-head" style={{marginBottom: 10}}><I.FileText size={13} /><span>SystemPromptFragments · {realMode ? "实时预览" : "有序"}</span></div>
          {realMode ? (
            <SrBundleReal preview={preview} previewErr={previewErr} />
          ) : (
            <>
              <div className="sr-bundle-frag">
                <div className="sr-frag-label"><span className="sr-frag-ord">1</span> narrative_summary</div>
                <p className="sr-frag-text">冷峻克制白描，短句为骨，逗号顿连…</p>
              </div>
              <div className="sr-bundle-frag">
                <div className="sr-frag-label danger"><span className="sr-frag-ord">2</span><I.Ban size={11} /> banned_pattern_block</div>
                <p className="sr-frag-text">禁：排比抒情长句 · 陈词滥调比喻 · 比喻后解释…</p>
              </div>
              <div className="sr-bundle-frag">
                <div className="sr-frag-label"><span className="sr-frag-ord">3</span> observations_by_dim · {Math.max(2, obsCount)} 条</div>
                <p className="sr-frag-text">句式：短句独立成段 / 词汇：乡土具象…</p>
              </div>
              <div className="sr-bundle-frag fixed">
                <div className="sr-frag-label lock"><span className="sr-frag-ord">4</span><I.ShieldCheck size={11} /> anti_plagiarism_block · 固定</div>
                <p className="sr-frag-text">严禁复制原文表达、人物、桥段与标志性意象。</p>
              </div>
              <div className="sr-budget-bar">
                <div className="sr-budget-track">
                  <div className="sr-budget-fill" style={{width: (totalTokens / 3000 * 100) + "%"}} />
                </div>
                <div className="sr-budget-legend">
                  <span className="tab-num">{totalTokens}</span> / 3000 tok 预算
                </div>
              </div>
            </>
          )}
          <div className="sr-bundle-meta">
            <span>策略 {strategy === "mixed" ? "A+B" : strategy}</span>
            <span>·</span>
            <span>{task.refresh > 0 ? `续写每 ${task.refresh} 字刷新` : "一次性注入"}</span>
          </div>
        </div>

        {task.refresh > 0 && (
          <div className="card-flat sr-drift">
            <div className="ctx-head" style={{marginBottom: 10}}><I.Refresh size={13} /><span>长文防漂移</span></div>
            <div className="sr-drift-track">
              {[0,1,2,3].map(i => (
                <div key={i} className="sr-drift-seg">
                  <div className="sr-drift-bar" />
                  {i < 3 && <div className="sr-drift-tick"><I.Refresh size={10} /></div>}
                </div>
              ))}
            </div>
            <p className="text-xs text-muted mt-2">每生成 {task.refresh} 字带最新 context 重调注入，5000+ 字续写 inject ≥3 次，防止回归 base 腔调。</p>
          </div>
        )}

        <div className="card-flat">
          <div className="ctx-head" style={{marginBottom: 10}}><I.GitBranch size={13} /><span>应用范围</span></div>
          <div className="sr-scope">
            {[["project","项目"],["scene","场景"],["character","角色"]].map(([id, name]) => (
              <button key={id}
                className={`sr-scope-btn ${scope === id ? "is-active" : ""}`}
                onClick={() => setScope(id)}>{name}</button>
            ))}
          </div>
          {/* 立项 A — scene/character 级目标选择器(真模式):选中 id 作为 effect.scope_ref_id */}
          {realMode && scope !== "project" && (
            <div className="sr-scope-target" style={{marginTop: 8}}>
              <select className="sr-select" value={scopeRefId || ""}
                onChange={(e) => setScopeRefId(e.target.value || null)}
                style={{width:"100%", padding:"6px 8px"}}>
                <option value="">{`选择${scope === "scene" ? "场景" : "角色"}…`}</option>
                {(scopeOpts[scope] || []).map(o => (
                  <option key={o.id} value={o.id}>{o.label}</option>
                ))}
              </select>
              {(scopeOpts[scope] || []).length === 0 && (
                <p className="text-xs text-muted" style={{marginTop:4}}>
                  {scope === "scene" ? "当前项目暂无场景(先在目录/构思生成场景)" : "当前项目暂无角色(先在构思补充角色)"}
                </p>
              )}
            </div>
          )}
          {realMode ? (
            <ul className="sr-bindings">
              {realBindings.length === 0 && (
                <li className="text-xs text-muted" style={{padding:"6px 2px", display:"block"}}>暂无已批准的绑定 · 应用并在收件箱批准后出现在此。</li>
              )}
              {realBindings.map(b => {
                const tone = b.scope === "project" ? "crimson" : b.scope === "character" ? "gold" : b.scope === "scene" ? "sage" : "slate";
                const sname = b.scope === "project" ? "项目" : b.scope === "character" ? "角色" : b.scope === "scene" ? "场景" : b.scope;
                return (
                  <li key={b.binding_id}>
                    <span className={`pill pill-${tone} text-xs`}><span className="pill-dot" />{sname}</span>
                    <span className="text-sm">{b.scope_ref_id || "—"} · {b.strategy === "mixed" ? "A+B" : b.strategy}</span>
                    <button className="btn btn-quiet btn-sm" onClick={() => {
                      window.srUnbind && window.srUnbind(b.binding_id, book.id).catch(e => window.alert("解绑失败：" + ((e && e.message) || e)));
                    }}>解绑</button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <ul className="sr-bindings">
              <li><span className="pill pill-crimson text-xs"><span className="pill-dot" />项目</span><span className="text-sm">潮汐档案 · 全局</span><I.Check size={13} style={{color:"var(--sage)"}} /></li>
              <li><span className="pill pill-gold text-xs"><span className="pill-dot" />角色</span><span className="text-sm">林岑 POV</span><button className="btn btn-quiet btn-sm">解绑</button></li>
              <li><span className="pill pill-sage text-xs"><span className="pill-dot" />场景</span><span className="text-sm">CH08 · SC01</span><button className="btn btn-quiet btn-sm">解绑</button></li>
            </ul>
          )}
        </div>

        <button className="btn btn-accent btn-lg" style={{width:"100%"}}
          disabled={!!applied || (realMode && scope !== "project" && !scopeRefId)} onClick={() => {
          if (!rvPush) return;
          const _act = (WsWorks && WsWorks.active && WsWorks.active()) || null;
          const workTitle = (_act && _act.title) || "当前作品";
          const projId = activeProjId;
          const selOpt = scope !== "project" ? (scopeOpts[scope] || []).find(o => o.id === scopeRefId) : null;
          const selLabel = selOpt ? selOpt.label : (scopeRefId || "");
          const scopeName = scope === "project" ? `项目《${workTitle}》`
            : scope === "scene" ? (realMode ? `场景 ${selLabel}` : "场景 CH08 · SC01")
            : (realMode ? `角色 ${selLabel}` : "角色 林岑 POV");
          // 立项 A — scope_ref_id:项目级用 project_id,场景/角色级用所选目标 id(显式传,不靠后端回退)
          const effScopeRefId = scope === "project" ? projId : scopeRefId;
          if (realMode) {
            const profileTitle = (deep && deep.profile && deep.profile.title) || `${book.author || "参考"}风格画像`;
            rvPush({
              kind: "decision", priority: 1,
              title: `参考画像「${profileTitle}」应用到${scopeName}`,
              where: "风格参考 · 注入应用", source: "风格参考",
              detail: `策略 ${strategy === "mixed" ? "A+B 混合" : strategy} · 强度 ${intensity}% · ${selectedDims.length} 维。批准后画像绑定到该范围、作为生成期默认润色基线，可随时回风格参考解绑。`,
              dedupe_key: `style-apply:${realProfileId}:${scope}:${effScopeRefId || "_"}:${strategy}`,
              actions: [
                { label: "批准应用", intent: "primary", op: "resolve",
                  effect: {
                    type: "bind_style_profile",
                    profile_id: realProfileId,
                    scope, scope_ref_id: effScopeRefId, task_type: taskType, strategy, intensity,
                    sub_dimensions: selectedDims,
                    include_positive: true, include_forbidden: true, include_metric: strategy !== "C",
                  } },
                { label: "回风格参考调整", intent: "ghost", op: "nav", to: "styleref" },
                { label: "丢弃", intent: "quiet", op: "resolve" },
              ],
            });
          } else {
            rvPush({
              kind: "decision", priority: 1,
              title: `参考画像「冷峻短句」应用到${scopeName}`,
              where: "风格参考 · 注入应用", source: "风格参考",
              detail: `策略 ${strategy === "mixed" ? "A+B 混合" : strategy} · 强度 ${intensity}% · 注入预算 ${totalTokens} tok。（演示画像：导入真实参考书并合成画像后，应用将创建携带配置的真实绑定决策。）`,
              actions: [
                { label: "批准应用", intent: "primary", op: "resolve" },
                { label: "回风格参考调整", intent: "ghost", op: "nav", to: "styleref" },
                { label: "丢弃", intent: "quiet", op: "resolve" },
              ],
            });
          }
          setApplied(scopeName);
        }}>
          <I.Check size={15} /> {applied ? "已进入审核" : `应用到${scope === "project" ? "项目" : scope === "scene" ? "场景" : "角色"} · 进审核`}
        </button>
        {applied ? (
          <p className="text-xs" style={{textAlign:"center", color:"var(--sage)", fontWeight:600}}>
            已为{applied}创建审核条目 · <a href="#review" style={{color:"inherit"}}>去待办收件箱拍板 →</a>
          </p>
        ) : (
          <p className="text-xs text-muted" style={{textAlign:"center"}}>应用后在「待办收件箱」创建决策条目，批准后才作为运行时规则生效。</p>
        )}
      </aside>
    </div>
  );
}

function StratCard({ id, cur, on, title, desc }) {
  return (
    <button className={`sr-strat ${cur === id ? "is-active" : ""}`} onClick={() => on(id)}>
      <span className="sr-strat-badge">{id === "mixed" ? "A+B" : id}</span>
      <span className="sr-strat-title">{title}</span>
      <span className="sr-strat-desc">{desc}</span>
    </button>
  );
}

/* 真实注入预览（dryrun）的 SystemPromptFragments 渲染 */
function SrBundleReal({ preview, previewErr }) {
  if (previewErr) {
    return <div className="sr-fewshot-warn"><I.Info size={13} /><span>注入预览：{previewErr}</span></div>;
  }
  if (!preview) {
    return <div className="text-xs text-muted" style={{padding:"10px 2px"}}>正在生成注入预览…</div>;
  }
  const f = preview.fragments || {};
  const clip = (t) => { const s = String(t || "").replace(/\n+/g, " · ").trim(); return s.length > 130 ? s.slice(0, 130) + "…" : s; };
  const ordered = [
    ["positive_block", "narrative / observations", false],
    ["forbidden_block", "banned_pattern_block", true],
    ["metric_anchor_block", "metric_anchor_block", false],
    ["few_shot_block", "few_shot_block", false],
  ];
  const present = ordered.filter(([k]) => f[k] && String(f[k]).trim());
  const hasAnti = !!(f.anti_plagiarism_block && String(f.anti_plagiarism_block).trim());
  const prefixLen = (preview.prefix || "").length;
  if (present.length === 0 && !hasAnti) {
    return <div className="text-xs text-muted" style={{padding:"10px 2px"}}>该画像暂无可注入内容——需先抽取并合成出观察后再应用。</div>;
  }
  return (
    <>
      {present.map(([k, label, danger], i) => (
        <div key={k} className="sr-bundle-frag">
          <div className={`sr-frag-label ${danger ? "danger" : ""}`}><span className="sr-frag-ord">{i + 1}</span>{danger && <I.Ban size={11} />} {label}</div>
          <p className="sr-frag-text">{clip(f[k])}</p>
        </div>
      ))}
      <div className="sr-bundle-frag fixed">
        <div className="sr-frag-label lock"><span className="sr-frag-ord">★</span><I.ShieldCheck size={11} /> anti_plagiarism_block · 固定</div>
        <p className="sr-frag-text">{clip(f.anti_plagiarism_block || "严禁复制原文表达、人物、桥段与标志性意象。")}</p>
      </div>
      <div className="sr-budget-bar">
        <div className="sr-budget-track">
          <div className="sr-budget-fill" style={{width: Math.min(100, prefixLen / 800 * 100) + "%"}} />
        </div>
        <div className="sr-budget-legend">
          <span className="tab-num">{prefixLen}</span> / 800 字 注入预算
        </div>
      </div>
    </>
  );
}

const srCss = `
.sr-page { padding: 0; }
.sr-cols { display: grid; grid-template-columns: 300px 1fr; min-height: calc(100vh - 65px); }

/* Books rail */
.sr-books { border-right: 1px solid var(--line-1); background: var(--paper-1); display: flex; flex-direction: column; min-height: 0; }
.sr-books-head { display: flex; justify-content: space-between; align-items: end; padding: 22px 20px 14px; border-bottom: 1px solid var(--line-1); }
.sr-book-list { list-style: none; margin: 0; padding: 10px; flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.sr-book {
  display: grid; grid-template-columns: 4px 1fr auto; gap: 12px; align-items: start;
  padding: 12px 14px 12px 12px; background: var(--paper-0); border: 1px solid var(--line-1);
  border-radius: 10px; width: 100%; text-align: left; cursor: pointer; transition: border-color var(--t-fast);
}
.sr-book:hover { border-color: var(--line-2); }
.sr-book.is-active { border-color: var(--crimson); box-shadow: 0 0 0 3px var(--crimson-wash); }
.sr-book-spine { width: 4px; align-self: stretch; border-radius: 2px; background: var(--ink-3); }
.spine-crimson { background: var(--crimson); } .spine-gold { background: var(--gold); }
.spine-slate { background: var(--slate); } .spine-sage { background: var(--sage); }
.sr-book-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.sr-book-title { font-size: 14.5px; font-weight: 600; }
.sr-book-author { font-size: 12px; color: var(--ink-3); }
.sr-book-run { font-size: 11px; color: var(--ink-4); margin-top: 2px; }
.sr-book-item { position: relative; }
.sr-book-del {
  position: absolute; bottom: 9px; right: 11px;
  display: inline-flex; align-items: center; justify-content: center;
  width: 27px; height: 27px; padding: 0;
  border: 1px solid var(--line-1); border-radius: 7px;
  background: var(--paper-0); color: var(--ink-4); cursor: pointer;
  opacity: 0; pointer-events: none;
  transition: opacity var(--t-fast), color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
}
.sr-book-item:hover .sr-book-del,
.sr-book-item:focus-within .sr-book-del,
.sr-book-del.is-busy { opacity: 1; pointer-events: auto; }
.sr-book-del:hover { color: var(--crimson); border-color: var(--crimson); background: var(--crimson-wash); }
.sr-book-del:disabled { cursor: default; }
.sr-books-import {
  display: flex; align-items: center; gap: 12px; margin: 0 10px 8px; padding: 12px 14px;
  border: 1px dashed var(--line-2); border-radius: 10px; color: var(--ink-3); cursor: pointer;
}
.sr-books-import:hover { border-color: var(--ink-3); color: var(--ink-1); }
.sr-safe-note {
  display: flex; gap: 8px; align-items: flex-start; margin: 0 14px 16px;
  font-size: 11.5px; color: var(--ink-3); line-height: 1.5;
}
.sr-safe-note svg { flex-shrink: 0; margin-top: 1px; color: var(--sage); }

/* Stage */
.sr-stage { display: flex; flex-direction: column; min-width: 0; }
.sr-stage-head { display: flex; justify-content: space-between; align-items: center; padding: 20px 32px 16px; border-bottom: 1px solid var(--line-1); background: var(--paper-0); }
.sr-stage-mark { width: 42px; height: 42px; border-radius: 10px; display: grid; place-items: center; color: white; font-family: var(--font-serif); font-weight: 600; font-size: 18px; }
.sr-stage-title { font-size: 24px; letter-spacing: -0.02em; }
.sr-stepper { display: flex; align-items: center; gap: 0; padding: 14px 32px; border-bottom: 1px solid var(--line-1); background: var(--paper-0); overflow-x: auto; }
.sr-step { display: inline-flex; align-items: center; gap: 9px; background: transparent; border: 0; padding: 6px 12px; border-radius: 10px; cursor: pointer; white-space: nowrap; transition: background var(--t-fast); }
.sr-step:hover { background: var(--paper-2); }
.sr-step-mark { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 999px; background: var(--paper-2); color: var(--ink-3); flex-shrink: 0; transition: all var(--t-fast); }
.sr-step.is-done .sr-step-mark { background: var(--sage); color: white; }
.sr-step.is-active .sr-step-mark { background: var(--crimson); color: white; box-shadow: 0 0 0 4px var(--crimson-wash); }
.sr-step-text { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.15; }
.sr-step-idx { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.1em; color: var(--ink-4); }
.sr-step.is-active .sr-step-idx { color: var(--crimson); }
.sr-step-name { font-size: 13.5px; font-weight: 600; color: var(--ink-3); }
.sr-step.is-active .sr-step-name, .sr-step.is-done .sr-step-name { color: var(--ink-1); }
.sr-step-line { flex: 1 0 18px; height: 2px; background: var(--line-2); margin: 0 4px; border-radius: 1px; min-width: 18px; }
.sr-step-line.is-done { background: var(--sage); }
.sr-stage-body { flex: 1; overflow-y: auto; padding: 24px 32px 40px; }

/* Overview */
.sr-ov-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 16px; margin-bottom: 16px; }
.sr-metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.sr-metric { padding: 12px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 10px; }
.sr-metric-name { font-size: 11px; color: var(--ink-3); margin-bottom: 4px; }
.sr-metric-val { font-family: var(--font-serif); font-size: 22px; font-weight: 600; line-height: 1; }
.sr-metric-unit { font-size: 12px; color: var(--ink-3); font-family: var(--font-sans); }
.sr-metric-std { font-size: 11px; color: var(--ink-4); margin-top: 4px; }
.sr-input-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.sr-input-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 8px; }
.sr-input-name { font-size: 13px; font-weight: 500; }
.sr-input-level { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.sr-input-level.lv-high { background: var(--sage-wash); color: var(--sage); }
.sr-input-level.lv-medium { background: var(--gold-wash); color: var(--gold); }
.sr-input-level.lv-low { background: var(--slate-wash); color: var(--slate); }
.sr-input-level.lv-skip { background: var(--paper-3); color: var(--ink-4); }
.sr-calib { padding-top: 14px; border-top: 1px solid var(--line-1); }
.sr-dist { display: flex; flex-direction: column; gap: 8px; }
.sr-dist-row { display: grid; grid-template-columns: 48px 1fr 44px; gap: 12px; align-items: center; }
.sr-dist-label { font-size: 13px; color: var(--ink-2); }
.sr-dist-bar { height: 10px; background: var(--paper-2); border-radius: 999px; overflow: hidden; }
.sr-dist-fill { height: 100%; background: linear-gradient(90deg, var(--crimson), var(--gold)); border-radius: 999px; }
.sr-dist-val { font-size: 12px; color: var(--ink-2); text-align: right; }

/* Trend chart */
.sr-trend { display: flex; align-items: flex-end; gap: 6px; height: 120px; padding: 8px 4px 0; }
.sr-trend-col { flex: 1; display: flex; align-items: flex-end; height: 100%; }
.sr-trend-bar { width: 100%; background: linear-gradient(180deg, var(--crimson), var(--gold)); border-radius: 3px 3px 0 0; min-height: 4px; transition: height var(--t-base); }
.sr-trend-col:last-child .sr-trend-bar { background: var(--crimson); box-shadow: 0 0 0 2px var(--crimson-wash); }

/* Retry chain */
.sr-retry { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.sr-retry li { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 8px; font-size: 13px; }
.sr-retry b { font-family: var(--font-serif); font-size: 15px; }
.sr-retry-dot { width: 9px; height: 9px; border-radius: 50%; }
.sr-retry-dot.ok { background: var(--sage); }
.sr-retry-dot.l1 { background: var(--gold); }
.sr-retry-dot.l2 { background: var(--crimson); }
.sr-retry-dot.drop { background: var(--ink-4); }

/* Matrix */
.sr-matrix-wrap { display: grid; grid-template-columns: 1fr 380px; gap: 20px; align-items: start; }
.sr-matrix-legend { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.sr-lg { font-size: 11px; padding: 2px 10px; border-radius: 999px; font-weight: 600; }
.sr-lg-high { background: var(--sage); color: white; }
.sr-lg-medium { background: var(--gold); color: white; }
.sr-lg-low { background: var(--slate-wash); color: var(--slate); }
.sr-lg-skip { background: var(--paper-3); color: var(--ink-4); }

.sr-matrix { display: flex; flex-direction: column; gap: 8px; }
.sr-matrix-row { display: grid; grid-template-columns: 92px 1fr; gap: 12px; align-items: stretch; }
.sr-matrix-rowhead { display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 8px 10px; background: var(--paper-1); border: 1px solid var(--line-1); border-radius: 10px; }
.sr-matrix-abbr { width: 24px; height: 24px; border-radius: 6px; background: var(--ink-1); color: var(--paper-0); display: grid; place-items: center; font-family: var(--font-serif); font-weight: 600; font-size: 13px; }
.sr-matrix-layer { font-size: 12px; font-weight: 600; color: var(--ink-2); }
.sr-matrix-cells { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.sr-cell {
  display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: 10px;
  border: 1px solid var(--line-1); cursor: pointer; text-align: left; transition: all var(--t-fast);
  min-height: 78px;
}
.sr-cell.conf-high   { background: var(--sage-wash);  border-color: transparent; }
.sr-cell.conf-medium { background: var(--gold-wash);  border-color: transparent; }
.sr-cell.conf-low    { background: var(--slate-wash); border-color: transparent; }
.sr-cell.conf-skip   { background: var(--paper-2); border-style: dashed; cursor: not-allowed; opacity: 0.7; }
.sr-cell:not(.conf-skip):hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
.sr-cell.is-active { box-shadow: 0 0 0 2px var(--crimson), var(--shadow-md); }
.sr-cell-name { font-size: 13px; font-weight: 600; color: var(--ink-1); }
.sr-cell-stats { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; color: var(--ink-2); margin-top: auto; }
.sr-cell-stat b { font-family: var(--font-mono); font-weight: 600; }
.sr-cell-stat.fp { color: var(--rose); }
.sr-cell-skip { font-size: 11px; color: var(--ink-4); margin-top: auto; }

/* Cell hover tooltip */
.sr-cell { position: relative; }
.sr-cell:hover { z-index: 20; }
.sr-cell-tip {
  position: absolute;
  left: 50%;
  top: calc(100% + 8px);
  transform: translateX(-50%);
  width: 230px;
  background: var(--ink-1);
  color: var(--paper-0);
  border-radius: 10px;
  padding: 11px 13px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: var(--shadow-lg);
  z-index: 30;
  pointer-events: none;
  animation: srTipIn 0.12s ease-out;
}
.sr-cell-tip::before {
  content: "";
  position: absolute;
  top: -5px; left: 50%;
  transform: translateX(-50%) rotate(45deg);
  width: 10px; height: 10px;
  background: var(--ink-1);
}
.sr-cell-tip-conf { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--paper-2); }
.sr-cell-tip-conf .conf-dot { width: 8px; height: 8px; }
.sr-cell-tip-metric { font-size: 12px; font-family: var(--font-mono); color: var(--gold-soft); }
.sr-cell-tip-quote { font-family: var(--font-serif); font-size: 13px; line-height: 1.5; color: var(--paper-0); }
.sr-cell-tip-hint { font-size: 10.5px; color: var(--paper-3); margin-top: 2px; }
@keyframes srTipIn { from { opacity: 0; transform: translateX(-50%) translateY(-4px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }

.sr-matrix-foot { display: flex; align-items: center; gap: 18px; margin-top: 16px; padding: 14px 18px; background: var(--paper-1); border: 1px solid var(--line-1); border-radius: 12px; }
.sr-matrix-foot-stat { font-size: 13px; color: var(--ink-3); }
.sr-matrix-foot-stat b { font-size: 17px; font-family: var(--font-serif); color: var(--ink-1); margin-right: 4px; }

/* Findings drawer */
.sr-findings { position: sticky; top: 0; background: var(--paper-1); border: 1px solid var(--line-1); border-radius: 14px; display: flex; flex-direction: column; max-height: calc(100vh - 230px); overflow: hidden; }
.sr-findings-head { display: flex; justify-content: space-between; align-items: start; padding: 16px 18px; border-bottom: 1px solid var(--line-1); }
.sr-findings-filter { display: flex; gap: 6px; padding: 12px 16px; border-bottom: 1px solid var(--line-1); }
.sr-ff { display: inline-flex; align-items: center; gap: 5px; background: var(--paper-2); border: 0; padding: 5px 11px; border-radius: 999px; font-size: 12px; color: var(--ink-3); cursor: pointer; font-weight: 500; }
.sr-ff.is-active { background: var(--ink-1); color: var(--paper-0); }
.sr-findings-scroll { overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }

.sr-finding { background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 12px; padding: 14px; }
.sr-finding.is-fp { border-left: 3px solid var(--rose); }
.sr-finding.rev-approved { border-color: var(--sage); }
.sr-finding.rev-rejected { opacity: 0.6; }
.sr-rev-state { font-size: 10.5px; font-weight: 600; padding: 1px 7px; border-radius: 999px; }
.sr-rev-state.st-pending { background: var(--paper-2); color: var(--ink-3); }
.sr-rev-state.st-approved { background: var(--sage-wash); color: var(--sage); }
.sr-rev-state.st-rejected { background: var(--rose-wash); color: var(--rose); }
.sr-rev-btn { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; background: var(--paper-2); border: 1px solid var(--line-1); color: var(--ink-3); cursor: pointer; }
.sr-rev-btn:hover { color: var(--ink-1); border-color: var(--line-2); }
.sr-rev-btn.on-ok { background: var(--sage); color: white; border-color: var(--sage); }
.sr-rev-btn.on-no { background: var(--rose); color: white; border-color: var(--rose); }
.sr-finding-foot { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--line-1); }
.sr-vote { display: flex; gap: 4px; }
.sr-vote-btn { width: 28px; height: 24px; border-radius: 6px; background: var(--paper-2); border: 1px solid var(--line-1); cursor: pointer; font-size: 13px; line-height: 1; }
.sr-vote-btn:hover { border-color: var(--line-2); }
.sr-vote-btn.on { background: var(--gold-wash); border-color: var(--gold); }
.sr-finding-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sr-finding-tag { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.sr-finding-tag.tag-obs { background: var(--sage-wash); color: var(--sage); }
.sr-finding-tag.tag-fp { background: var(--rose-wash); color: var(--rose); }
.sr-finding-statement { font-size: 14px; line-height: 1.6; color: var(--ink-1); margin-bottom: 12px; }
.sr-finding-evidence-label { font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink-4); font-weight: 600; margin-bottom: 8px; }
.sr-ev { padding: 10px 12px; background: var(--paper-1); border-radius: 8px; margin-bottom: 6px; }
.sr-ev-mark { margin-bottom: 6px; }
.sr-ev-badge { font-size: 10px; font-family: var(--font-mono); padding: 2px 7px; border-radius: 4px; font-weight: 600; }
.sr-ev-badge.quote { background: var(--slate-wash); color: var(--slate); }
.sr-ev-badge.avoid { background: var(--gold-wash); color: var(--gold); }
.sr-ev-badge.syn { background: var(--rose-wash); color: var(--rose); }
.sr-ev-quote { font-size: 13.5px; line-height: 1.65; color: var(--ink-1); border-left: 2px solid var(--gold); padding-left: 10px; margin: 0 0 4px; }
.sr-ev-note { font-size: 12px; color: var(--ink-3); line-height: 1.5; }
.sr-ev-dims { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.sr-ev-dim { font-size: 10px; font-family: var(--font-mono); color: var(--ink-3); background: var(--paper-2); padding: 1px 6px; border-radius: 4px; }

/* Profile */
.sr-profile { display: grid; grid-template-columns: 1fr 300px; gap: 18px; align-items: start; }
.sr-profile-summary { font-size: 15px; line-height: 1.85; color: var(--ink-1); margin-bottom: 18px; }
.sr-profile-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line-1); margin-bottom: 16px; }
.sr-pt { background: transparent; border: 0; padding: 8px 12px; font-size: 13px; color: var(--ink-3); border-bottom: 2px solid transparent; margin-bottom: -1px; cursor: pointer; font-weight: 500; }
.sr-pt.is-active { color: var(--ink-1); border-bottom-color: var(--crimson); font-weight: 600; }
.sr-profile-dims { display: flex; flex-direction: column; gap: 4px; }
.sr-pd-row { display: grid; grid-template-columns: 120px 12px 1fr; gap: 12px; align-items: center; padding: 8px 10px; border-radius: 8px; }
.sr-pd-row:hover { background: var(--paper-2); }
.sr-pd-path { font-size: 13px; font-weight: 500; }
.conf-dot { width: 10px; height: 10px; border-radius: 50%; }
.conf-dot.conf-high { background: var(--sage); }
.conf-dot.conf-medium { background: var(--gold); }
.conf-dot.conf-low { background: var(--slate); }
.sr-pd-counts { font-size: 12px; color: var(--ink-3); }

.sr-profile-side { display: flex; flex-direction: column; gap: 14px; }
.sr-baseline { display: flex; flex-direction: column; gap: 8px; }
.sr-baseline-row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; line-height: 1.4; }
.sr-baseline-row > span:last-child { white-space: nowrap; }
.sr-sample-index { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.sr-sample-index li { display: flex; justify-content: space-between; padding: 6px 10px; background: var(--paper-0); border-radius: 6px; font-size: 12.5px; }
.sr-sample-index b { font-family: var(--font-serif); }

/* Preview */
.sr-preview { display: flex; flex-direction: column; gap: 10px; }
.sr-preview-head { display: flex; justify-content: space-between; align-items: center; }
.sr-pv-card { background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 10px; padding: 14px; }
.sr-pv-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.sr-pv-scores { margin-left: auto; display: flex; gap: 10px; font-size: 11.5px; font-family: var(--font-mono); color: var(--ink-3); }
.sr-pv-text { font-size: 15px; line-height: 1.8; color: var(--ink-1); }

/* Apply */
.sr-apply { display: grid; grid-template-columns: 1fr 320px; gap: 18px; align-items: start; }
.sr-apply-main { display: flex; flex-direction: column; gap: 16px; }

/* Apply sub-tabs */
.sr-apply-subtabs { display: flex; gap: 6px; flex-wrap: wrap; }
.sr-ast { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; background: var(--paper-1); border: 1px solid var(--line-1); border-radius: 999px; font-size: 13px; color: var(--ink-3); cursor: pointer; font-weight: 500; }
.sr-ast:hover { color: var(--ink-1); border-color: var(--line-2); }
.sr-ast.is-active { background: var(--ink-1); color: var(--paper-0); border-color: var(--ink-1); }
.sr-ast-count { font-family: var(--font-mono); font-size: 10.5px; padding: 0 5px; border-radius: 999px; background: var(--crimson); color: white; }

/* Layer stack */
.sr-stack { display: flex; flex-direction: column; gap: 8px; }
.sr-stack-layer { display: grid; grid-template-columns: 64px 1fr; gap: 12px; align-items: center; padding: 12px 14px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 10px; }
.sr-stack-rank { display: grid; place-items: center; padding: 6px 0; border-radius: 8px; font-family: var(--font-mono); font-size: 11px; font-weight: 600; }
.rank-slate { background: var(--slate-wash); color: var(--slate); }
.rank-crimson { background: var(--crimson-wash); color: var(--crimson); }
.rank-gold { background: var(--gold-wash); color: var(--gold); }
.rank-sage { background: var(--sage-wash); color: var(--sage); }
.sr-stack-body { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.sr-stack-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sr-stack-target { font-size: 14px; font-weight: 600; }
.sr-stack-onstage { font-size: 11.5px; color: var(--gold); }
.sr-stack-frags { font-size: 11px; color: var(--ink-3); font-family: var(--font-mono); margin-left: auto; }
.sr-stack-budget { display: flex; align-items: center; gap: 10px; }
.sr-stack-budget-track { flex: 1; height: 6px; background: var(--paper-2); border-radius: 3px; overflow: hidden; }
.sr-stack-budget-fill { height: 100%; border-radius: 3px; }
.fill-slate { background: var(--slate); } .fill-crimson { background: var(--crimson); } .fill-gold { background: var(--gold); } .fill-sage { background: var(--sage); }
.sr-stack-weight { font-size: 11px; color: var(--ink-3); }
.sr-stack-tokens { font-size: 12px; font-weight: 600; color: var(--ink-1); min-width: 52px; text-align: right; }
.sr-stack-note { display: flex; gap: 8px; align-items: flex-start; margin-top: 14px; padding: 12px 14px; background: var(--slate-wash); border-radius: 10px; font-size: 12px; line-height: 1.6; color: var(--slate); }
.sr-stack-note svg { flex-shrink: 0; margin-top: 2px; }
.sr-stack-note code { font-family: var(--font-mono); font-size: 11px; background: rgba(0,0,0,0.06); padding: 1px 5px; border-radius: 4px; }

/* Few-shot */
.sr-fewshot-warn { display: flex; gap: 8px; align-items: center; padding: 10px 12px; background: var(--gold-wash); border-radius: 8px; font-size: 12.5px; color: #6a4d1d; margin-bottom: 12px; }
.sr-fewshot-list { display: flex; flex-direction: column; gap: 10px; }
.sr-fewshot-item { padding: 12px 14px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 10px; }
.sr-fewshot-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sr-fewshot-id { font-family: var(--font-mono); font-size: 11px; color: var(--ink-3); margin-left: auto; }
.sr-fewshot-text { font-size: 14px; line-height: 1.7; color: var(--ink-1); border-left: 2px solid var(--gold); padding-left: 12px; }

/* Banned terms */
.sr-banned-add { display: flex; gap: 8px; align-items: center; margin-bottom: 14px; }
.sr-banned-add .input { flex: 1; }
.sr-banned-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.sr-banned-item { display: flex; align-items: center; gap: 10px; padding: 9px 12px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 8px; }
.sr-banned-scope { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.sr-banned-scope.sc-generation { background: var(--crimson-wash); color: var(--crimson); }
.sr-banned-scope.sc-extraction { background: var(--slate-wash); color: var(--slate); }
.sr-banned-term { font-size: 14px; font-weight: 600; }
.sr-banned-hint { font-size: 12px; color: var(--ink-3); }
.sr-banned-preset { font-size: 10.5px; color: var(--ink-4); background: var(--paper-2); padding: 1px 6px; border-radius: 4px; }
.sr-banned-item .btn { margin-left: auto; }
.sr-task-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.sr-task { display: flex; flex-direction: column; gap: 2px; padding: 9px 14px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 10px; cursor: pointer; text-align: left; }
.sr-task.is-active { border-color: var(--crimson); background: var(--crimson-wash); }
.sr-task-name { font-size: 13px; font-weight: 600; }
.sr-task-def { font-size: 11px; color: var(--ink-3); font-family: var(--font-mono); }
.sr-strat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.sr-strat { display: flex; flex-direction: column; gap: 4px; padding: 14px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 10px; cursor: pointer; text-align: left; }
.sr-strat.is-active { border-color: var(--crimson); box-shadow: 0 0 0 2px var(--crimson-wash); }
.sr-strat-badge { width: 38px; height: 24px; border-radius: 6px; background: var(--ink-1); color: var(--paper-0); display: grid; place-items: center; font-family: var(--font-mono); font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.sr-strat.is-active .sr-strat-badge { background: var(--crimson); }
.sr-strat-title { font-size: 13.5px; font-weight: 600; }
.sr-strat-desc { font-size: 11.5px; color: var(--ink-3); line-height: 1.4; }

.sr-intensity-val { font-family: var(--font-serif); font-size: 24px; font-weight: 600; color: var(--crimson); }
.sr-range { width: 100%; accent-color: var(--crimson); height: 6px; margin: 8px 0; }
.sr-intensity-ticks { display: flex; justify-content: space-between; font-size: 11px; color: var(--ink-4); }
.sr-intensity-readout { display: flex; align-items: center; gap: 8px; margin-top: 14px; padding: 10px 12px; background: var(--gold-wash); border-radius: 8px; font-size: 12.5px; color: #6a4d1d; }
.sr-intensity-readout b { font-family: var(--font-serif); }
.sr-intensity-readout svg { color: var(--gold); }

.sr-dimselect { display: flex; flex-direction: column; gap: 12px; }
.sr-ds-layer-name { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; margin-bottom: 6px; }
.sr-ds-cells { display: flex; flex-wrap: wrap; gap: 6px; }
.sr-ds-cell { display: inline-flex; align-items: center; gap: 5px; padding: 6px 12px; background: var(--paper-0); border: 1px solid var(--line-1); border-radius: 999px; font-size: 12.5px; color: var(--ink-2); cursor: pointer; font-weight: 500; }
.sr-ds-cell.is-on { background: var(--crimson); color: white; border-color: var(--crimson); }
.sr-ds-cell.is-disabled { opacity: 0.4; cursor: not-allowed; border-style: dashed; }

/* Apply side */
.sr-apply-side { display: flex; flex-direction: column; gap: 14px; position: sticky; top: 0; }
.sr-bundle-frag { padding: 8px 0; border-bottom: 1px dashed var(--line-1); }
.sr-frag-label { font-size: 10.5px; font-family: var(--font-mono); color: var(--ink-3); margin-bottom: 3px; display: flex; align-items: center; gap: 4px; }
.sr-frag-label.danger { color: var(--rose); }
.sr-frag-label.lock { color: var(--sage); }
.sr-frag-text { font-size: 12.5px; color: var(--ink-1); line-height: 1.5; }
.sr-bundle-frag.fixed { background: var(--sage-wash); margin: 4px -8px 0; padding: 8px; border-radius: 8px; border-bottom: 0; }
.sr-frag-ord { display: inline-grid; place-items: center; width: 15px; height: 15px; border-radius: 4px; background: var(--ink-1); color: var(--paper-0); font-size: 9px; font-family: var(--font-mono); font-weight: 600; margin-right: 2px; }
.sr-bundle-meta { display: flex; gap: 8px; margin-top: 10px; font-size: 11px; color: var(--ink-3); font-family: var(--font-mono); }
.sr-budget-bar { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--line-1); }
.sr-budget-track { height: 6px; background: var(--paper-2); border-radius: 3px; overflow: hidden; margin-bottom: 5px; }
.sr-budget-fill { height: 100%; background: linear-gradient(90deg, var(--sage), var(--gold)); border-radius: 3px; }
.sr-budget-legend { font-size: 11px; color: var(--ink-3); }
.sr-budget-legend .tab-num { color: var(--ink-1); font-weight: 600; }

/* Anti-drift */
.sr-drift-track { display: flex; align-items: center; gap: 0; }
.sr-drift-seg { display: flex; align-items: center; flex: 1; }
.sr-drift-bar { height: 8px; flex: 1; background: linear-gradient(90deg, var(--crimson-wash), var(--crimson)); border-radius: 4px; }
.sr-drift-tick { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; background: var(--crimson); color: white; flex-shrink: 0; margin: 0 -2px; z-index: 1; }
.sr-scope { display: flex; gap: 4px; padding: 2px; background: var(--paper-2); border-radius: 8px; margin-bottom: 12px; }
.sr-scope-btn { flex: 1; background: transparent; border: 0; padding: 6px; border-radius: 6px; font-size: 12.5px; font-weight: 600; color: var(--ink-3); cursor: pointer; }
.sr-scope-btn.is-active { background: var(--paper-0); color: var(--ink-1); box-shadow: var(--shadow-sm); }
.sr-bindings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.sr-bindings li { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--paper-0); border-radius: 8px; }
.sr-bindings li .text-sm { flex: 1; }

@media (max-width: 1280px) {
  .sr-matrix-wrap { grid-template-columns: 1fr; }
  .sr-findings { position: static; max-height: none; }
  .sr-profile, .sr-apply { grid-template-columns: 1fr; }
  .sr-ov-grid { grid-template-columns: 1fr; }
}
@media (max-width: 1000px) {
  .sr-cols { grid-template-columns: 240px 1fr; }
  .sr-matrix-cells, .sr-strat-row { grid-template-columns: repeat(2, 1fr); }
  .sr-metric-grid { grid-template-columns: repeat(2, 1fr); }
}
`;

/* ==========================================================
   FE-ALIGN F5：参考书库接 style_reference v2。
   - 书库列表/导入/删除/重跑/重分类走真实 API（无 LLM 即可用的部分）；
   - 后端有真实书时列表以后端为准，否则保留演示书（流水线展示）；
   - 矩阵/画像/回测/注入各 stage 的内容仍为演示——它们展示的是 LLM
     抽取产物（findings/profile），LLM 关闭时无真实数据可渲染（账本记录）。
   ========================================================== */
const SR_DEMO_BOOKS = SR_BOOKS.slice();
let SR_REAL = false;

function srMapStatus(s) {
  if (s === "ready") return "ready";
  if (/extract|run/i.test(s || "")) return "extracting";
  return "pending";
}

async function srSyncBooks() {
  let rows = [];
  try {
    const { apiGet } = await import("./lib/client.js");
    rows = ((await apiGet("/api/v2/style-reference/books")) || {}).books || [];
  } catch (e) { return; }
  if (!rows.length) {
    if (SR_REAL) { SR_BOOKS = SR_DEMO_BOOKS.slice(); SR_REAL = false; window.dispatchEvent(new CustomEvent("sr:books-changed")); }
    return;
  }
  const colors = ["crimson", "gold", "slate", "sage"];
  SR_BOOKS = rows.map((b, i) => ({
    id: b.book_id,
    title: b.title,
    author: b.author_label || "未署名",
    chars: b.total_chars || 0,
    status: srMapStatus(b.status),
    profiles: 0,
    run: b.status === "ready" ? "已导入 · 待抽取" : b.status,
    color: colors[i % colors.length],
    real: true,
  }));
  SR_REAL = true;
  window.dispatchEvent(new CustomEvent("sr:books-changed"));
}

/* 导入参考书：文件选择 → POST import-upload（multipart，带幂等键） */
function srImportBook() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".txt,.md,.epub,.docx";
  input.onchange = async () => {
    const f = input.files && input.files[0];
    if (!f) return;
    const title = (window.prompt("书名（用于书库显示）", f.name.replace(/\.[^.]+$/, "")) || "").trim();
    if (!title) return;
    try {
      const { buildUrl, getOperatorRef } = await import("./lib/client.js");
      const fd = new FormData();
      fd.append("file", f, f.name);
      fd.append("title", title);
      // segments_only:抽取按段落分批送 LLM(从不整本上送)。local_only 会被后端
      // 策略层拒绝一切云端抽取(STYLE_REFERENCE_CLOUD_POLICY_BLOCKED),仅适合纯本地场景。
      fd.append("cloud_policy", "segments_only");
      const res = await fetch(buildUrl("/api/v2/style-reference/books/import-upload"), {
        method: "POST",
        headers: { "X-Idempotency-Key": "sr-import-" + Date.now().toString(36), "X-Operator-Ref": getOperatorRef() },
        body: fd,
      });
      const body = await res.json();
      if (!body.ok) throw new Error((body.error && body.error.message) || "导入失败");
      await srSyncBooks();
      window.alert(`已导入《${title}》（${(((body.data || {}).book || {}).total_chars || 0).toLocaleString()} 字）。`);
    } catch (e) { window.alert("导入失败：" + (e.message || e)); }
  };
  input.click();
}

/* 头部动作（真实书）：重跑抽取 / 重新分类。LLM 未启用时给明确引导。 */
async function srBookAction(action, bookId) {
  try {
    const { apiPost } = await import("./lib/client.js");
    if (action === "rerun") {
      // 后台模式：立即返回 run_id，按 coverage_json.progress 轮询(2.5s),
      // 全 16 维抽取可达数分钟,同步等待会撞 HTTP 超时
      const res = await apiPost(`/api/v2/style-reference/books/${bookId}/runs`, { background: true });
      const runId = res && res.run_id;
      window.alert("抽取已在后台启动（按层推进），完成后会提示。");
      if (runId) srPollRun(runId);
    } else if (action === "reclassify") {
      await apiPost(`/api/v2/style-reference/books/${bookId}/reclassify`, {});
      window.alert("已重新分类段落。");
    }
  } catch (e) {
    if (e && e.code === "STYLE_REFERENCE_CLOUD_POLICY_BLOCKED") {
      window.alert("这本书的云端策略是「仅本地」，风格抽取需要把段落送 LLM 分析。请删除后以「按段落送云」策略重新导入。");
    } else if (e && (e.code === "STYLE_REFERENCE_LLM_REQUIRED" || /llm/i.test(e.code || ""))) {
      window.alert("风格抽取需要先启用 LLM：请到「系统设置 → 模型与接入」配置并开启后重试。");
    } else {
      window.alert("操作失败：" + (e.message || e));
    }
  }
  await srSyncBooks();
}

/* 后台抽取轮询：层粒度进度，完成/失败时提示并刷新书库。最长轮询 20 分钟。 */
async function srPollRun(runId) {
  const { apiGet } = await import("./lib/client.js");
  const startedAt = Date.now();
  const tick = async () => {
    if (Date.now() - startedAt > 20 * 60 * 1000) return;
    let run = null;
    try { run = ((await apiGet(`/api/v2/style-reference/runs/${runId}`)) || {}).run || null; } catch (e) { /* 网络抖动下一轮再试 */ }
    const status = run && run.status;
    if (status === "done") {
      await srSyncBooks();
      window.alert("风格抽取完成，维度矩阵已可查看。");
      return;
    }
    if (status === "failed" || status === "cancelled") {
      await srSyncBooks();
      window.alert(status === "failed" ? "风格抽取失败，可重试或查看系统日志。" : "风格抽取已取消。");
      return;
    }
    setTimeout(tick, 2500);
  };
  setTimeout(tick, 2500);
}

async function srDeleteBook(bookId) {
  const { buildUrl, getOperatorRef } = await import("./lib/client.js");
  const res = await fetch(buildUrl(`/api/v2/style-reference/books/${bookId}`), {
    method: "DELETE",
    // book_id 由内容 checksum 决定（同内容重导=同 id），删除键必须带熵，
    // 否则幂等层会重放上一次的成功响应而不真正执行
    headers: { "X-Idempotency-Key": `sr-del-${bookId}-${Date.now().toString(36)}`, "X-Operator-Ref": getOperatorRef() },
  });
  const body = await res.json();
  if (!body.ok) throw new Error((body.error && body.error.message) || "删除失败");
  await srSyncBooks();
  return true;
}

/* ==========================================================
   深层页真后端 store（按 book 懒加载 profile + bindings）
   有真画像 → 注入应用走真后端；无（演示书 / 未合成）→ 回退演示。
   范式同 srSyncBooks：内存缓存 + 懒加载 + 防重 + window 事件广播。
   ========================================================== */
const SR_DEEP = {};            // bookId -> { profileId, profile, bindings, loaded, error }
const SR_DEEP_FETCHING = {};

function srDeepFor(bookId) { return SR_DEEP[bookId] || null; }

async function srLoadDeep(bookId, { force = false } = {}) {
  if (!bookId) return null;
  if (!force && SR_DEEP[bookId]) return SR_DEEP[bookId];
  if (SR_DEEP_FETCHING[bookId]) return SR_DEEP_FETCHING[bookId];
  SR_DEEP_FETCHING[bookId] = (async () => {
    const out = {
      book: null, runId: null, run: null,
      findingsByDim: {}, dimCounts: {},
      profileId: null, profile: null, bindings: [],
      loaded: true, error: null,
    };
    try {
      const { apiGet } = await import("./lib/client.js");
      // 1. 书详情（stats_json：metrics / input_assessment / 段型分布 / 分类器校准）
      try {
        const r = await apiGet(`/api/v2/style-reference/books/${encodeURIComponent(bookId)}`);
        out.book = (r && r.book) || null;
      } catch (e) { /* 详情失败不致命 */ }
      // 2. 最新 run（优先 done，否则最新一条）
      try {
        const rr = await apiGet(`/api/v2/style-reference/books/${encodeURIComponent(bookId)}/runs`);
        const runs = (rr && rr.runs) || [];
        out.run = runs.find(r => r.status === "done") || runs[0] || null;
        out.runId = out.run ? out.run.run_id : null;
      } catch (e) { /* 无 run 列表则矩阵走演示 */ }
      // 3. 该 run 的 findings（含证据）→ 按 sub_dim 分组 + 计数
      if (out.runId) {
        try {
          const fr = await apiGet(`/api/v2/style-reference/runs/${out.runId}/findings?include=evidence`);
          for (const f of (fr && fr.findings) || []) {
            const dim = f.sub_dimension;
            if (!out.findingsByDim[dim]) out.findingsByDim[dim] = { observations: [], forbidden_patterns: [] };
            (f.finding_kind === "forbidden_pattern" ? out.findingsByDim[dim].forbidden_patterns : out.findingsByDim[dim].observations).push(f);
          }
          for (const [dim, g] of Object.entries(out.findingsByDim)) {
            const confs = g.observations.map(o => o.confidence);
            const conf = confs.includes("high") ? "high" : confs.includes("medium") ? "medium" : "low";
            const q = [...g.observations, ...g.forbidden_patterns].reduce((s, f) => s + ((f.evidence || []).length), 0);
            out.dimCounts[dim] = { obs: g.observations.length, fp: g.forbidden_patterns.length, q, conf };
          }
        } catch (e) { /* findings 失败则矩阵走演示 */ }
      }
      // 4. profile + bindings
      try {
        const pr = await apiGet(`/api/v2/style-reference/profiles?book_id=${encodeURIComponent(bookId)}`);
        const profiles = (pr && pr.profiles) || [];
        const chosen = profiles.find(p => p.status === "active") || profiles[profiles.length - 1] || null;
        out.profileId = chosen ? chosen.profile_id : null;
        out.profile = chosen;
        if (chosen) {
          try {
            const b = await apiGet(`/api/v2/style-reference/profiles/${chosen.profile_id}/bindings`);
            out.bindings = (b && b.bindings) || [];
          } catch (e) { /* 绑定拉取失败不致命 */ }
        }
      } catch (e) { /* profile 失败则画像/应用走演示 */ }
    } catch (e) {
      out.error = (e && e.message) || String(e);
    } finally {
      SR_DEEP[bookId] = out;
      delete SR_DEEP_FETCHING[bookId];
      window.dispatchEvent(new CustomEvent("sr:deep-changed"));
    }
    return SR_DEEP[bookId];
  })();
  return SR_DEEP_FETCHING[bookId];
}

/* dryrun 注入预览（不写盘）：返回真实 fragments + prefix。失败抛 ApiRequestError。 */
async function srInjectionPreview(profileId, body) {
  const { apiPost } = await import("./lib/client.js");
  return apiPost(`/api/v2/style-reference/profiles/${profileId}/injection-preview`, body);
}

/* 解绑：DELETE binding 后强制重载该 book 的深层数据。 */
async function srUnbind(bindingId, bookId) {
  const { apiDelete } = await import("./lib/client.js");
  await apiDelete(`/api/v2/style-reference/bindings/${bindingId}`);
  await srLoadDeep(bookId, { force: true });
  return true;
}

/* 合成画像：POST synthesize（需 LLM）后强制重载。LLM 未启用时抛 ApiRequestError(409)。 */
async function srSynthesize(runId, bookId) {
  const { apiPost } = await import("./lib/client.js");
  const r = await apiPost(`/api/v2/style-reference/runs/${runId}/synthesize`, {});
  await srLoadDeep(bookId, { force: true });
  return r;
}

/* finding 审核（approved / rejected / pending）后强制重载。 */
async function srReviewFinding(findingId, decision, bookId) {
  const { apiPost } = await import("./lib/client.js");
  await apiPost(`/api/v2/style-reference/findings/${findingId}/review`, { decision });
  await srLoadDeep(bookId, { force: true });
  return true;
}

/* 立项 B — finding 用户反馈(👍/👎):聚合后按阈值调档 confidence,强制重载使 deep 体现。 */
async function srFindingFeedback(findingId, vote, bookId) {
  const { apiPost } = await import("./lib/client.js");
  await apiPost(`/api/v2/style-reference/findings/${findingId}/user-feedback`, { vote });
  await srLoadDeep(bookId, { force: true });
  return true;
}

/* 画像预览：生成 3 段示例 + 自跑回测（需 LLM）。 */
async function srPreviewSamples(profileId) {
  const { apiPost } = await import("./lib/client.js");
  return apiPost(`/api/v2/style-reference/profiles/${profileId}/preview`, {});
}

setTimeout(() => srSyncBooks(), 800); // 启动水合
window.addEventListener("hashchange", () => {
  if ((location.hash || "").indexOf("styleref") >= 0) srSyncBooks();
});

Object.assign(window, {
  WsStyleRef, srSyncBooks, srImportBook, srBookAction, srDeleteBook,
  srLoadDeep, srDeepFor, srInjectionPreview, srUnbind,
  srSynthesize, srReviewFinding, srFindingFeedback, srPreviewSamples,
});

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { WsStyleRef };
