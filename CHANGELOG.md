# Changelog / 更新日志

## 2.1.1

- **Hook 默认策略收口**
  - `user_prompt_submit` 默认禁用
  - Claude Code / Codex adapter 默认不再生成 `UserPromptSubmit`
  - 避免普通自然语言请求（如“继续”“下一步”“同步下文档”）被建议型 Hook 打断
- **Hook 配置行为修复**
  - `enabled: false` 现在会被 runner 和 adapters 一起真正视为禁用
  - `tool_matcher` 统一从 `filter.tool_matcher` 读取，配置语义与执行语义一致
- **文档体系收敛**
  - 主文档收敛为 7 份核心文档
  - 旧专项文档整体下沉到 `docs/archive/`

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
  - `_resolve_memory_ref` 使用 backend 优先读取 session events / write receipts
  - timeline 收集与部分高频读路径进一步优先复用 SQLite backend

## 2.0.11

- 全部 7 个高频大返回默认 `view=compact`
- `workspace_recent_evidence` 补齐 `view=compact|full`
- `memory_ref_get` 增加 `timeline_ref`
- dashboard / continuity 增加 `view / budget` 切换
- `/ui/ref`、`/ui/timeline`、`/ui/task` 等页面钻取能力增强
- Hook adapter 收口与可执行性增强

## 2.0.10

- `recent_evidence` view/gain 收口
- 短引用体系补齐
- ref → timeline 反向导航落地

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
