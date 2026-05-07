# Memory Center 设计说明

## 目标

为 AI 编程助手提供项目记忆 MCP 服务，重点支持 Spring Cloud 多项目场景。

## 核心闭环

```text
任务输入 -> workspace_sniff -> 规则/契约检查 -> 代码修改 -> 验证 -> workspace_record_case
```

## 两层上下文

1. Workspace 级：跨项目服务拓扑、契约、MQ、公共规则、跨服务经验。
2. Project 级：单项目文件索引、Java 符号、局部规则、文件摘要。

## 第一版索引能力

- Java class/interface/method/import/annotation
- `@RestController` + Mapping API
- `@FeignClient` 跨服务调用
- `@KafkaListener`
- `@RocketMQMessageListener`
- `application.yml` / `bootstrap.yml`

## 后续增强

- tree-sitter-java AST
- Maven dependency graph
- Nacos 远程配置同步
- Git commit / PR 任务归档
- 向量检索
- 图数据库或 GraphRAG
