# ADR-0003：移除 GraphViewBuilder 图谱视图模块

## 状态

已接受。

## 背景

`core/views/builder.py`（`GraphView` / `GraphViewBuilder`）提供 architecture / business / change 三种 persona 化图谱视图，依赖 `domain.extractor`、`reasoning.risk` 与 `RuntimeStore`。全仓核查确认：

- 没有任何生产调用方：MCP、CLI、HTTP、hooks、application 层均未暴露或引用该模块。
- 仅有 3 个回归测试文件直接 import 它（`test_v3_extended.py`、`test_h_i_series.py`、`test_v3_ontology_mcp.py`），其中引用的“§20.3-20.4 views/”在现行 `docs/REFERENCE.md` 中已不存在。
- 其能力面已被更丰富的 `mc_onboard`、`mc_domain`、`mc_context_pack` facade 覆盖。

它是一个"只有一个适配器的假设性接缝"，且该假设从未变成真实消费方；删除测试显示没有任何生产复杂度需要迁移。

## 决策

删除 `core/views` 包及全部测试引用。不选择"归位到 `mc_onboard` / `mc_domain` 背后作为输出适配器"，原因：

1. 这会改变现有 MCP 工具的输出契约，违反"稳定入口"原则，且没有 Agent 侧需求证据。
2. onboarding / domain 面已有自己的输出结构，引入第二套视图表示只会增加面而无新增能力。

## 后果

- `tests/regression/test_v3_extended.py` 移除 `TestGraphViewBuilder` 类与 V3 pipeline 测试中的 view building 步骤。
- `tests/regression/test_h_i_series.py` 移除 H-06 change bundle 中仅测 GraphView 数据结构的类。
- `tests/domain/test_v3_ontology_mcp.py` 移除 `TestViewAsTool` 类。
- 未来若确实需要 persona 化图谱视图，应从 `mc_onboard` / `mc_domain` 的现有输出派生，或按新需求重新设计，不恢复本模块。
- 后续架构评审不应再把"为 GraphViewBuilder 找生产消费方"当作待办事项。
