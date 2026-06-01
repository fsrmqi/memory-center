# Changelog / 更新日志

本更新日志按**版本号**归纳，优先记录：

- 用户可感知的新能力
- 重要行为变化
- 明确修复的真实 bug

## 2.1.8

- **发布版本更新**
  - Python 包版本更新为 `2.1.8`

## 2.1.7

- **安装脚本默认目标修正**
  - 在本地仓库中执行 `bash install.sh` 时，默认安装当前 checkout，而不是回退到远端 GitHub 仓库
  - 仍然保留 `curl ... | bash` 场景下默认从 GitHub 安装的行为
  - 安装脚本会自动优先选择本机可用的 `python3.10+`，并按当前 package target 重新安装已有 `pipx` 环境
- **发布版本更新**
  - Python 包版本更新为 `2.1.7`

## 2.1.3

- **文档体系重构**
  - 补回根目录维护者文档：`TECHNICAL_GUIDE.md`、`NEXT_PHASE_MASTER_PLAN.md`
  - `README.md`、`docs/ROADMAP.md`、`docs/RELEASE.md` 与技术/计划文档重新串联
  - 调整文档分层：对外使用线与对内维护线并存

## 2.1.2

- **文档结构收敛**
  - 主文档收敛为 7 份核心 docs
  - `README`、`ROADMAP`、`CHANGELOG` 的角色重新划分
  - 清理重复、阶段性和过细的旧文档入口

## 2.1.1

- **Hook 默认策略收口**
  - `user_prompt_submit` 默认禁用
  - Claude Code / Codex adapter 默认不再生成 `UserPromptSubmit`
  - 避免普通自然语言请求（如“继续”“下一步”“同步下文档”）被建议型 Hook 打断
- **Hook 配置行为修复**
  - `enabled: false` 现在会被 runner 和 adapters 一起真正视为禁用
  - `tool_matcher` 统一从 `filter.tool_matcher` 读取，配置语义与执行语义一致

## 2.1.0

- **agentmemory 风格 token benchmark**
  - 新增 `memory_eval_token_benchmark`
  - 覆盖 7 个高频函数：`sniff / status / resume / recent_evidence / continuity / dashboard / handoff`
  - 对 `small / medium / large` 三档预算输出按函数对比表和总 token 统计
- **Top-K evidence 策略**
  - `workspace_recent_evidence` 的 compact 模式采用显式 top-K
  - `small=3`、`medium=5`、`large=10`
  - 排序优先级为 `ref_id + summary + payload_ref/receipt_ref` 的信号丰富度，再按时间倒序
- **SQLite 后端读路径扩展**
  - `_resolve_memory_ref` 优先复用 backend 读取 session events / write receipts
  - timeline 和部分高频读路径进一步优先复用 SQLite backend

## 2.0.11

- **默认 compact 与短引用收口**
  - 全部 7 个高频大返回默认 `view=compact`
  - `workspace_recent_evidence` 补齐 `view=compact|full`
  - `memory_ref_get` 增加 `timeline_ref`
- **UI / workbench 增强**
  - dashboard / continuity 增加 `view / budget` 切换
  - `/ui/ref`、`/ui/timeline`、`/ui/task` 等页面钻取能力增强
  - guided tour、next action 卡片、cross-page links
- **Hook / adapter 增强**
  - Codex adapter 生成脚本可执行化
  - Cursor adapter 补充 MCP 命令与 quick reference

## 2.0.10

- `recent_evidence` 的 compact/full 与 gain 收口
- 短引用体系进一步补齐
- ref → timeline 反向导航落地

## 2.0.9

- Hook 资源模板与打包问题修复
- 默认 hooks 配置修正
- 核心数据处理与稳定性增强

## 2.0.5

- token gain 跟踪与评测
- Hook runner / adapters 基础能力
- 工作流编排评测与预算优化
- SQLite 优先读取开始接入更多路径

## 2.0.4

- 增量索引第一阶段
  - `--project`
  - `--path`
  - `--changed-only`
- `work-*` 一键工作流命令
- workbench / backend query 第一阶段

## 2.0.2

- regression suite
- compact / full
- budget
- short refs
- `memory_ref_get / batch`

## 2.0.0

- continuity / handoff / dashboard 主链路成型
- write receipt / write judge / write plan / write execute
- 多根目录 workspace 支持
- 工具使用报告与 lookup hint

## 1.3.0

- 共享工件与 sync sniff / sync case
- 自动同步模式
- 更完整的代码搜索、符号解析和调用链分析

## 1.0.0

- 项目正式命名为 **Memory Center / 记忆中心**
- Python 包统一为 `memory_center`
- CLI / MCP 命令统一为 `memory-center` / `memory-center-mcp`
- README 和公共文档体系初步建立

## 0.2.0

- Public GitHub-ready repository structure
- Apache-2.0 license, templates, basic docs, CI

## 0.1.0

- Initial MVP with workspace indexing, MCP tools, default rules and agent instructions
