# UCAP All Setup / `ucap-all` 公共空间落地说明

本文档记录当前这套本地公共空间的实际落地方式，面向：

- 本机路径：`/Users/cuijiaqi/javaworkspace/ucap`
- 公共 workspace 名称：`ucap-all`
- 仓库地址：[fsrmqi/memory-center](https://github.com/fsrmqi/memory-center)

这不是通用示例，而是你当前机器上已经落地的一套真实配置说明。

---

## 1. 目标

目标是把下面这些项目统一纳入一个公共的 Memory Center 空间，而不是拆成多个 workspace：

- `/Users/cuijiaqi/javaworkspace/ucap/ucap-rap-common`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-back`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-datainterface`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-datainterface-other`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-task`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-newmedia-web`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-newmedia-back`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-website-web`
- `/Users/cuijiaqi/javaworkspace/ucap/ucap-cloud-website-back`

最终效果是：

- 统一索引
- 统一图谱
- 统一语义索引
- 统一历史记忆
- 统一查询、上下文、影响分析入口

---

## 2. 最终目录结构

公共空间目录：

```text
/Users/cuijiaqi/javaworkspace/ucap/.memory-center/
```

关键文件：

- workspace 配置：
  `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml`
- 使用说明：
  `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/UCAP_ALL_USAGE.md`
- 文件/符号/API/Feign/MQ/Config 索引：
  `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/index/`
- 图谱数据库：
  `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/graph/graph.db`
- 历史任务记忆：
  `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/memory/cross-service-task-memory.jsonl`

---

## 3. 安装前提

当前项目要求：

- Python `>= 3.10`

你本机一开始只有：

- `/usr/bin/python3`
- 版本 `3.9.6`

因此直接执行 `pipx install .` 会失败，典型报错是：

```text
Package 'memory-center' requires a different Python: 3.9.6 not in '>=3.10'
```

### 正确做法

先安装 Python 3.10+，推荐 3.11。

例如通过 Homebrew：

```bash
brew install python@3.11
```

然后用这个 Python 安装 CLI。

---

## 4. 一条命令安装 CLI

仓库本地安装：

```bash
cd /Users/cuijiaqi/Ai-common-skills/memory-center
bash install.sh
```

远程安装：

```bash
curl -fsSL https://raw.githubusercontent.com/fsrmqi/memory-center/main/install.sh | bash
```

### 说明

安装脚本默认用 `pipx`。

如果 `pipx` 已安装但当前 shell 找不到，通常是 `PATH` 问题。

例如你本机上，`pipx` 装在：

```bash
$HOME/Library/Python/3.9/bin
```

需要先临时加 PATH：

```bash
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
```

为了长期生效，建议写入：

```bash
~/.zshrc
```

加入：

```bash
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
```

然后执行：

```bash
source ~/.zshrc
```

### 安装后验证

```bash
memory-center --version
```

---

## 5. `ucap-all` 的 workspace 配置

当前使用的 workspace 文件：

- [workspace.yaml](</Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml>)

当前配置的核心参数：

- `workspace: ucap-all`
- `root: /Users/cuijiaqi/javaworkspace/ucap`

它把上面那 9 个目录作为 `services` 纳入统一公共空间。

---

## 6. 已执行的初始化步骤

这次实际已经完成过以下动作：

1. 创建：
   `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/`
2. 写入 `workspace.yaml`
3. 生成默认规则
4. 生成本地 instructions
5. 执行首次 `reindex`
6. 执行 `doctor --self-test`

也就是说，这个公共空间已经不是“待初始化”，而是“已经可用”。

---

## 7. 当前索引结果

当前这套 `ucap-all` 公共空间的实际状态是：

- `files`: `10820`
- `symbols`: `9823`
- `apis`: `4297`
- `feigns`: `254`
- `mq`: `0`
- `semantic_docs`: `183851`

图谱规模：

- `nodes`: `183851`
- `edges`: `714046`

语义索引状态：

- `backend`: `sparse`
- `requested_backend`: `sparse`
- `ready`: `true`

`doctor --self-test` 结果：

- `ok: true`

---

## 8. 当前这个公共空间的现实边界

这一点很重要。

虽然你现在已经有了一个统一公共空间，但这份配置目前是：

- 以“项目根目录”为 `service`

例如：

- `ucap-cloud-back`
- `ucap-cloud-task`
- `ucap-cloud-website-back`

而不是：

- 内部更细的 `*-app` 模块级 service

### 这意味着什么

优点：

- 现在已经能统一查代码、查上下文、查影响面
- 公共历史记忆可以开始积累
- 不需要拆多个 workspace

限制：

- 一些 Feign `target_service` 仍然会显示成 `unknown-service`
- 跨微服务精确映射还不够细

所以当前阶段更适合把它理解成：

- “统一代码记忆中心”

如果后面想进一步提升微服务级精度，下一步可以把 `services` 从“项目根目录级”细化到“真实 app 模块级”。

---

## 9. 日常怎么用

### 看状态

```bash
memory-center status \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

### 健康检查

```bash
memory-center doctor \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --self-test
```

### 任务上下文

```bash
memory-center sniff \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --intent "修改 Feign DTO 和网站任务链路"
```

### 查询

```bash
memory-center query \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --text "SomeFeignClient SomeDto some-config-key"
```

### 上下文

```bash
memory-center context \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name SomeFeignClient
```

### 影响分析

```bash
memory-center impact \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --target SomeFeignClient
```

### 变更影响

```bash
memory-center detect-changes \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --scope staged
```

---

## 10. 历史记忆怎么沉淀

公共历史记忆统一落在：

```text
/Users/cuijiaqi/javaworkspace/ucap/.memory-center/memory/cross-service-task-memory.jsonl
```

推荐使用 CLI：

```bash
memory-center record-case \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --task "修复公共 DTO 兼容问题" \
  --project ucap-cloud-back \
  --project ucap-cloud-task \
  --file ucap-cloud-back/src/main/java/.../SomeDto.java \
  --file ucap-cloud-task/src/main/java/.../SomeConsumer.java \
  --flow "query -> context -> impact -> verify" \
  --risk-point "Feign 契约兼容" \
  --risk-point "历史消息兼容" \
  --verified-by integration-test
```

建议只记录：

- 跨项目经验
- 已验证的公共 DTO / Feign / MQ / 配置问题
- 后续大概率复用的处理路径

---

## 11. 后续维护建议

### 什么时候重新索引

以下情况建议重新执行：

```bash
memory-center reindex \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

场景包括：

- 新增项目
- 新增模块
- 改了 `workspace.yaml`
- 想切换语义 backend
- 索引过旧

### 什么时候细化 `services`

如果你开始明显遇到这些问题：

- Feign target 频繁 `unknown-service`
- 同一个根目录里其实有很多真正独立服务
- 想看更精确的微服务拓扑

那就可以进入下一阶段：

- 按真实 `*-app` 模块细化 `services`

---

## 12. 常见问题

### Q1：为什么一开始 `memory-center` 命令找不到？

常见原因有两个：

1. `pipx` 不在 PATH
2. 当前 Python 版本只有 3.9，不满足项目要求

### Q2：为什么 `pipx install .` 失败？

因为当前项目要求：

```text
Python >= 3.10
```

而你本机最开始只有：

```text
Python 3.9.6
```

### Q3：为什么 `mq` 计数是 0？

这说明当前这些项目里，按现有轻量规则并没有扫出可识别的 `@KafkaListener` / `@RocketMQMessageListener` 命中，或者相关代码不在这 9 个项目里。

这不影响其他索引能力使用。

### Q4：当前这份公共空间是不是已经能用了？

可以用，而且已经可用。

当前最适合用来做：

- 统一代码检索
- 统一上下文分析
- 统一影响分析
- 公共历史记忆沉淀

---

## 13. 关联文档

- [README.md](../README.md)
- [LOCAL_USAGE_GUIDE.md](./LOCAL_USAGE_GUIDE.md)
- [MCP_TOOLS.md](./MCP_TOOLS.md)
- [WORKSPACE_SPEC.md](./WORKSPACE_SPEC.md)
