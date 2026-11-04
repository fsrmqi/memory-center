# 本地执行观测边界 / Local Execution Observability Boundary

> 文档类型：设计边界（decision）。**本仓库不发布宿主插件**：执行元数据由外部宿主适配器采集，Memory Center 只定义接收与聚合边界。

Memory Center 可以接收宿主侧脱敏后的执行元数据，用于回答"这次任务花了多少时间、模型与工具各占多少、哪一步失败"。采集器是可选的，由宿主侧集成提供，不属于本仓库的发布物；Memory Center 本体不依赖云服务，也不因为没有采集器而降低能力。

Memory Center can ingest sanitized execution metadata produced by a host-side adapter to answer how long a task took, how much of it was model versus tool time, and where it failed. The collector is optional and ships outside this repository; Memory Center itself never requires a cloud service and loses no capability when no collector is installed.

## 设计边界 / Design Boundary

- Memory Center 只定义**接收格式**与**聚合口径**；宿主的采集实现、安装方式与 UI 呈现由对应宿主集成决定，不在本文档承诺。
- 采集器把事件写入 `.memory-center/memory/agent-execution-inbox/` 下的追加式 NDJSON；导入按 event ID 幂等。
- 没有采集器时服务正常运行；该能力不能成为任何主链路的必需前置。

- Memory Center defines only the **ingest format** and **aggregation semantics**; install instructions and UI live with the host integration, not here.
- The collector appends NDJSON events under `.memory-center/memory/agent-execution-inbox/`; imports are idempotent by event ID.
- Without a collector the service runs normally; this capability is never a prerequisite of any primary path.

## 字段与隐私 / Fields and Privacy

采集元数据只包含标识、时间、模型/工具名称、Token 数、状态与错误类别。它不写入 prompt、消息正文、工具参数/结果、request header 或工作目录。可选的正文哈希只写 SHA-256，不写正文。

Captured metadata contains only identifiers, time, model/tool names, token counts, statuses, and error classes. It never writes prompts, message bodies, tool arguments/results, request headers, or the working directory. The optional body mode writes a SHA-256 digest only.

聚合结果返回的是**哈希化会话标识**、turn/step 数量、模型与工具耗时、首 Token 延迟、Token 统计与失败分类。哈希化不可逆推原始会话或路径。

The summary reports hashed session identifiers, turn/step counts, model and tool duration, first-token latency, token accounting, and failure classes. Hashing is not reversible into raw sessions or paths.

## 失败行为 / Failure Behavior

采集器必须 fail-open：队列溢出、本地写入失败与关闭超时最多丢失观测记录，绝不能让 Agent 主循环失败。导入失败不修改宿主会话数据，也不修改 Memory Center 的代码或任务记忆。

The collector must be fail-open: queue overflow, local write failure, and shutdown timeout may drop observability records but must never fail the agent loop. Import failures modify neither host session data nor Memory Center code/task memory.

## 非目标 / Non-goals

- 不做跨机器的遥测汇聚，不上传任何执行元数据。
- 不把观测数据写入知识库或长期记忆；它只作为本机运行诊断。
- 不承诺具体采集器的安装路径、命令或宿主页面入口。

- No cross-machine telemetry aggregation and no upload of execution metadata.
- Observability data is never promoted into the knowledge base or long-term memory; it stays local diagnostics.
- No install paths, commands, or host UI entry points are promised for any specific collector.
