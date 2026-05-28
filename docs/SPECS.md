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
