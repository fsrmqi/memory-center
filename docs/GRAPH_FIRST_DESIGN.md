# Graph-first Design / 图优先设计

Memory Center 1.1 introduces a graph-first architecture inspired by modern code intelligence systems.

记忆中心 1.1 引入图优先架构：索引阶段提前构建代码关系、服务关系、契约关系、消息关系和经验关系，Agent 查询时直接基于图返回上下文。

## Graph nodes / 图节点

- Workspace / 工作区
- Service / 服务
- File / 文件
- Class / 类
- Method / 方法
- Field / 字段
- Endpoint / HTTP 接口
- FeignClient / Feign 客户端
- FeignMethod / Feign 方法
- MQTopic / 消息主题
- MQConsumer / 消费者
- TaskMemory / 任务记忆
- Rule / 规则

## Graph edges / 图边

- CONTAINS：包含关系
- DECLARES：声明关系
- EXPOSES_ENDPOINT：Controller 暴露接口
- CALLS_SERVICE：Feign 调用服务
- IMPLEMENTS_FEIGN：Feign 方法匹配 Controller Endpoint
- CONSUMES_TOPIC：消费者消费 Topic
- IMPORTS：Java import 依赖
- RELATED_TO_MEMORY：与历史任务相关

## Why local SQLite / 为什么使用本地 SQLite

- Zero external server / 不依赖外部服务
- Easy to inspect and back up / 易检查、易备份
- Portable for open-source users / 适合公共组件传播
- Can later be replaced by Kuzu, Neo4j or other graph engines / 后续可替换为专用图数据库

## Agent flow / Agent 使用流程

1. `workspace_sniff_tool(intent)`
2. `memory_query_tool(query)`
3. `memory_context_tool(name)`
4. `memory_impact_tool(target)`
5. `workspace_check_rules_tool(...)`
6. `workspace_record_case_tool(...)`
