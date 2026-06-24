# codebase-memory-mcp 关键设计参考 / Key Design Reference

> 本文档是对本地参考项目 `/Users/cuijiaqi/Ai-common-skills/codebase-memory-mcp`
> 的设计摘录和 Memory Center 映射，不复制对方源码，不引入对方作为运行时依赖。
>
> This document summarizes design ideas from the local reference project
> `/Users/cuijiaqi/Ai-common-skills/codebase-memory-mcp`. It does not copy source
> code and does not make CBM a runtime dependency.

---

## 1. 参考定位 / Reference Scope

`codebase-memory-mcp`（下文简称 CBM）对 Memory Center 最有价值的不是 MCP
tool 名称，而是底层工程路线：

- 极快索引：RAM-first pipeline、批量写入、压缩、单次 dump。
- 结构化图优先：函数、类、路由、调用链、跨服务边都是一等图节点/边。
- tree-sitter + 类型解析：AST 负责结构，Hybrid LSP 风格解析负责更准的调用和类型关系。
- 查询少读文件：graph / FTS / semantic / trace 工具优先，减少 grep/read/token。
- 增量与共享图：watcher 自动更新，压缩 graph artifact 可作为团队共享启动缓存。
- 评测驱动：多语言 benchmark 用固定问题维度、真实仓库、token/tool/time/quality 指标评估。

对 Memory Center 的结论：

- CBM 应作为 **P0/P1 索引性能和图查询质量的参考设计**。
- 不应该把 CBM 当作要复制的产品、CLI、源码目录或运行时依赖。
- 当前最值得吸收的是“索引热路径设计”和“评测方法”，不是 158 语言覆盖。

---

## 2. 关键设计 / Key Designs

### 2.1 RAM-first indexing pipeline

CBM 把索引热路径尽量放在内存中完成：文件读取、AST 提取、关系构建、SQLite
批量落盘在一个高吞吐 pipeline 内完成，最后一次性持久化。

Memory Center 映射：

- 当前瓶颈已经不是 SQLite PRAGMA，而是 Java parser 双轨、`asdict`、metadata
  高频序列化。
- P0 优先优化 Python 热路径：减少重复 parser、减少递归复制、减少小对象 JSON
  序列化。
- 中期可以评估“内存 staging + 批量 graph 写入 + 单次 commit / dump”。

不直接复制：

- 不在本阶段用 C 重写 indexer。
- 不引入 LZ4 / zstd 作为核心运行依赖，除非真实 benchmark 证明收益大于复杂度。

### 2.2 tree-sitter as structure, type resolver as precision layer

CBM 的思路是：tree-sitter 提供语法结构，但更准确的调用关系需要额外类型解析层。
其 Hybrid LSP 风格解析会结合 import、继承、泛型、lambda、类层级等信息，修正
`CALLS` / `USAGE` / resolved calls。

Memory Center 映射：

- 现有 `TreeSitterJavaParser` 已能提取 Java 结构，但仍依赖 regex merge 做安全网。
- 现有 `JavaCallResolver` 已开始做 same-class / package / import / static-import 分层解析。
- 下一步不应只“关掉 regex”，而要配套 parser differential 与 call resolution gate，
  把 regex 的安全网转成明确的 resolver / extractor 能力。

优先吸收：

- Java-specific resolver 分层：local scope、same class、imports、static imports、
  inheritance/interface、Spring bean injection、Feign target、Controller target。
- 每类 resolution level 都要可解释、可降级、可评测。

### 2.3 Graph-first query surface

CBM 将 `CALLS`、`IMPORTS`、`DEFINES`、`IMPLEMENTS`、`HTTP_CALLS`、
`DATA_FLOWS` 等关系作为图查询核心，并用 trace / architecture / impact / search
工具替代大量文件读取。

Memory Center 映射：

- Memory Center 已有 graph store、walkthrough、impact、context pack、domain flow。
- 下一步要继续减少“查到一堆文本”而不是“返回一条可执行链路”的情况。
- `mc_lookup(auto)` 应优先返回入口、主链路、证据文件、completion status 和下一步。

优先吸收：

- 图关系要区分事实边、推断边、派生边。
- 调用链查询不应混入 `DECLARES` / `CONTAINS` 这类结构边作为行为链主结果。
- 影响分析应优先返回 graph-aware change bundle，而不是散乱候选。

