# 编排

提供查询、影响分析、统一变更审查、会话、恢复、同步、写入、分组、评估和工作区操作的任务级组合。

面向工作区的门面放在 `workspace_ops.py`，内部编排基础能力放在 `shared.py`。`change_review.py` 负责组合变更检测、定向刷新、加权影响、风险与验证 Action；不得在此加入持久化引擎。`templates.py` 提供有界图查询模板（`find_symbols` / `trace_call_paths` / `find_contract_consumers`），统一 fast/standard/deep 三档硬预算与 generation 键控缓存；它组合的是任务级查询用例，因此归属本层而不是检索引擎层（ADR-0002 §4.4）。
