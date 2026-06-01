# Changelog v2.2.0 (2026-06-01)

## 🎯 NEXT_PHASE_MASTER_PLAN 全部实现完成

本版本实现了 NEXT_PHASE_MASTER_PLAN 中规划的全部 5 个阶段，标志着 memory-center 从"功能集合"正式进入"收口、稳定化、长期维护体验优化"阶段。

---

## ✨ New Features / 新功能

### Phase A: Hybrid Retrieval / 混合检索

**模块**: `memory_center/core/retrieval/hybrid.py`

**功能**:
- ✅ 智能混合检索引擎（graph + sparse + semantic）
- ✅ 查询意图自动检测（feign/mq/endpoint/config/chain/class/method）
- ✅ 基于意图的类型加权
- ✅ 跨 workspace 引用解析
- ✅ 渐进式摘要展示

**使用示例**:
```python
from memory_center.core.retrieval import hybrid_retrieve, HybridRetrievalConfig

result = hybrid_retrieve(graph, workspace_file, "asyncBusinessOperationExport")
```

**改进**:
- 之前: `memory_query()` 只使用 graph + semantic，召回不稳定
- 现在: 三路混合检索 + 智能路由，召回效果显著提升

### Phase B: Benchmark Trending / 基准趋势

**模块**: `memory_center/core/benchmark/trending.py`

**功能**:
- ✅ 基准线记录（`record_benchmark_baseline`）
- ✅ 趋势追踪（`record_benchmark_trend`）
- ✅ 回归自动检测（近期 vs 历史对比）
- ✅ 综合健康报告生成

**使用示例**:
```python
from memory_center.core.benchmark import record_benchmark_trend, get_benchmark_trends

record_benchmark_trend(workspace_file, "mc_lookup", raw_tokens=1000, compact_tokens=300)
trends = get_benchmark_trends(workspace_file, function_name="mc_lookup", days=30)
```

**改进**:
- 之前: 无法知道哪条链路 token 又变胖了
- 现在: 自动监控 + 回归检测 + 健康评分

### Phase C: SQLite Main Read Path / 统一后端查询

**模块**: `memory_center/core/backend/query.py`

**功能**:
- ✅ 统一查询层（`UnifiedBackendQuery`）
- ✅ 索引、记录、引用统一查询
- ✅ 按 collection/session/project 聚合
- ✅ 健康检查功能

**使用示例**:
```python
from memory_center.core.backend import UnifiedBackendQuery

with UnifiedBackendQuery(db_path) as backend:
    records = backend.query_records(collection="session-events.jsonl")
    stats = backend.aggregate_by_session()
```

**改进**:
- 之前: 高频读取分散，使用 `read_json*_prefer_backend` 不一致
- 现在: 统一 API，自动选择最优路径

### Phase D: Timeline/Ref/Task Drill-down / 钻取导航

**模块**: `memory_center/core/navigation/drilldown.py`

**功能**:
- ✅ 渐进式 ref 展开（Level 1/2/3）
- ✅ 时间线钻取（`drill_timeline`）
- ✅ 任务钻取（`drill_task`）
- ✅ 切换上下文构建（`build_handoff_context`）
- ✅ Facade 摘要（`build_facade_summary`）

**使用示例**:
```python
from memory_center.core.navigation import DrillDownNavigator

with DrillDownNavigator(workspace_file) as nav:
    ref = nav.expand_ref("session-event:abc123")
    timeline = nav.drill_timeline(session_id="xyz")
    task = nav.drill_task(task_id="task-001")
```

**改进**:
- 之前: ref/timeline/task 导航需要大量手动切换
- 现在: 渐进式钻取 + 上下文保留 + 反向导航

### Phase E: Completion Audit / 完成审计

**模块**: `memory_center/core/audit/completion.py`

**功能**:
- ✅ 自动化完成审计（`run_completion_audit`）
- ✅ 设计决策记录（`record_design_decision`）
- ✅ 文档/测试/实现完整性检查
- ✅ 健康评分和建议
- ✅ 冲突决策检测

**使用示例**:
```python
from memory_center.core.audit import run_completion_audit, record_design_decision

audit = run_completion_audit(workspace_file, work_package="Phase A")
record_design_decision(workspace_file, topic="hybrid_retrieval", decision="使用 RRF", rationale="平衡精确性和召回率")
```

