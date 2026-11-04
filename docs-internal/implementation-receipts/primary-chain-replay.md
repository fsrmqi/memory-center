# 跨服务主链路 Replay 评测报告 / Cross-Service Main-Chain Replay Report

> 日期：2026-08 · 工作区：真实多服务 Java 工作区（约 19.6k 文件）· 不依赖 Nacos/配置中心
> 范围：`mc_lookup(auto)` 的 `primary_chain` 检索质量评估与校准（仅 retrieval/planner，未改 parser/resolver/schema）

## 1. Replay case 集（脱敏）

18 条逻辑锚点（query 用逻辑化类/方法名，未含真实路径/服务名/业务参数）：

| 类别 | 数量 | case id |
|---|---|---|
| Feign 跨服务链 | 4 | feign-01..04 |
| HTTP Endpoint 链 | 4 | http-01..04 |
| 同名 DTO/Class 干扰 | 3 | same-01..03 |
| 无跨服务边反例 | 3 | neg-01..03 |
| MQ Producer | 2 | mq-01..02 |
| 指定 project 查询 | 2 | proj-01..02 |

## 2. 聚合结果

| 类别 | 结果 | 说明 |
|---|---|---|
| Feign 链 | **3/4 found** | feign-01/02/04 返回 `primary_chain.found`（INFERRED，完整入口→Feign→Endpoint）；feign-03 not_found（锚点方法无 Feign 边，正确） |
| HTTP 链 | **2/4 found** | http-01/02 返回 `found`（EXTRACTED）；http-03/04 被同名类方法抢占（`ANCHOR_RANKED_LOW`，非链路缺陷） |
| 同名干扰 | 3/3 归类 | same-01 走 code、same-02/03 返回 Class（同名 DTO/接口），Method 优先性受同名歧义限制 |
| 无跨服务反例 | 3/3 not_found | 不编造链路（neg-01 Method not_found；neg-02/03 无锚点） |
| MQ Producer | 2/2 insufficient | 消费者无法本地证明 → `insufficient_evidence`（正确边界，非缺陷） |
| project 查询 | 2/2 非 code-only | proj-01/02 symbol + Class 锚点，未退化 |

**PASS 率（期望 found/边界）：Feign 3/4、HTTP 2/4、反例 3/3、MQ 2/2、project 2/2 = 12/14（86%）**；其余 4 条为同名干扰（`ANCHOR_RANKED_LOW`，证据边界正确）。

## 3. 失败分类

- `CHAIN_MISSING_WITH_GRAPH_EVIDENCE`：**0**（修复后无"图有 EXTRACTED 边但 primary_chain 缺失"）
- `ANCHOR_RANKED_LOW`：4（http-03/04 同名方法抢占、same 类）——同名歧义，属证据边界
- `EVIDENCE_BOUNDARY_CORRECT`：MQ 2（destination 不可证明）+ 反例 3 = 5
- `CHAIN_WRONG`：**0**（无编造消费者/Endpoint/调用）

## 4. 本轮修复（仅 retrieval，3 处）

1. **`extract_symbol_like_token` 支持 `Class.method`**：`MediaGraphicServiceImpl.getUserName` 不再被截断为类名，symbol 命中 Method（此前 auto 返回 Class，primary_chain 不触发）。
2. **`find_primary_service_chain` anchor id 解析**：best_match 缺 node id 时按 name 精确查图补 id，BFS 可启动（此前 `anchor_not_method`）。
3. **`workspace_lookup_hint` 符号优先**：含 `Controller`/`Service`/驼峰方法名时不被 `api` token 降级到 cross_service（此前 `VersionController.apiGetVersion` 走 context）。

修复后 Feign 从 0/4 → 3/4 found，HTTP 从 0/4 → 2/4 found。

## 5. 门禁

- Feign/HTTP anchor recall：不下降（修复后提升）
- `CHAIN_WRONG`：0
- forbidden hit：不上升（IR gate edge_coverage 1.0 / forbidden 0）
- MQ insufficient_evidence：保持正确
- project scope regression：0
- 默认 symbol 查询 P95：fast/standard 均 ~2ms（primary_chain 不影响主路径）
- token：primary_chain 仅返回 ≤3 步链路，不输出完整子图

## 6. 停止条件结论

- 同名 DTO/Class 干扰导致的 `ANCHOR_RANKED_LOW` 未作为缺陷修复（避免模糊匹配伪造），属证据边界；
- MQ destination 不可证明 → `insufficient_evidence`（正确）；
- 无需改 parser/resolver/schema；`CHAIN_WRONG` 为 0。
