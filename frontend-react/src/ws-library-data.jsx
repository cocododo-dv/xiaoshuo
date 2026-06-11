import { apiGet } from "./lib/client.js";

/* global window */
/* ==========================================================
   Library data — 档案库 / 潮汐档案 故事圣经
   One connected dataset across categories, with cross-links.
   Each entry: { id, cat, name, code, kind, accent, tags,
                 summary, blurb, facts[], links[], appears[],
                 state?, arc?, updated, pinned? }
   ========================================================== */

const LIB_CATS = [
  { id: "people",    label: "人物",   icon: "Users",     accent: "crimson", noun: "位角色" },
  { id: "world",     label: "世界",   icon: "MapPin",    accent: "gold",    noun: "处设定" },
  { id: "events",    label: "大事记", icon: "Clock",     accent: "slate",   noun: "起事件" },
  { id: "refs",      label: "参考",   icon: "BookOpen",  accent: "sage",    noun: "本参考" },
  { id: "profiles",  label: "风格",   icon: "Sparkles",  accent: "rose",    noun: "组画像" },
  { id: "knowledge", label: "知识",   icon: "FileText",  accent: "ink",     noun: "条沉淀" },
];

const LIB_SEED_ENTRIES = [
  /* ---------------- 人物 ---------------- */
  {
    id: "lin-cen", cat: "people", name: "林岑", code: "人·01", kind: "主角",
    accent: "crimson", pinned: true, updated: "今晨", glyph: "林",
    summary: "档案修复师 · POV", tags: ["内敛", "强迫式", "POV", "可靠叙述者"],
    arc: { from: "克制", to: "释放", note: "三幕逐步松动" },
    blurb: "潮汐城旧城档案馆的修复师。习惯把人也当作待修的卷宗——先除尘，再辨认，最后才敢动手。全书第一人称，叙述冷而准，越接近真相，句子越短。",
    facts: [
      { k: "年龄", v: "28" }, { k: "职业", v: "档案修复师" },
      { k: "立场", v: "追查真相" }, { k: "声音", v: "冷峻短句" },
    ],
    links: [
      { id: "zhou-lan", rel: "对立 · 主任" },
      { id: "cen-fu", rel: "父亲 · 已故" },
      { id: "a-ke", rel: "搭档" },
      { id: "old-archive", rel: "工作于" },
    ],
    appears: ["CH01", "CH02", "CH05", "CH07", "CH08"],
  },
  {
    id: "zhou-lan", cat: "people", name: "周岚", code: "人·02", kind: "对立",
    accent: "slate", updated: "昨天", glyph: "周",
    summary: "档案学院主任", tags: ["权威", "伪造者", "克制"],
    arc: { from: "维护", to: "崩塌", note: "体面层层剥落" },
    blurb: "档案学院主任，体制的脸面。她相信有些记录值得为更大的秩序而被改写——直到改写反噬其身。与林岑的对峙是全书的主轴。",
    facts: [
      { k: "年龄", v: "53" }, { k: "职业", v: "学院主任" },
      { k: "秘密", v: "档案重写" }, { k: "弱点", v: "母亲的旧事" },
    ],
    links: [
      { id: "lin-cen", rel: "宿敌" },
      { id: "zhou-mu", rel: "母亲" },
      { id: "gu-guan", rel: "前任 · 师承" },
      { id: "academy", rel: "执掌" },
    ],
    appears: ["CH03", "CH05", "CH07"],
  },
  {
    id: "cen-fu", cat: "people", name: "岑父", code: "人·03", kind: "重要",
    accent: "ink", updated: "上周", glyph: "岑",
    summary: "前档案员 · 已故", tags: ["伏笔", "信件", "影像"],
    arc: { from: "缺席", to: "在场", note: "通过遗物逐渐显形" },
    blurb: "林岑的父亲，二十年前的档案员，死于第三潮汐事件。全程不出场，只以信件、影像与一卷未归档的录音存在——却是推动林岑的真正引擎。",
    facts: [
      { k: "状态", v: "已故" }, { k: "职业", v: "前档案员" },
      { k: "遗留", v: "一卷录音" }, { k: "作用", v: "动机源" },
    ],
    links: [
      { id: "lin-cen", rel: "女儿" },
      { id: "third-tide", rel: "罹难于" },
      { id: "echo-record", rel: "留下" },
    ],
    appears: ["CH02 · 回忆", "CH08"],
  },
  {
    id: "a-ke", cat: "people", name: "阿恪", code: "人·04", kind: "次要",
    accent: "gold", updated: "三天前", glyph: "恪",
    summary: "档案技术员 · 搭档", tags: ["搭档", "黑色幽默", "技术流"],
    arc: { from: "协助", to: "决裂", note: "利益处分道扬镳" },
    blurb: "档案馆的技术员，林岑唯一的搭档。用玩笑稀释紧张，却在关键处选择了自保。他的离开是中段的情绪低点。",
    facts: [
      { k: "年龄", v: "30" }, { k: "职业", v: "档案技术员" },
      { k: "功能", v: "调剂 · 反衬" }, { k: "结局", v: "决裂离场" },
    ],
    links: [
      { id: "lin-cen", rel: "搭档 → 决裂" },
      { id: "data-center", rel: "出入" },
    ],
    appears: ["CH04", "CH06"],
  },
  {
    id: "zhou-mu", cat: "people", name: "周岚母亲", code: "人·05", kind: "次要",
    accent: "ink", updated: "上周", glyph: "母",
    summary: "回忆中的一段", tags: ["历史", "回忆"],
    arc: { from: "—", to: "—", note: "仅以回忆呈现" },
    blurb: "周岚崩塌的源头。她那一代人对档案的信仰与背叛，在一段插叙里交代，解释了周岚为何走到今天。",
    facts: [
      { k: "年龄", v: "78" }, { k: "出场", v: "插叙 · 一段" },
      { k: "作用", v: "动机回溯" }, { k: "关联", v: "学院旧史" },
    ],
    links: [{ id: "zhou-lan", rel: "女儿" }, { id: "academy", rel: "旧事牵连" }],
    appears: ["CH07 · 插叙"],
  },
  {
    id: "gu-guan", cat: "people", name: "顾老馆长", code: "人·06", kind: "次要",
    accent: "ink", updated: "上周", glyph: "顾",
    summary: "前任馆长 · 师承", tags: ["传授", "旧制度"],
    arc: { from: "—", to: "—", note: "象征旧秩序" },
    blurb: "旧城档案馆的前任馆长，林岑与周岚共同的师辈。他立下的规矩，正是两人冲突的尺度。",
    facts: [
      { k: "年龄", v: "71" }, { k: "身份", v: "前任馆长" },
      { k: "象征", v: "旧秩序" }, { k: "出场", v: "短 · 回忆" },
    ],
    links: [{ id: "lin-cen", rel: "师辈" }, { id: "zhou-lan", rel: "师辈" }, { id: "old-archive", rel: "旧主事" }],
    appears: ["CH05 · 回忆"],
  },

  /* ---------------- 世界 ---------------- */
  {
    id: "old-archive", cat: "world", name: "旧城档案馆", code: "世·01", kind: "地点",
    accent: "gold", updated: "今晨", glyph: "馆",
    summary: "故事的主舞台", tags: ["主场景", "潮湿", "迷宫式"],
    blurb: "潮汐城最老的建筑之一，半沉于潮位线之下。地下书库常年返潮，纸张需要不断修复——林岑的世界从这里展开。",
    facts: [
      { k: "类别", v: "地点 · 建筑" }, { k: "区位", v: "旧城 · 潮位线下" },
      { k: "氛围", v: "潮湿 · 幽闭" }, { k: "出现", v: "贯穿全书" },
    ],
    links: [{ id: "lin-cen", rel: "工作地" }, { id: "salt-tower", rel: "比邻" }, { id: "tide-line", rel: "受制于" }],
    appears: ["CH01", "CH02", "CH05", "CH08"],
  },
  {
    id: "salt-tower", cat: "world", name: "盐钟塔", code: "世·02", kind: "地点",
    accent: "gold", updated: "本周", glyph: "塔",
    summary: "测潮的旧塔 · 关键意象", tags: ["意象", "金属", "钟声"],
    blurb: "海岸边的测潮塔，钟体由盐与铁锻成。每逢高潮鸣响一次，是全城的时间。结构图见「知识 · 盐钟塔结构」。",
    facts: [
      { k: "类别", v: "地点 · 地标" }, { k: "材质", v: "盐 · 铁" },
      { k: "功能", v: "测潮 · 报时" }, { k: "象征", v: "无法改写的时间" },
    ],
    links: [{ id: "salt-reading", rel: "产出" }, { id: "tower-structure", rel: "结构资料" }, { id: "old-archive", rel: "比邻" }],
    appears: ["CH03", "CH06", "CH08"],
  },
  {
    id: "third-tide-zone", cat: "world", name: "第三潮汐区", code: "世·03", kind: "地点",
    accent: "gold", updated: "上周", glyph: "区",
    summary: "事故发生地", tags: ["废弃", "禁区"],
    blurb: "二十年前事故的发生地，此后被划为禁区。岑父的最后行踪止于此处。",
    facts: [
      { k: "类别", v: "地点 · 区域" }, { k: "现状", v: "禁区 · 废弃" },
      { k: "关联", v: "第三潮汐事件" }, { k: "出现", v: "回忆 · 终章" },
    ],
    links: [{ id: "third-tide", rel: "事发地" }, { id: "cen-fu", rel: "最后行踪" }],
    appears: ["CH02 · 回忆", "CH08"],
  },
  {
    id: "data-center", cat: "world", name: "潮汐数据中心", code: "世·04", kind: "地点",
    accent: "gold", updated: "上周", glyph: "心",
    summary: "新旧档案的对峙", tags: ["现代", "对照"],
    blurb: "新建的数字档案中心，与旧城档案馆形成新旧两极。二次备份制度从这里推行。",
    facts: [
      { k: "类别", v: "地点 · 机构" }, { k: "对照", v: "旧城档案馆" },
      { k: "制度", v: "二次备份" }, { k: "出现", v: "中段" },
    ],
    links: [{ id: "backup", rel: "推行" }, { id: "a-ke", rel: "出入" }],
    appears: ["CH04", "CH06"],
  },
  {
    id: "academy", cat: "world", name: "档案学院", code: "世·05", kind: "组织",
    accent: "gold", updated: "昨天", glyph: "院",
    summary: "权力中枢 · 组织", tags: ["组织", "权威"],
    blurb: "培养档案员、也制定规则的机构，周岚执掌于此。学院改组（2011）是其权力转折。",
    facts: [
      { k: "类别", v: "组织 · 机构" }, { k: "掌权", v: "周岚" },
      { k: "转折", v: "2011 改组" }, { k: "立场", v: "秩序优先" },
    ],
    links: [{ id: "zhou-lan", rel: "主任" }, { id: "academy-reform", rel: "经历" }, { id: "rewrite-crime", rel: "界定" }],
    appears: ["CH03", "CH07"],
  },
  {
    id: "research-assoc", cat: "world", name: "潮汐研究协会", code: "世·06", kind: "组织",
    accent: "gold", updated: "上周", glyph: "会",
    summary: "民间力量", tags: ["组织", "民间"],
    blurb: "独立于学院之外的研究团体，掌握部分未被官方收录的记录，是林岑的外援。",
    facts: [
      { k: "类别", v: "组织 · 民间" }, { k: "立场", v: "存疑 · 求真" },
      { k: "作用", v: "提供线索" }, { k: "出现", v: "中后段" },
    ],
    links: [{ id: "lin-cen", rel: "外援" }, { id: "academy", rel: "张力" }],
    appears: ["CH05", "CH06"],
  },
  {
    id: "salt-reading", cat: "world", name: "盐钟读数", code: "世·07", kind: "术语",
    accent: "gold", updated: "本周", glyph: "读",
    summary: "术语 · 计时单位", tags: ["术语", "计时"],
    blurb: "以盐钟塔每次鸣响为一格的本地计时法，全书用作时间锚点。",
    facts: [
      { k: "类别", v: "术语" }, { k: "来源", v: "盐钟塔" },
      { k: "用途", v: "叙事时间锚" }, { k: "频次", v: "高频" },
    ],
    links: [{ id: "salt-tower", rel: "来自" }],
    appears: ["贯穿"],
  },
  {
    id: "echo-record", cat: "world", name: "回声记录", code: "世·08", kind: "术语",
    accent: "gold", updated: "上周", glyph: "声",
    summary: "术语 · 录音档案", tags: ["术语", "声音", "伏笔"],
    blurb: "档案馆收录环境声的特殊门类。岑父留下的那一卷，是揭示真相的钥匙。",
    facts: [
      { k: "类别", v: "术语 · 物件" }, { k: "形态", v: "录音卷" },
      { k: "关键", v: "岑父遗留" }, { k: "作用", v: "真相载体" },
    ],
    links: [{ id: "cen-fu", rel: "遗留" }, { id: "lin-cen", rel: "追查" }],
    appears: ["CH02", "CH08"],
  },
  {
    id: "tide-line", cat: "world", name: "潮位线", code: "世·09", kind: "术语",
    accent: "gold", updated: "上周", glyph: "潮",
    summary: "术语 · 空间界线", tags: ["术语", "地理"],
    blurb: "城市与海争夺的那条线，决定哪些建筑会被淹没。旧城档案馆正卡在它之下。",
    facts: [
      { k: "类别", v: "术语 · 地理" }, { k: "意义", v: "存亡界线" },
      { k: "象征", v: "无可逆转" }, { k: "出现", v: "环境描写" },
    ],
    links: [{ id: "old-archive", rel: "威胁" }],
    appears: ["环境"],
  },
  {
    id: "rewrite-crime", cat: "world", name: "档案重写罪", code: "世·10", kind: "术语",
    accent: "gold", updated: "昨天", glyph: "罪",
    summary: "术语 · 核心罪名", tags: ["术语", "核心", "法度"],
    blurb: "篡改已归档记录的罪名，全书的道德核心。周岚的所作所为正落在这条线上。",
    facts: [
      { k: "类别", v: "术语 · 法度" }, { k: "界定者", v: "档案学院" },
      { k: "触犯", v: "周岚" }, { k: "重量", v: "全书核心" },
    ],
    links: [{ id: "zhou-lan", rel: "触犯" }, { id: "academy", rel: "界定" }],
    appears: ["CH05", "CH07"],
  },
  {
    id: "backup", cat: "world", name: "二次备份", code: "世·11", kind: "术语",
    accent: "gold", updated: "上周", glyph: "备",
    summary: "术语 · 制度", tags: ["术语", "制度"],
    blurb: "数据中心推行的冗余制度，理论上让记录无法被悄悄抹去——也成了反派的破绽。",
    facts: [
      { k: "类别", v: "术语 · 制度" }, { k: "推行", v: "数据中心" },
      { k: "效果", v: "记录留痕" }, { k: "作用", v: "翻案凭据" },
    ],
    links: [{ id: "data-center", rel: "推行" }],
    appears: ["CH06"],
  },

  /* ---------------- 大事记 ---------------- */
  {
    id: "third-tide", cat: "events", name: "第三潮汐事件", code: "事·01", kind: "事件 · 2003",
    accent: "slate", updated: "上周", glyph: "03",
    summary: "二十年前的事故", tags: ["背景", "核心", "回忆"],
    blurb: "二十年前，第三潮汐区的一场事故，官方记录与真相不符。岑父罹难于此，也由此埋下全书的悬念。",
    facts: [
      { k: "时间", v: "2003" }, { k: "地点", v: "第三潮汐区" },
      { k: "后果", v: "岑父罹难" }, { k: "层级", v: "全书背景核" },
    ],
    links: [{ id: "cen-fu", rel: "罹难者" }, { id: "third-tide-zone", rel: "发生地" }, { id: "official-record", rel: "官方记录" }],
    appears: ["CH02", "CH08"],
  },
  {
    id: "academy-reform", cat: "events", name: "学院改组", code: "事·02", kind: "事件 · 2011",
    accent: "slate", updated: "上周", glyph: "11",
    summary: "权力更替", tags: ["背景", "权力"],
    blurb: "档案学院的一次改组，周岚由此上位。新旧制度的更替，为日后的重写埋下制度温床。",
    facts: [
      { k: "时间", v: "2011" }, { k: "结果", v: "周岚上位" },
      { k: "影响", v: "制度松动" }, { k: "层级", v: "中景背景" },
    ],
    links: [{ id: "zhou-lan", rel: "受益者" }, { id: "academy", rel: "主体" }],
    appears: ["CH03 · 提及"],
  },
  {
    id: "renovation", cat: "events", name: "旧馆翻修", code: "事·03", kind: "事件 · 2018",
    accent: "slate", updated: "上周", glyph: "18",
    summary: "故事的近因", tags: ["近因", "触发"],
    blurb: "旧城档案馆的一次翻修，意外让一批尘封卷宗重见天日，是故事正式开场的触发点。",
    facts: [
      { k: "时间", v: "2018" }, { k: "事由", v: "翻修出土旧卷" },
      { k: "作用", v: "正文触发" }, { k: "层级", v: "开场近因" },
    ],
    links: [{ id: "old-archive", rel: "发生地" }, { id: "lin-cen", rel: "卷入" }],
    appears: ["CH01"],
  },

  /* ---------------- 参考 ---------------- */
  {
    id: "ref-tide-notes", cat: "refs", name: "潮汐城笔记", code: "参·01", kind: "参考书 · 陈芜 2018",
    accent: "sage", updated: "三天前", glyph: "潮",
    summary: "248 页 · 已学完", tags: ["短句", "冷叙述", "档案体"],
    state: { tone: "sage", label: "已就绪" },
    blurb: "近未来沿海城市的散文体小说。短句、冷叙述、档案体节奏——本项目「冷峻短句」画像的来源文本。",
    facts: [
      { k: "作者", v: "陈芜 · 2018" }, { k: "篇幅", v: "248 页" },
      { k: "学习", v: "已完成" }, { k: "产出画像", v: "1" },
    ],
    links: [{ id: "prof-cold", rel: "导出画像" }],
    appears: ["—"],
  },
  {
    id: "ref-archivist", cat: "refs", name: "档案学者札记", code: "参·02", kind: "参考书 · 毛蕴 2014",
    accent: "sage", updated: "今晨", glyph: "札",
    summary: "312 页 · 已学完", tags: ["回忆体", "嵌套", "引证"],
    state: { tone: "sage", label: "已就绪" },
    blurb: "档案学者的工作笔记体小说。多线索、回忆嵌套、引用层层叠叠——「档案体节奏」画像由此而来。",
    facts: [
      { k: "作者", v: "毛蕴 · 2014" }, { k: "篇幅", v: "312 页" },
      { k: "学习", v: "已完成" }, { k: "产出画像", v: "1 · 待审" },
    ],
    links: [{ id: "prof-rhythm", rel: "导出画像" }],
    appears: ["—"],
  },
  {
    id: "ref-salt-iron", cat: "refs", name: "盐与铁的城市", code: "参·03", kind: "参考书 · 顾尘 2021",
    accent: "sage", updated: "进行中", glyph: "盐",
    summary: "188 页 · 学习中 64%", tags: ["物件叙事", "重物件"],
    state: { tone: "gold", label: "学习中" },
    progress: 0.64,
    blurb: "工业海岸城市的悬疑文学，重物件、轻心理。学习尚未完成，「盐与铁意象」画像仍是草稿。",
    facts: [
      { k: "作者", v: "顾尘 · 2021" }, { k: "篇幅", v: "188 页" },
      { k: "学习", v: "进行中 64%" }, { k: "产出画像", v: "草稿" },
    ],
    links: [{ id: "prof-salt", rel: "草稿画像" }],
    appears: ["—"],
  },
  {
    id: "ref-paper-tide", cat: "refs", name: "纸上的潮水", code: "参·04", kind: "参考书 · 苏白 2019",
    accent: "sage", updated: "排队中", glyph: "纸",
    summary: "220 页 · 等待学习", tags: [],
    state: { tone: "slate", label: "等待" },
    blurb: "已导入，排队等待学习。学习完成后会自动尝试导出一组风格画像。",
    facts: [
      { k: "作者", v: "苏白 · 2019" }, { k: "篇幅", v: "220 页" },
      { k: "学习", v: "排队中" }, { k: "产出画像", v: "—" },
    ],
    links: [],
    appears: ["—"],
  },

  /* ---------------- 风格画像 ---------------- */
  {
    id: "prof-cold", cat: "profiles", name: "冷峻短句", code: "风·01", kind: "风格画像",
    accent: "rose", pinned: true, updated: "今晨", glyph: "冷",
    summary: "本项目正在使用", tags: ["短句", "动词驱动", "克制"],
    state: { tone: "crimson", label: "已应用" },
    blurb: "短句、动词驱动、克制的心理描写，句末落重音。影响候选生成的节奏与句式选择，是本稿的主声音。",
    facts: [
      { k: "来源", v: "潮汐城笔记" }, { k: "状态", v: "已应用" },
      { k: "影响", v: "节奏 · 句式" }, { k: "强度", v: "主声音" },
    ],
    links: [{ id: "ref-tide-notes", rel: "来源文本" }, { id: "lin-cen", rel: "服务于 POV" }],
    appears: ["全稿"],
  },
  {
    id: "prof-rhythm", cat: "profiles", name: "档案体节奏", code: "风·02", kind: "风格画像",
    accent: "rose", updated: "三天前", glyph: "档",
    summary: "待审核 · 等你决策", tags: ["多线索", "嵌套", "引证"],
    state: { tone: "gold", label: "待审核" },
    blurb: "多线索、回忆嵌套、引证段落，段落长度变化大。三天前生成，等待你决定是否应用到本项目。",
    facts: [
      { k: "来源", v: "档案学者札记" }, { k: "状态", v: "待审核" },
      { k: "适用", v: "插叙 · 回忆段" }, { k: "决策", v: "待你拍板" },
    ],
    links: [{ id: "ref-archivist", rel: "来源文本" }],
    appears: ["候选 · 待定"],
  },
  {
    id: "prof-salt", cat: "profiles", name: "盐与铁意象", code: "风·03", kind: "风格画像",
    accent: "rose", updated: "进行中", glyph: "盐",
    summary: "草稿 · 学习未完成", tags: ["物件叙事", "金属", "海"],
    state: { tone: "slate", label: "草稿" },
    blurb: "物件叙事，感官集中在金属与海。来源学习仅完成 64%，暂不可应用。",
    facts: [
      { k: "来源", v: "盐与铁的城市" }, { k: "状态", v: "草稿" },
      { k: "完成度", v: "64%" }, { k: "用途", v: "环境 · 物件段" },
    ],
    links: [{ id: "ref-salt-iron", rel: "来源文本" }],
    appears: ["—"],
  },

  /* ---------------- 知识 ---------------- */
  {
    id: "craft-restore", cat: "knowledge", name: "档案修复工艺", code: "知·01", kind: "知识 · 工艺",
    accent: "ink", updated: "上周", glyph: "修",
    summary: "已发布", tags: ["工艺", "细节真实"],
    state: { tone: "sage", label: "已发布" },
    blurb: "纸张除霉、脱酸、补缀的工序细节，为林岑的日常动作提供可信的质感。",
    facts: [
      { k: "门类", v: "工艺资料" }, { k: "状态", v: "已发布" },
      { k: "服务于", v: "林岑日常" }, { k: "可信度", v: "高" },
    ],
    links: [{ id: "lin-cen", rel: "用于刻画" }, { id: "old-archive", rel: "场景支撑" }],
    appears: ["CH01", "CH05"],
  },
  {
    id: "acoustics", cat: "knowledge", name: "潮汐声学基础", code: "知·02", kind: "知识 · 科学",
    accent: "ink", updated: "上周", glyph: "声",
    summary: "已发布", tags: ["科学", "声音"],
    state: { tone: "sage", label: "已发布" },
    blurb: "海潮与回声记录的声学原理，支撑「回声记录」这一关键物件的合理性。",
    facts: [
      { k: "门类", v: "科学资料" }, { k: "状态", v: "已发布" },
      { k: "支撑", v: "回声记录" }, { k: "用途", v: "设定自洽" },
    ],
    links: [{ id: "echo-record", rel: "支撑设定" }],
    appears: ["CH02", "CH08"],
  },
  {
    id: "classification", cat: "knowledge", name: "馆藏分类法 v3", code: "知·03", kind: "知识 · 制度",
    accent: "ink", updated: "本周", glyph: "类",
    summary: "已批准", tags: ["制度", "体系"],
    state: { tone: "gold", label: "已批准" },
    blurb: "档案馆的分类与编号体系，是「档案重写罪」得以界定的技术前提。",
    facts: [
      { k: "门类", v: "制度资料" }, { k: "状态", v: "已批准" },
      { k: "关联", v: "重写罪界定" }, { k: "版本", v: "v3" },
    ],
    links: [{ id: "rewrite-crime", rel: "技术前提" }, { id: "academy", rel: "由其制定" }],
    appears: ["CH05"],
  },
  {
    id: "director-timeline", cat: "knowledge", name: "学院主任年表", code: "知·04", kind: "知识 · 年表",
    accent: "ink", updated: "今晨", glyph: "年",
    summary: "已批准", tags: ["年表", "人物史"],
    state: { tone: "gold", label: "已批准" },
    blurb: "历任学院主任的年表，周岚的上位与改组在此对齐，防止时间线出错。",
    facts: [
      { k: "门类", v: "年表资料" }, { k: "状态", v: "已批准" },
      { k: "对齐", v: "学院改组" }, { k: "防错", v: "时间线" },
    ],
    links: [{ id: "zhou-lan", rel: "记录" }, { id: "academy-reform", rel: "对齐事件" }],
    appears: ["参考"],
  },
  {
    id: "official-record", cat: "knowledge", name: "二十年前事故的官方记录", code: "知·05", kind: "知识 · 文件",
    accent: "ink", updated: "今天", glyph: "录",
    summary: "审核中", tags: ["文件", "悬念", "存疑"],
    state: { tone: "slate", label: "审核中" },
    blurb: "第三潮汐事件的官方说法，与真相存在缝隙。这份「权威记录」本身就是悬念。",
    facts: [
      { k: "门类", v: "文件资料" }, { k: "状态", v: "审核中" },
      { k: "对应", v: "第三潮汐事件" }, { k: "性质", v: "不可靠" },
    ],
    links: [{ id: "third-tide", rel: "对应事件" }, { id: "echo-record", rel: "被其推翻" }],
    appears: ["CH08"],
  },
  {
    id: "tower-structure", cat: "knowledge", name: "盐钟塔结构", code: "知·06", kind: "知识 · 图纸",
    accent: "ink", updated: "今天", glyph: "构",
    summary: "审核中", tags: ["图纸", "地标"],
    state: { tone: "slate", label: "审核中" },
    blurb: "盐钟塔的结构图与材质说明，为终章的塔上场景提供空间依据。",
    facts: [
      { k: "门类", v: "图纸资料" }, { k: "状态", v: "审核中" },
      { k: "支撑", v: "终章塔上戏" }, { k: "材质", v: "盐 · 铁" },
    ],
    links: [{ id: "salt-tower", rel: "结构资料" }],
    appears: ["CH08"],
  },
  {
    id: "zhou-diary", cat: "knowledge", name: "周岚日记 · 节选", code: "知·07", kind: "知识 · 手记",
    accent: "ink", updated: "现在", glyph: "记",
    summary: "草稿 · 撰写中", tags: ["手记", "内心", "草稿"],
    state: { tone: "crimson", label: "草稿" },
    blurb: "周岚视角的私密手记节选，用于校准反派的内在逻辑，目前仍在撰写。",
    facts: [
      { k: "门类", v: "手记资料" }, { k: "状态", v: "草稿" },
      { k: "用途", v: "反派内核" }, { k: "进度", v: "撰写中" },
    ],
    links: [{ id: "zhou-lan", rel: "视角主体" }],
    appears: ["内部参考"],
  },
];

