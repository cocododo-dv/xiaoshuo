# Style Reference 黄金测试语料

本目录承载 Style Reference v1.1 抽取/验证流水线的端到端黄金测试。
参见《风格参考模块重构执行手册 v1.1》§9.2。

## 目录结构

```
backend/tests/golden/style_reference/
├── corpus/
│   ├── luxun_short_stories.txt   # 主力测试集:鲁迅短篇 11 篇,约 66,000 字
│   ├── zhuziqing_essays.txt      # 对照测试集:朱自清散文 4 篇,约 8,300 字
│   └── luxun_kongyiji.txt        # 下限测试集:单篇《孔乙己》,约 2,600 字(全层 skip)
├── expected/
│   ├── luxun_ingest_expected.json      # 主力集 ingest 期望(26 metrics + input_assessment 等)
│   └── zhuziqing_ingest_expected.json  # 对照集 ingest 期望
└── README.md
```

## 语料来源与版权

全部为**公有领域**作品,2026-06-13 取自中文维基文库(zh.wikisource.org,
REST API `page/html` + zh-hans 变体转换,HTMLParser 提取 <p> 正文并滤除
许可证/导航噪声):

- **鲁迅**(1881–1936,卒逾 50/70 年,两岸与美国均已进入公有领域;
  所收各篇均发表于 1930 年以前):《狂人日记》《孔乙己》《药》《明天》
  《一件小事》《头发的故事》《风波》《故乡》《阿Q正传》《祝福》《在酒楼上》
- **朱自清**(1898–1948,卒逾 50 年,大中华区公有领域;所收各篇发表于
  1923–1927,美国亦公有领域):《背影》《荷塘月色》《温州的踪迹》《航船中的文明》

**硬约束(《手册》§9.2 / 附录 C B9)**:本目录严禁出现当代受版权保护 IP
的文本或关键词;`test_style_reference_golden.py` 内置关键词守卫用例,
命中即 fail。

## 期望文件再生成

corpus 或 metrics 算法**有意**变更后,重新生成 expected:

```powershell
cd backend
python tests/golden/style_reference/regen_expected.py
```

(脚本在隔离临时库上跑真实 ingest 管线——启发式分类,无 LLM,结果确定。)

## 本地私有语料验证(不入仓库)

想用自己的书(如受版权保护的当代小说)验证摄取/统计/抄袭检测,
设环境变量指向本地 TXT(UTF-8 或 GB18030)后单独跑:

```powershell
$env:NOVEL_SYSTEM_STYLE_REF_LOCAL_CORPUS = "C:\path\to\本地参考书.txt"
python -m pytest tests/test_style_reference_local_corpus.py -v
```

未设该变量时这些用例自动跳过;本地书内容永不进入仓库。
