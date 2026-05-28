# UCAP Workspace Maintenance / `ucap-all` 工作区维护模板

本文档专门回答一个问题：

- `ucap-all` 这个公共 workspace 后面怎么新增项目？
- 怎么删除项目？
- 改完配置后怎么重建索引和验证？

当前公共 workspace：

- Workspace: `ucap-all`
- Root: `/Users/cuijiaqi/javaworkspace/ucap`
- Config: `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml`

---

## 1. 维护原则

`ucap-all` 现在是一个**统一公共空间**，所以所有项目维护都围绕同一个文件：

- [workspace.yaml](</Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml>)

后续新增或删除项目，推荐优先使用 CLI：

- `memory-center workspace add-service`
- `memory-center workspace remove-service`
- `memory-center workspace list-services`

如果确实需要，也可以手工改 `services`。

`reindex` 会自动一起更新：

- 文件索引
- Java 符号索引
- API 索引
- Feign 索引
- MQ 索引
- 配置索引
- 图谱数据库
- 语义索引

不需要你单独重建图谱或单独重建语义索引。

---

## 2. 新增项目模板

假设你要新增：

```text
/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-open-api
```

### 方式 A：推荐，直接用 CLI

服务型项目：

```bash
memory-center workspace add-service \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name ucap-cloud-open-api \
  --path ucap-cloud-open-api \
  --type spring-boot-service \
  --service-name ucap-cloud-open-api
```

公共库项目：

```bash
memory-center workspace add-service \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name ucap-cloud-open-api \
  --path ucap-cloud-open-api \
  --type shared-library \
  --service-name ucap-cloud-open-api \
  --tag common \
  --tag contract
```

查看当前服务列表：

```bash
memory-center workspace list-services \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

### 方式 B：手工修改 YAML

### 步骤 1：确认目录存在

```bash
ls /Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-open-api
```

### 步骤 2：编辑 `workspace.yaml`

在 `services:` 末尾增加一项。

#### 模板 A：Spring Boot 服务

```yaml
- name: ucap-cloud-open-api
  path: ucap-cloud-open-api
  type: spring-boot-service
  service_name: ucap-cloud-open-api
```

#### 模板 B：公共库 / 契约库

```yaml
- name: ucap-cloud-open-api
  path: ucap-cloud-open-api
  type: shared-library
  service_name: ucap-cloud-open-api
  tags:
    - common
    - contract
```

### 字段说明

- `name`
  建议和目录名一致
- `path`
  必须是相对 `root=/Users/cuijiaqi/javaworkspace/ucap` 的路径
- `type`
  常用：
  - `spring-boot-service`
  - `shared-library`
- `service_name`
  如果你知道真实 Spring/Nacos 服务名，优先填真实值
- `tags`
  只在公共库、契约库、共通模块上建议加

---

## 3. 新增项目后的命令模板

改完 `workspace.yaml` 后，固定跑这 4 步。

### 1. 重建索引

```bash
memory-center reindex \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

### 2. 健康检查

```bash
memory-center doctor \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --self-test
```

### 3. 查看状态

```bash
memory-center status \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

### 4. 做一次查询验证

```bash
memory-center query \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --text "ucap-cloud-open-api"
```

### 新增项目成功的判断标准

至少满足下面几项：

- `status` 里 `services` 数量增加
- `files` 增长
- `symbols` 增长
- `semantic_docs` 增长
- `doctor.ok = true`
- `query` 能查到新增项目名或其典型类

---

## 4. 删除项目模板

假设你要从公共空间里移除：

```text
/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-open-api
```

### 方式 A：推荐，直接用 CLI

```bash
memory-center workspace remove-service \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name ucap-cloud-open-api
```

这里的 `--name` 可以传：

- `service.name`
- 或 `service.path`

### 方式 B：手工修改 YAML

### 步骤 1：编辑 `workspace.yaml`

把对应的 `service` 整段删掉。

例如删除这段：

```yaml
- name: ucap-cloud-open-api
  path: ucap-cloud-open-api
  type: spring-boot-service
  service_name: ucap-cloud-open-api
```

### 步骤 2：重新构建索引

```bash
memory-center reindex \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

### 步骤 3：重新检查

```bash
memory-center doctor \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --self-test
```

### 步骤 4：验证它已经被移除

```bash
memory-center query \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --text "ucap-cloud-open-api"
```

删除后预期：

- 命中结果明显减少或查不到
- `status` 里 `services` 数量减少
- `files` / `symbols` / `semantic_docs` 有下降

---

## 5. 复制即用模板

### 新增一个服务型项目

```yaml
- name: REPLACE_PROJECT_NAME
  path: REPLACE_PROJECT_DIR
  type: spring-boot-service
  service_name: REPLACE_SERVICE_NAME
```

### 新增一个公共库项目

```yaml
- name: REPLACE_PROJECT_NAME
  path: REPLACE_PROJECT_DIR
  type: shared-library
  service_name: REPLACE_SERVICE_NAME
  tags:
    - common
    - contract
```

### 删除一个项目

操作方式：

1. 从 `workspace.yaml` 中删除对应块
2. 重新执行：

```bash
memory-center reindex \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

### 推荐的命令版模板

新增：

```bash
memory-center workspace add-service \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name REPLACE_PROJECT_NAME \
  --path REPLACE_PROJECT_DIR \
  --type spring-boot-service \
  --service-name REPLACE_SERVICE_NAME
```

删除：

```bash
memory-center workspace remove-service \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name REPLACE_PROJECT_NAME
```

---

## 6. 推荐维护顺序

以后每次新增项目，建议都按这个顺序走：

1. 确认项目目录已存在
2. 编辑 `workspace.yaml`
3. 执行 `reindex`
4. 执行 `doctor --self-test`
5. 执行 `status`
6. 执行 `query`

以后每次删除项目，建议按这个顺序走：

1. 编辑 `workspace.yaml`
2. 删除对应 `service`
3. 执行 `reindex`
4. 执行 `doctor --self-test`
5. 执行 `query` 验证

---

## 7. 常见注意点

### 注意 1：`path` 一定是相对路径

这里不能写绝对路径：

```yaml
path: /Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-open-api
```

应写成：

```yaml
path: ucap-cloud-open-api
```

### 注意 2：`service_name` 尽量写真实值

如果你知道真实的 Nacos / Spring 服务名，尽量不要只写目录名。

这样 Feign → 服务 的映射会更准。

### 注意 3：删除项目后一定要 `reindex`

只改 YAML 不够。

如果不 `reindex`，旧索引和旧图谱还在。

### 注意 4：新增项目后不只看 `status`

一定要再跑一次 `query` 或 `context`，确认它真的能查到。

---

## 8. 推荐关联文档

- [UCAP_ALL_SETUP.md](./UCAP_ALL_SETUP.md)
- [LOCAL_USAGE_GUIDE.md](./LOCAL_USAGE_GUIDE.md)
- [WORKSPACE_SPEC.md](./WORKSPACE_SPEC.md)