/* ==========================================================
   FE-ALIGN Phase 6：资料库接真。
   LIB_ENTRIES 退化为可变缓存数组（保持引用——视图随访问重挂载读取
   最新内容）；数据来自 /api/v2/projects/{id}/library（人物/实体/关系/
   时间线聚合），适配为原型条目形状。refs/profiles/knowledge 三类
   由风格/知识子系统供给，P8 接真前留空。
   原静态种子（LIB_SEED_ENTRIES）保留为导出脚本的数据源
   （scripts/export-demo-catalog.mjs → 后端 demo seed），运行时不再使用。
   ========================================================== */

const LIB_ENTRIES = [];
const LIB_BY_ID = {};

const LIB_KIND_LABEL = { location: "地点", item: "物品", faction: "机构", concept: "概念" };
const LIB_CAT_ACCENT = { people: "crimson", world: "gold", events: "slate" };

const libActiveId = () => { try { return window.WsWorks ? window.WsWorks.activeId() : null; } catch (e) { return null; } };

/* 关系 id 缓存（编辑层 diff 删边用）：refPair "a|b" → relation_id */
let LIB_RELATIONS = [];

function libStripRef(ref) { return String(ref || "").split(":").slice(1).join(":"); }

function libAdaptCharacter(c, linksOf) {
  const d = c.details || {};
  return {
    id: c.character_id, cat: "people", name: c.name,
    code: d.code || "人物", kind: c.role || "角色",
    accent: d.accent || LIB_CAT_ACCENT.people, glyph: d.glyph || Array.from(c.name)[0],
    pinned: !!d.pinned, updated: d.updated || "",
    summary: c.summary || "", tags: d.tags || [],
    arc: d.arc, state: d.state,
    blurb: d.blurb || "",
    facts: d.facts || [],
    links: linksOf(`character:${c.character_id}`),
    appears: d.appears || [],
    ref: c.ref,
  };
}

