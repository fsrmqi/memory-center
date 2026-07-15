# Release / 发布说明

## 1. Release Principle / 发布原则

发布时优先保证：

- MCP facade 兼容性
- 文档与实现一致
- 本地安装可用
- 关键 smoke 可通过

## 2. Minimum Checklist / 最小发布清单

1. 更新版本号
2. `python3.11 -m compileall memory_center`
3. 关键 smoke：
   - `status`
   - `work-start`
   - `mc_admin(action="health")`
   - Hook 生成
4. README / docs 是否同步
5. 本地安装验证：使用 Python 3.10+ 执行 `pipx reinstall --python "$(command -v python3.11)" memory-center`，再运行 `memory-center --version`；不要依赖可能指向旧 Python 的默认 `pipx reinstall`

## 3. Trusted Release Notes / 可信发布说明

对外说明重点只保留：

- 这版新增了什么
- 修了哪些真实 bug
- 有哪些行为变更
- 是否需要重新安装 / 重生成 hooks / 重启 MCP

## 4. Notes / 说明

发布相关文档保持精简，历史性的细碎检查项不再长期保留为独立文档。

如果要看当前阶段的详细实现计划与状态，请看：

- [NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md)

阶段性的“实现完成报告”不再单独维护，完成状态统一并回总方案、changelog 和相关主文档。
