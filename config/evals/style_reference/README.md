# 风格参考跨内容基准 v1

这套基准用于回答一个窄而重要的问题：同一份原创场景事实，经过当前
Style Reference 模块后，是否比中性稿更接近指定参考风格，同时不丢事实、
不复制参考正文，也不把隐藏评分作品送进生成提示词。

首版内置两位公版作者、8 个原创场景和 24 个生成单元。朱自清侧已扩充到
16 篇固定 revision 公版散文；训练集与隐藏评分集
按完整作品切分；隐藏侧只在全部生成完成后由评分器加载。用户不需要另行准备
语料或人工标注。

## 运行

从 `backend` 目录执行：

```powershell
python -m novel_system.tools.style_reference_benchmark inspect
python -m novel_system.tools.style_reference_benchmark prepare
python -m novel_system.tools.style_reference_benchmark run-live
```

`run-live` 会使用隔离 SQLite 数据库复用产品真实链路：摄取、四层抽取、Profile
合成、项目绑定、中性稿和风格稿。它要求所有相关模型路由均启用且具有凭据；
缺失时会在任何模型调用和工作区写入之前停止。运行中每完成一个单元即写原子
checkpoint，可用 `--resume` 续跑。

产物默认位于 `backend/.style-benchmark/`，并已被 Git 忽略：

- `results.json`：生成正文、实际提示词和血缘元数据；
- `report.json`：隐藏自动评分，不回显隐藏正文；
- `blind_packet.json`：候选身份盲化的人工复核包；
- `blind_key.json`：与盲评包分离的答案键；
- `benchmark.db`：隔离运行数据库。

命令退出码：`0` 表示所有冻结门槛通过，`2` 表示基准完整执行但至少一项门槛
未通过，`1` 表示配置、凭据或输入错误。

## 结论边界

自动分数只证明“跨内容相对风格信号”，不等于自然度、审美质量、作者身份鉴定，
也不能证明文本不会被所谓 AI 检测器识别。最终产品结论仍应结合独立盲评；首版
两位作者的隐藏语料规模也不均衡，因此报告采用宏平均并明确保留该限制。
