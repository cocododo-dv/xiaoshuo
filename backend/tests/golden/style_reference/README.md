# Style Reference 黄金测试语料

本目录承载 Style Reference v1.1 抽取/验证流水线的端到端黄金测试。
参见《风格参考模块重构执行手册 v1.1》§9.2。

## 目录结构

```
backend/tests/golden/style_reference/
├── corpus/
│   ├── luxun_short_stories.txt        # 主力测试集
│   ├── laoshe_short_stories.txt       # 对照测试集
│   └── shenxc_biancheng_excerpt.txt   # 短篇下限测试
├── expected/
│   └── (待 PR-3+ 落 expected JSON,如 luxun_profile_metrics.json 等)
└── README.md
```

## 当前状态:占位语料

PR-2 仅落 **placeholder 合成中文文本**作为占位,**不是真实公版作品**。
每份 placeholder 文件头部已显式标注"占位语料,真实公版 corpus 待提供"。

PR-2 单测在 placeholder 上验证 ingest / metrics / segmentation 链路通畅,
**不**在 placeholder 上验证文学质量或风格还原度。

## 真实 corpus 待提供

用户后续将以独立 commit 替换 placeholder 为真实公版作品。推荐源材料如下,
全部公版或开放授权,可放心放入仓库:

| 文件 | 推荐源材料 | 字数目标 | 获取建议 |
|---|---|---|---|
| luxun_short_stories.txt | 《孔乙己》《故乡》《祝福》《阿Q正传》 | ~80k | 中国哲学书电子化计划 (ctext.org) / 维基文库 zh.wikisource.org |
| laoshe_short_stories.txt | 《断魂枪》《月牙儿》 | ~50k | 中国哲学书电子化计划 / Project Gutenberg 中文区 (gutenberg.org) |
| shenxc_biancheng_excerpt.txt | 《边城》节选 | ~30k | 维基文库 / 公版作品归档库 |

**严禁**使用当代 IP(江南、龙族、路明非、路鸣泽、昂热、恺撒等 — 见 §9.2)。
CI 后续会加 grep 守卫拒绝这些关键词进入 golden 目录。

## 替换 placeholder 的步骤

1. 从推荐源下载 TXT(确认编码为 UTF-8,统一 LF 换行)
2. 替换 corpus/ 下对应同名文件,**保留头部首行 `# 来源:<url>` 元数据**
3. 跑 `python -m pytest backend/tests/test_style_reference_metrics.py -v` 确认指标计算稳定
4. 跑 `backend/tests/test_style_reference_ingest.py` 确认 input_assessment 进入预期等级

## 文件命名约定

- `corpus/`:**输入语料**(原始 TXT)
- `expected/`:**预期输出**(JSON,后续 PR-3+ 落地)
  - `<author>_profile_metrics.json` — 期望的硬指标 ± tolerance
  - `<author>_sub_dim_keywords.json` — 每 sub_dim 期望出现的关键词
  - `faux_*.txt` — 故意构造的反例文本(如"伪张爱玲腔"),必须 validation fail