### 2.4 FTS / BM25 / semantic as candidate sources, graph as constraint

CBM 的搜索不是单一 grep：FTS、结构图、语义相似、路由/类型/签名信号会合并打分。
但结构问题最终仍要落回图关系验证。

Memory Center 映射：

- 当前 hybrid retrieval 已有 exact / graph / BM25 / semantic / optional vector。
- 下一步要强化 source diagnostics 和真实 case replay，避免 semantic 命中把入口方法挤出结果。
- full-chain 场景应继续坚持 exact + graph 硬约束。

优先吸收：

- 查询先得到候选集，再用 graph / ontology / freshness 约束过滤。
- 每个 source 的贡献和禁用原因必须可见。
- token 和 latency 不以牺牲 anchor recall 为代价。

### 2.5 Watcher, incremental indexing, and shared graph artifact

CBM 支持后台 watcher 和 compressed graph artifact：首次索引后可共享压缩图，后续只对
本地 diff 做增量更新。

Memory Center 映射：

- 当前已有 freshness、changed-path reindex、删除/移动感知 reconciliation。
- 中期可以评估 `.memory-center` 下的可选 graph snapshot / bootstrap artifact，但不能默认提交私有索引。
- 对私有 UCAP 工作区，snapshot 只能本地生成和本地使用；公开仓库必须避免泄漏路径、服务名和源码片段。

优先吸收：

- connect-time catch-up：启动时发现 stale，优先给出 reindex / live read / incremental catch-up 建议。
- 增量索引的验收要覆盖新增、修改、删除、移动。
- graph artifact 若实现，必须有隐私保护和 opt-in 开关。

### 2.6 Evaluation methodology

CBM 的 benchmark 用固定问题维度评估真实仓库：定义/API discovery、调用关系、目标源码、
架构结构、跨切面/语义问题，并记录质量、token、工具调用、延迟和 zero-result。

Memory Center 映射：

- 当前已有 Golden Benchmark、Java call resolution gate、真实 UCAP baseline。
- 下一步要把 P0 性能修复也纳入同一评测口径，避免只看单点 micro benchmark。
- 新能力完成说明必须报告真实 case 指标，而不是只说“单测通过”。

优先吸收：

- 每个真实 case 标注问题维度：walkthrough / impact / retrieval / parser / call-resolution。
- 统一记录 anchor recall、edge recall、forbidden hit、latency、token、invalid search suggestion。
- 失败 case 必须能落到 parser、resolver、graph、retrieval 或 rendering 某一层。

---

## 3. 对下一步开发的影响 / Impact on Roadmap

CBM 参考将 P0 的优先级进一步明确为：

1. **先设计索引热路径收口方案**：避免零散修 `asdict`、`json.dumps`、parser 双轨后又返工。
2. **再做低风险热点修复**：`JavaSymbol.to_dict()`、metadata 空 dict 快路径。
3. **最后关闭 parser 双轨**：必须依赖 differential / Java call-resolution / Golden gate。

建议新增 P0-0：

- 输出 `Index Hot Path Design` 小设计，明确哪些 CBM 思路本阶段吸收，哪些暂缓。
- 不超过一个工作日，不能变成长期调研。
- 完成后立刻进入 P0 热点修复。

---

## 4. 不做什么 / Non-Goals

- 不复制 CBM 源码。
- 不把 CBM 设为 Memory Center 的 backend provider。
- 不在当前阶段追求 158 语言覆盖。
- 不把 Memory Center 改成单静态 C binary。
- 不引入必选外部服务、外部 LSP 进程或远程 embedding。
- 不提交任何 CBM 派生源码、私有 UCAP 索引或私有 graph artifact。

---

## 5. 后续引用方式 / How to Use This Reference

后续计划和实现只引用本文档，不再直接依赖 CBM 项目实时状态。

允许引用：

- `docs/references/codebase-memory-mcp.md`
- 本地只读参考路径：`/Users/cuijiaqi/Ai-common-skills/codebase-memory-mcp`

不允许：

- 复制 CBM 源码到本仓库。
- 把 CBM 的 CLI / MCP tool surface 当作必须兼容目标。
- 用 CBM benchmark 数字替代 Memory Center 真实 UCAP gate。
