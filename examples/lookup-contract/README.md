# Lookup contract private-suite template / 查询契约私有样本模板

将 `cases.example.yaml` 复制到仓库外的私有评测目录后填写逻辑 query。不要提交真实路径、业务 payload、用户提示或生产 session ID。

`session_steps: 2` 用于验证同一 session 的第二次查询在 CLI、HTTP、MCP 都触发 `served_dedup`。
