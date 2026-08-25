# DSH 本地执行观测 / Local DSH Execution Observability

Memory Center can ingest sanitized execution metadata from the optional [Memory Center DSH Plugin](../memory-center-dsh-plugin/README.zh.md). The integration is local-only: DSH writes an inbox file, and Memory Center imports it explicitly. Neither component requires a cloud service.

Memory Center 可从可选的 [Memory Center DSH 插件](../memory-center-dsh-plugin/README.zh.md)导入脱敏执行元数据。该集成仅在本地运行：DSH 写入 inbox 文件，Memory Center 显式导入；两个组件都不依赖云服务。

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

## Enable / 启用

The plugin is `OFF` by default. Enable metadata capture only for the selected launch.

插件默认 `OFF`。仅在启动指定 profile 时启用元数据采集。

```sh
MEMORY_CENTER_WORKSPACE=/absolute/path/to/.memory-center/workspace.yaml \
MEMORY_CENTER_DSH_MODE=METADATA \
dsh --profile web
```

`METADATA` writes identifiers, time, model/tool names, token counts, statuses, and error classes. It never writes prompts, message bodies, tool arguments/results, request headers, or cwd. `DIAGNOSTIC` additionally writes only a SHA-256 body hash.

`METADATA` 写入标识、时间、模型/工具名称、Token 数、状态与错误类别，不写入 prompt、消息正文、工具参数/结果、request header 或 cwd。`DIAGNOSTIC` 只额外写入 body 的 SHA-256。

## Import and inspect / 导入与查看

```sh
memory-center agent-execution-import \
  --workspace /absolute/path/to/.memory-center/workspace.yaml

memory-center agent-execution-summary \
  --workspace /absolute/path/to/.memory-center/workspace.yaml
```

The summary reports hashed DSH session IDs, turn/step counts, model/tool duration, first-token latency, token accounting, and failures. The inbox is append-only and imports are idempotent by event ID.

摘要返回哈希化的 DSH session ID、turn/step 数量、模型/工具耗时、首 Token 延迟、Token 统计和失败。inbox 仅追加，导入按 event ID 幂等。

## Failure behavior / 失败行为

The plugin is fail-open. Queue overflow, local write failure, and shutdown timeout may drop observability records, but never fail the DSH agent loop. Import failures do not modify DSH session data or Memory Center code/task memory.

插件为 fail-open。队列溢出、本地写入失败和 shutdown 超时最多丢失观测记录，绝不会让 DSH agent loop 失败。导入失败不会修改 DSH session 数据，也不会修改 Memory Center 的代码/任务记忆。