function libAdaptEntity(e, linksOf) {
  const d = e.details || {};
  return {
    id: e.entity_id, cat: "world", name: e.name,
    code: d.code || "世界", kind: LIB_KIND_LABEL[e.kind] || e.kind,
    accent: d.accent || LIB_CAT_ACCENT.world, glyph: d.glyph || Array.from(e.name)[0],
    pinned: !!d.pinned, updated: d.updated || "",
    summary: e.summary || "", tags: e.tags || [],
    arc: d.arc, state: d.state,
    blurb: d.blurb || "",
    facts: d.facts || [],
    links: linksOf(e.ref),
    appears: d.appears || [],
    ref: e.ref,
  };
}

function libAdaptEvent(ev, byRef) {
  const facts = [];
  if (ev.time_label) facts.push({ k: "时间", v: ev.time_label });
  if (ev.chapter_ref) facts.push({ k: "章", v: ev.chapter_ref });
  return {
    id: ev.event_id, cat: "events", name: ev.label,
    code: "事记", kind: "事件",
    accent: LIB_CAT_ACCENT.events, glyph: Array.from(ev.label)[0],
    updated: "",
    summary: ev.time_label || "", tags: [],
    blurb: ev.note || "",
    facts,
    links: (ev.entity_refs || []).map(ref => ({ id: libStripRef(ref), rel: "相关" })).filter(l => l.id),
    appears: ev.chapter_ref ? [ev.chapter_ref] : ["贯穿"],
    ref: `event:${ev.event_id}`,
  };
}

