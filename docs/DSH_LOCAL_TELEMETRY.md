# DSH 本地执行观测 / Local DSH Execution Observability

Memory Center can ingest sanitized execution metadata from the optional [Memory Center DSH Plugin](../memory-center-dsh-plugin/README.zh.md). The integration is local-only: DSH writes an inbox file and the plugin automatically triggers local import after flush or shutdown. The same plugin also provides a DSH-local, read-only workbench bridge for Memory Center workspace views. Neither component requires a cloud service.

Memory Center 可从可选的 [Memory Center DSH 插件](../memory-center-dsh-plugin/README.zh.md)导入脱敏执行元数据。该集成仅在本地运行：DSH 写入 inbox，插件会在 flush 或 shutdown 后自动触发本地导入；同一插件还为 Memory Center 工作台提供 DSH 管理的只读本地 bridge。两个组件都不依赖云服务。

## Install / 安装

Install the bundle into one DSH profile. Other profiles are unchanged.

将 bundle 安装到一个 DSH profile；其他 profile 不受影响。

```sh
dsh plugin --profile web add /absolute/path/to/memory-center-dsh-plugin
dsh --profile web --dump-config
```

Remove the bundle to restore that profile's prior composition.

删除 bundle 即可恢复该 profile 之前的组合。

```sh
dsh plugin --profile web remove memory-center-dsh-plugin
```

## Enable and workbench / 启用与工作台

Installation enables the plugin for that profile. For every DSH session, it discovers `.memory-center/workspace.yaml` from the session cwd; sessions outside a Memory Center workspace are skipped and DSH remains unaffected. `MEMORY_CENTER_WORKSPACE` may override discovery with one explicit workspace file, but is not an enable switch.

安装即为该 profile 启用插件。每个 DSH session 会从 cwd 向上发现 `.memory-center/workspace.yaml`；不属于 Memory Center workspace 的 session 会被跳过，DSH 不受影响。`MEMORY_CENTER_WORKSPACE` 可覆盖为一个固定 workspace 文件，但不是启用开关。

After DSH starts, the plugin lazily starts and manages a loopback-only, read-only Memory Center query bridge for the detected workspace. The DSH Web `Memory Center` tab therefore does not require a separate `memory-center serve-http` command. Closing DSH stops the bridge; Memory Center itself remains independently usable through CLI, MCP, or HTTP.

DSH 启动后，插件会按需启动并管理已发现 workspace 的、仅绑定 loopback 的只读 Memory Center 查询 bridge。因此 DSH Web 的 `Memory Center` 标签不需要另行运行 `memory-center serve-http`。关闭 DSH 会停止 bridge；Memory Center 本体仍可独立通过 CLI、MCP 或 HTTP 使用。

Captured metadata contains identifiers, time, model/tool names, token counts, statuses, and error classes. It never writes prompts, message bodies, tool arguments/results, request headers, or cwd. `diagnosticHash: true` additionally writes only a SHA-256 body hash.

采集元数据包含标识、时间、模型/工具名称、Token 数、状态与错误类别，不写入 prompt、消息正文、工具参数/结果、request header 或 cwd。`diagnosticHash: true` 只额外写入 body 的 SHA-256。

## Import and inspect / 导入与查看

```sh
memory-center agent-execution-import \
  --workspace /absolute/path/to/.memory-center/workspace.yaml

memory-center agent-execution-summary \
  --workspace /absolute/path/to/.memory-center/workspace.yaml
```

The summary reports hashed DSH session IDs, turn/step counts, model/tool duration, first-token latency, token accounting, and failures. The inbox is append-only and imports are idempotent by event ID. Manual import remains only a troubleshooting path.

摘要返回哈希化的 DSH session ID、turn/step 数量、模型/工具耗时、首 Token 延迟、Token 统计和失败。inbox 仅追加，导入按 event ID 幂等。手工导入仅用于排障。

## Failure behavior / 失败行为

The plugin is fail-open. Queue overflow, local write failure, and shutdown timeout may drop observability records, but never fail the DSH agent loop. Import failures do not modify DSH session data or Memory Center code/task memory.

插件为 fail-open。队列溢出、本地写入失败和 shutdown 超时最多丢失观测记录，绝不会让 DSH agent loop 失败。导入失败不会修改 DSH session 数据，也不会修改 Memory Center 的代码/任务记忆。
