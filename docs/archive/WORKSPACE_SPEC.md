# Workspace Spec / 工作区配置规范

## 中文

Memory Center 使用 `.memory-center/workspace.yaml` 描述一个多项目工作区。

```yaml
workspace: content-risk-platform
root: /Users/you/javaworkspace/workspace/origin
language:
  - zh-CN
  - en-US
services:
  - name: article-service
    path: article-service
    type: spring-boot-service
    service_name: article-service
    port: 18081
    tags: [business]

  - name: common-api
    path: common-api
    type: shared-library
    tags: [contract]
```

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `workspace` | 是 | 工作区名称。 |
| `root` | 是 | 多项目根目录。相对路径会基于 `workspace.yaml` 所在目录解析。 |
| `language` | 否 | 文档语言偏好，例如 `zh-CN`、`en-US`。 |
| `services` | 是 | 服务和公共库列表。 |
| `services[].name` | 是 | Memory Center 内部项目名。 |
| `services[].path` | 是 | 项目路径。既支持相对于 `root` 的路径，也支持绝对路径；绝对路径可用于把分散在不同父目录下的项目纳入同一个 workspace。 |
| `services[].type` | 否 | `spring-boot-service`、`spring-cloud-gateway`、`spring-boot-task`、`shared-library`。 |
| `services[].service_name` | 否 | Spring Cloud 注册名，通常对应 `spring.application.name`。 |
| `services[].port` | 否 | 服务端口。 |
| `services[].tags` | 否 | 标签，例如 `contract`、`common`、`engine`、`task`。 |

### Multi-Root 示例（推荐）/ Multi-Root Example (Recommended)

当项目分散在不同父目录时，可以在同一个 workspace 里混用相对路径和绝对路径：

```yaml
workspace: shared-engineering-workspace
root: /Users/you/work/a
language:
  - zh-CN
  - en-US
services:
  - name: account-service
    path: account-service
    type: spring-boot-service
    service_name: account-service

  - name: billing-service
    path: /Users/you/work/b/billing-service
    type: spring-boot-service
    service_name: billing-service

  - name: common-contract
    path: /Users/you/work/c/common-contract
    type: shared-library
    tags: [contract]
```

说明：

- `root` 仍然是 workspace 默认根目录。
- `services[].path` 为相对路径时，按 `root` 解析。
- `services[].path` 为绝对路径时，按绝对路径直接索引，不要求在 `root` 目录下。

## English

The workspace file declares repositories and services managed by Memory Center.

Relative `root` values are resolved against the directory containing `workspace.yaml`, which makes examples portable.