let libFetching = null;
function libFetch() {
  const pid = libActiveId();
  if (!pid || pid === "__loading__") return Promise.resolve();
  if (libFetching) return libFetching;
  libFetching = (async () => {
    try {
      const data = await apiGet(`/api/v2/projects/${pid}/library`);
      LIB_RELATIONS = (data && data.relations) || [];
      const linkIndex = {};
      for (const rel of LIB_RELATIONS) {
        (linkIndex[rel.from_ref] = linkIndex[rel.from_ref] || []).push({ id: libStripRef(rel.to_ref), rel: rel.note || rel.kind, type: rel.kind, relationId: rel.relation_id });
        (linkIndex[rel.to_ref] = linkIndex[rel.to_ref] || []).push({ id: libStripRef(rel.from_ref), rel: rel.note || rel.kind, type: rel.kind, relationId: rel.relation_id });
      }
      const linksOf = (ref) => linkIndex[ref] || [];
      const byRef = {};
      const next = [
        ...((data && data.characters) || []).map(c => libAdaptCharacter(c, linksOf)),
        ...((data && data.entities) || []).map(e => libAdaptEntity(e, linksOf)),
        ...((data && data.timeline) || []).map(ev => libAdaptEvent(ev, byRef)),
      ];
      LIB_ENTRIES.length = 0;
      LIB_ENTRIES.push(...next);
      Object.keys(LIB_BY_ID).forEach(k => { delete LIB_BY_ID[k]; });
      next.forEach(e => { LIB_BY_ID[e.id] = e; });
      try { window.dispatchEvent(new CustomEvent("ws:library-changed")); } catch (e) {}
    } catch (e) {
      console.warn("[WsLibrary] 拉取资料库失败:", e);
    } finally {
      libFetching = null;
    }
  })();
  return libFetching;
}

try { libFetch(); } catch (e) {}
window.addEventListener("ws:work-changed", () => { try { libFetch(); } catch (e) {} });
Object.assign(window, { LIB_relationsRaw: () => LIB_RELATIONS, LIB_refetch: libFetch });

Object.assign(window, { LIB_CATS, LIB_ENTRIES, LIB_BY_ID });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LIB_CATS, LIB_ENTRIES, LIB_BY_ID };
