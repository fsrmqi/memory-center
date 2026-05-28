# Roadmap / 路线图

## Overview / 总览

这份路线图按**版本里程碑**整理，分成两部分：

1. 已完成的关键演进
2. 下一阶段最值得推进的方向

如果你需要维护者视角的详细计划与当前阶段判断，请看：

- [NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/NEXT_PHASE_MASTER_PLAN.md)
- [docs/ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ROADMAP.md)

## Completed Milestones / 已完成里程碑

### `0.1.x` MVP

- 初始 workspace 索引
- 基础 MCP tools
- 默认规则
- 基础 agent instructions

### `0.2.x` Public GitHub-ready

- 开源仓库结构整理
- License / 模板 / CI
- 基础公开文档

### `1.0.x` Memory Center 定型

- 项目统一命名为 **Memory Center / 记忆中心**
- Python 包统一为 `memory_center`
- CLI / MCP 命令统一
- README 和公共文档体系建立

### `1.3.x` Shared artifacts and sync

- 共享工件体系
- sync sniff / sync case
- auto-sync 模式
- 更完整的代码搜索、符号解析、调用链分析

### `2.0.0` Stable shared memory platform

- continuity / handoff / dashboard 主链路落地
- write receipt / write judge / write plan / write execute
- 多根目录 workspace 支持
- 规则驱动的恢复与评测

### `2.0.2` Lightweight context and short refs

- compact/full
- budget 档位
- regression suite
- 短引用展开

### `2.0.4` Partial reindex and workflows

- 增量索引第一阶段
- `--project / --path / --changed-only`
- `work-*` 工作流命令
- workbench 雏形

### `2.0.5` to `2.0.9` Backend and hook foundation

- SQLite `memory.db` 镜像后端
- backend query
- 高层 Hook runner / adapters
- facade MCP 面开始稳定
- 核心模块拆分与并发/稳定性修复

### `2.0.10` to `2.0.11` Facade + compact tightening

- 82 → 8 MCP facade 工具
- `workspace_handoff_packet` 纳入轻量协议
- 全部 7 个高频大返回默认 `compact`
- `recent_evidence`、refs、timeline、handoff 收口
- UI drill-down、guided tour、next action 卡片

### `2.1.0` agentmemory-style absorption

- `memory_eval_token_benchmark`
- 7 个高频函数 benchmark
- top-K evidence：`3 / 5 / 10`
- token gain / token benchmark 组合
- SQLite 高优先读路径继续扩展

### `2.1.1` Hook behavior stabilization

- `enabled: false` 真正生效
- `filter.tool_matcher` 执行语义修复
- `UserPromptSubmit` 默认禁用
- Claude Code / Codex 默认不再生成 `UserPromptSubmit`

### `2.1.2` ~ `2.1.3` Documentation restructure

- 文档从“多份重叠说明”重构为：
  - 根目录总入口
  - 技术说明
  - 详细计划
  - 7 份核心 docs
- README / CHANGELOG / ROADMAP / TECHNICAL_GUIDE / plan 串联起来

## Next Stage / 下一阶段

### Priority 1 / 第一优先级

- Hybrid retrieval
- 更系统的 benchmark 趋势化
- SQLite 继续接管更多真实读路径

### Priority 2 / 第二优先级

- timeline / ref / task 更强 drill-down
- 更稳的 completion audit
- Hook 宿主策略继续收口

### Priority 3 / 第三优先级

- 更强 guided onboarding
- 更系统的 workbench 交互
- 更长期的质量趋势分析

## Guiding Principle / 指导原则

后续版本不再以“功能数量”作为主要目标，而以这三件事为主：

1. 日常使用是否更顺
2. token 是否更稳
3. 多模型连续性是否更自然
