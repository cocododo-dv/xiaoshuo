# FE-主线对齐 · 交接包

把整个 `FE-主线对齐/` 文件夹放进 codex 仓库的 `codex-patches/` 下（与 P0-1 等并列）。

## 用法 A（无人值守，推荐）

复制 `自动执行提示词.md` 里的提示词整段发给 Claude Code（建议 `claude --dangerously-skip-permissions` 启动），它会按 Phase 0→8 自动执行到底，决策按默认、偏差记 PROGRESS.md、不中途提问。

## 用法 B（每个 Phase 一个会话，人工把关）

第一次会话：
> 阅读 codex-patches/FE-主线对齐/ 下的 CLAUDE_CODE_任务简报.md、两份契约附录和 phases/00-基线与陷阱.md，
> 决策点 D1–D6 按默认。先执行 Phase 0，再按 phases/01-前端工程化.md 执行，完成后更新 PROGRESS.md。

之后每个会话：
> 阅读 codex-patches/FE-主线对齐/ 下的主简报、契约附录和 PROGRESS.md，
> 继续执行下一个未完成的 Phase（phases/0N-…），完成后更新 PROGRESS.md。

## 内容

| 文件 | 作用 |
|---|---|
| `CLAUDE_CODE_任务简报.md` | 主简报：原则、概念对照表（**端点已逐一核实**）、决策点、Phase 一览、全局验收 |
| `契约附录-store缝合面.md` | 五个前端 store 的公开方法签名/数据形状/事件——改造的不可变接口 |
| `契约附录-B-后端端点清单.md` | 后端既有端点全量清单（按域，含与原型视图的对应） |
| `phases/00–08` | Phase 0 是基线+陷阱清单（含对主简报三处事实修正）；其余每 Phase：后端现状（核实符号）→ 改动步骤 → API 契约 → 自检 → 提交信息 |
| `PROGRESS.md` | 进度账本：勾选 + 提交号 + 「核对发现」（实际代码与简报不符时记录在此） |
| `design/` | 高保真原型（设计真相源）。React 18 + Babel standalone，入口 `index.html`，静态服务器直开即可运行 |

## 注意

- `design/` 不是线框参考，而是按 D1 方案**直接工程化**（搬入 `frontend-react/`、模块化、接 API）的实现基础；视觉与交互像素级保留。
- 改造铁律：**只动 store 层、不动视图层**（契约附录是验收依据）。
- 每个 Phase：单独会话、单独提交、测试全绿再进下一个；简报与实际代码冲突时以代码为准并记入 PROGRESS.md。
