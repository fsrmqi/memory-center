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
5. 本地 `pipx reinstall` 验证

## 3. Trusted Release Notes / 可信发布说明

对外说明重点只保留：

- 这版新增了什么
- 修了哪些真实 bug
- 有哪些行为变更
- 是否需要重新安装 / 重生成 hooks / 重启 MCP

## 4. Archived Release Material / 已归档发布材料

更细碎的发布检查与历史说明已归档到：

- `docs/archive/`
