# Specs / 规格说明

## 1. workspace.yaml

核心字段：

- `workspace`
- `root`
- `services`
- `registry`
- `embedding_backend`

每个 service 典型字段：

- `path`
- `type`
- `service_name`
- `language`
- `stack`

## 2. rules

规则文件位于：

- `.memory-center/rules/`

高频规则：

- `global-rules.yaml`
- `auto-sync-rules.yaml`
- `resume-rules.yaml`
- `handoff-rules.yaml`
- `write-policy-rules.yaml`
- `eval-rules.yaml`

规则应至少包含：

- `id`
- `title`
- `severity`
- `when`
- `message`

## 3. hooks.yaml

支持的事件：

- `session_start`
- `pre_edit`
- `session_stop`
- `user_prompt_submit`

支持的 mode：

- `soft`
- `guard`
- `suggest`
- `off`

推荐默认：

- `session_start`: `soft`
- `pre_edit`: `guard`
- `session_stop`: `soft`
- `user_prompt_submit`: `enabled: false`

## 4. Memory Layout / 记忆目录

典型目录：

```text
.memory-center/
  workspace.yaml
  hooks.yaml
  rules/
  index/
  graph/
  memory/
  artifacts/
  instructions/
```

### 4.1 `provider-mcp-policy.json` / 外部 MCP Bridge 策略

可选策略文件位于 `.memory-center/provider-mcp-policy.json`，仅用于声明 Memory Center 可以作为 Client 直接调用的外部 HTTP MCP Server。它不是 workspace 初始化条件，缺失时 Bridge 仅返回空策略状态。

- 顶层：`schema_version: 1`、`providers: []`。
- Provider：`id`、`server`、`url`、`transport`、可选 `timeout_seconds`、`priority`、`tools`。
- `url` 只能为不含用户名、密码、查询串或 fragment 的 `http(s)` URL；`transport` 仅为 `sse|streamable_http`；`timeout_seconds` 被限制在 `1..60` 秒。
- Tool：`action`、`tool`、`mode`、`arguments`、可选 `capabilities`、`evidence_claim`、`confirmation_required`。`mode` 只能是 `read_only|controlled_write|destructive`；后两类始终需要明确确认。
- `arguments` 仅允许常量及 `{query}`、`{target}` 占位符，不能出现格式化属性、索引、转换或未知字段。
- 调用时 Client 必须先执行 `list_tools` 确认 `tool` 仍由外部 Server 暴露；不得支持 stdio、token/认证字段、任意工具或任意参数。
- 原始响应不进入图谱、SQLite、断言、审计或长期记忆；只在当前响应中展示，并派生不含正文的会话级 `EvidenceRef`。
- `read_only` Tool 声明 `capabilities: [code_navigation]` 后可作为动态 Provider 参与联邦初始化；它与静态 Provider 共享进程内健康路由，但不会触发后台探测。
- `evidence_claim` 必须是只含 `subject`、`predicate`、`value` 的模板。融合器仅比较显式 Claim；多个 Provider 的相同 Claim 值为 `CONSISTENT`，不同值为 `CONFLICT`，无 Claim 或独立 Provider 不足为 `INSUFFICIENT_EVIDENCE`。

## 5. Timeline / Ref / Receipt

当前正式 `timeline_item.kind`：

- `session_event`
- `write_receipt`
- `handoff`

短引用体系：

- `ref_id`
- `summary`
- `payload_ref` / `receipt_ref`

## 6. Compatibility / 兼容性

原则：

- MCP facade schema 兼容优先
- 破坏性变更必须同步 README / docs / changelog
- 原子 CLI / HTTP 能力可继续保留，但默认公开面以 facade 为主

## 7. 分析与经验演进契约 / Analysis and Skill Contracts

### `mc_analyze`

- `depth` 仅接受 `quick|standard|full`。
- `direction` 仅接受 `upstream|downstream|both`。
- `max_depth` 为 `1..6`。
- `analysis_status` 是 additive 字段：`complete` 表示所有请求阶段完成；`partial` 表示影响图已成功，但一项或多项辅助阶段不可用。
- `partial` 响应必须保留已有 `impact`、给出 `diagnostics` 和可行动的 `next_action`；不得把部分成功改写为 `internal_error`。
- MCP 错误的安全诊断可以含 `operation`、异常类别和 `trace_id`，不得包含私有路径、源码、密钥或异常正文。

### Delivery Skill

- 生命周期固定为 `candidate -> canary -> published|rolled_back`。
- `canary` 和候选不参与默认推荐。
- 发布至少需要三条带证据引用的成功观测，且没有失败观测。
- 回滚撤出默认推荐但不删除来源、观测和证据。
- 失败聚类和多轨迹归纳仅可显式离线触发，输出不保存原始源码、需求正文或验证日志。
