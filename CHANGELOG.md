# Changelog / 更新日志

## 2.1.0

- **Token benchmark eval (agentmemory 模式)**
  - 新增 `memory_eval_token_benchmark` — 对 7 个高频函数在 small/medium/large 三个预算下测量 token 数量
  - CLI: `eval-token-benchmark`，MCP: `mc_admin(action="eval_token_benchmark")`
  - 返回 per-function per-budget 对比表 + 总计 token，可用于回归测试
- **Top-K only evidence 策略 (agentmemory 模式)**
  - `_compact_evidence_entries` 改为按信号丰富度（ref_id + summary + payload_ref）+ 时间排序，取 top-K
  - budget-aware K 值：small=3, medium=5, large=10
- **SQLite 后端读路径扩展**
  - `_resolve_memory_ref` (common.py): session events + write receipts → `read_jsonl_prefer_backend`
  - `_collect_timeline_items` (timeline.py): timeline 收集 → `read_jsonl_prefer_backend`
  - 核心读路径已全面切换到 SQLite 优先

## 2.0.11

- **WP3: 默认 compact 模式**
  - 全部 7 个高频函数（sniff/status/resume/handoff/recent_evidence/continuity/dashboard）默认 `view` 从 `"full"` 改为 `"compact"`
  - 测试中需要完整字段的断言改为显式 `view="full"`
- **WP3: compact 模式收紧为严格短引用**
  - dashboard/continuity/handoff 的 compact 函数中 `recent_evidence`、`recent_receipts`、`recent_handoffs`、`focus_task` 全部提取为仅 `ref_id + summary` 或 `task_id + title + status`
  - 不再在 compact 模式下混入完整原始字段
- **Hooks: Codex adapter 生产化**
  - 脚本生成后自动 `chmod +x`（可执行）
  - docstring 更新，移除 placeholder 标记
- **Hooks: Cursor adapter 增强**
  - `.cursorrules` 现在包含每个 hook 的具体 MCP 命令指令（mc_start/mc_lookup/mc_analyze/mc_sync/mc_resume/mc_handoff/mc_close）
  - 新增 Quick Reference 部分，列出 8 个 facade 工具的用途
- **Guided tour overlay / 引导叠加层**
  - `/ui` 索引页首次打开时自动弹出 5 步引导叠加层（Dashboard/Continuity/Timeline/Refs/Tools）
  - `localStorage` 记住已看过一次，侧栏提供 "Replay Tour / 重播引导" 按钮
- **Next Action hero card / 下一步行动卡片**
  - `/ui/dashboard` 页面顶部新增高亮的 "Next Action / 下一步" 卡片
  - 自动从 `focus_resume_eval` / `continuity_overview` 提取最紧急的未完成项或下一步动作
  - 包含 quality/score 标签和 "Go → / 前往 →" 快捷链接
- **Cross-page drill-down links / 跨页钻取链接**
  - `/ui/continuity` → `/ui/task`（焦点任务）
  - `/ui/task` → `/ui/timeline` + `/ui/receipts`（新增 receipts 链接）
  - `/ui/ref` → `/ui/timeline`（反向导航，v2.0.10 已有）
- **Version roadmap updated / 版本路线图更新**
  - `NEXT_PHASE_MASTER_PLAN.md` 新增 v2.0.11 里程碑

## 2.0.11

- **WP2 收口：`workspace_recent_evidence` 补齐 `view=compact|full`**
  - 新增 `view` 参数，默认 `"full"`；`view="compact"` 走 `_compact_evidence_entries` + `log_token_gain`
  - `view="full"` 返回完整条目（不再强制压缩），与其他 6 个高频接口对齐
  - 所有 MCP/HTTP/CLI/hook 调用点统一传 `view="compact"`
- **WP3 收口：ref→timeline 反向导航**
  - `memory_ref_get` 返回新增 `timeline_ref` 字段，从 raw 中的 session_id/task_id 构造 `/ui/timeline?...` 链接
  - `/ui/ref` HTML 页面新增 "View in Timeline → / 在时间线中查看 →" 交叉链接
- **WP5 交互增强：budget/compact UI 切换控件**
  - `/ui/dashboard` 和 `/ui/continuity` 筛选表单新增 `<select name="view">` 和 `<select name="budget">` 下拉控件
  - HTML 生成函数和 HTTP 路由接受 `view`/`budget` 参数，动态标记 `selected`
- **WP5 交互增强：refs 内联展开**
  - `_render_ref_list_html`、`_render_receipt_list_html`、`_render_task_list_html`、`_render_handoff_list_html`、timeline items 全部添加 `<details><summary>Expand / 展开</summary>` 内联展开
  - 各页面 CSS 添加 `details/summary/pre` 样式规则
- Completion audit: 6 个工作包全部达到已交付状态
- 文档更新：NEXT_PHASE_MASTER_PLAN.md 补充版本技术路线表、README.md 更新 schema 字段、DETAILED_REFERENCE.md 更新 memory_ref 返回结构

## 2.0.10

## 1.0.0

- Renamed the project to **Memory Center / 记忆中心**.
- Renamed Python package to `memory_center` and CLI commands to `memory-center` / `memory-center-mcp`.
- Added detailed bilingual README and documentation.
- Improved workspace root resolution for portable examples.
- Added public-release oriented agent instructions for AGENTS, Claude, Gemini and Copilot.
- Clarified the product positioning: MCP-native project memory service, multi-agent shared context center and experience memory layer.

## 0.2.0

- Public GitHub-ready repository structure.
- Added Apache-2.0 license, contribution guide, security policy and issue templates.
- Added Mermaid topology export.
- Added workspace doctor command.
- Added docs for architecture, MCP tools, rule spec, workspace spec and release checklist.
- Added smoke tests and CI workflow.

## 0.1.0

- Initial MVP with workspace indexing, MCP tools, default rules and agent instructions.