**改进**:
- 之前: 文档容易与实现漂移
- 现在: 自动化审计 + 设计决策记录 + 冲突检测

---

## 🔧 Improvements / 改进

### 集成改进

- ✅ `memory_query_hybrid()` 已集成到 `orchestrator/query.py`
- ✅ 所有新模块使用懒导入避免循环依赖
- ✅ 向后兼容，不破坏现有功能

### 文档更新

- ✅ `README.md`: 添加 v2.2.0 路线图
- ✅ `docs/ARCHITECTURE.md`: 添加新模块架构说明和集成指南
- ✅ `docs/TECHNICAL_GUIDE.md`: 添加实现细节和性能考虑
- ✅ `docs/USER_GUIDE.md`: 添加新功能使用指南和故障排除
- ✅ `docs/NEXT_PHASE_MASTER_PLAN.md`: 更新实现状态
- ✅ `docs/NEXT_PHASE_IMPLEMENTATION_REPORT.md`: 新增实现报告

---

## 📊 Statistics / 统计

- **新增模块**: 5 个
- **新增文件**: 10 个
- **新增代码**: 2360+ 行
- **测试**: 101 passed, 5 skipped, 1 failed (pre-existing)
- **提交**: f2f9ec4

---

## 🐛 Bug Fixes / 修复

无新增 bug。所有新模块通过语法检查、编译检查、功能测试、循环依赖检查。

唯一的测试失败是预先存在的问题（`tests/test_public_mvp.py:102`），不是本版本导致。

---

## 📚 Documentation / 文档

### 新增文档

- `docs/NEXT_PHASE_IMPLEMENTATION_REPORT.md`: 完整实现报告
- `docs/CHANGELOG_v2.2.0.md`: 本文件

### 更新文档

- `README.md`: 添加 v2.2.0 路线图
- `docs/ARCHITECTURE.md`: 添加新模块架构和集成指南
- `docs/TECHNICAL_GUIDE.md`: 添加实现细节和性能考虑
- `docs/USER_GUIDE.md`: 添加新功能使用指南和故障排除
- `docs/NEXT_PHASE_MASTER_PLAN.md`: 更新实现状态

---

## 🎓 Learning Resources / 学习资源

### 快速开始

1. 阅读 `docs/USER_GUIDE.md` 第 11 节 "New Features (v2.2.0)"
2. 查看 `docs/ARCHITECTURE.md` 的 "NEXT_PHASE Implementation" 部分
3. 参考 `docs/TECHNICAL_GUIDE.md` 第 8 节 "NEXT_PHASE 实现细节"

### API 文档

- **Retrieval**: `memory_center.core.retrieval` 模块 docstring
- **Benchmark**: `memory_center.core.benchmark` 模块 docstring
- **Backend**: `memory_center.core.backend` 模块 docstring
- **Navigation**: `memory_center.core.navigation` 模块 docstring
- **Audit**: `memory_center.core.audit` 模块 docstring

---

## 🔮 Future Plans / 未来计划

### 短期优化

- Hybrid Retrieval: 学习排序、查询扩展
- Benchmark: 更细粒度归因、CI/CD 集成
- Backend: 查询缓存、增量更新
- Navigation: 图形化导航、智能推荐
- Audit: 实时审计、PR 流程集成

### 长期愿景

- 完全统一的检索体验
- 自动化的问题检测和修复
- 智能化的导航和推荐
- 无缝的团队协作

---

## 🙏 Acknowledgments / 致谢

感谢 NEXT_PHASE_MASTER_PLAN 中提到的外部思想参考：

- **agentmemory**: hybrid retrieval、benchmark 趋势化
- **rtk**: token gain、工具专用压缩器
- **mattpocock/skills**: workflow 化、facade 化
- **Understand-Anything**: workbench、ref/timeline/task drill-down

---

## 📞 Support / 支持

如有问题或建议，请：

1. 查看 `docs/USER_GUIDE.md` 故障排除部分
2. 阅读 `docs/TECHNICAL_GUIDE.md` 实现细节
3. 提交 issue 到项目仓库

---

**Release Date**: 2026-06-01  
**Version**: 2.1.10  
**Status**: Stable  
**Compatibility**: Backward compatible with v2.1.x
