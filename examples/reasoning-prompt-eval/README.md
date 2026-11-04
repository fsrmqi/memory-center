# Reasoning Prompt Evaluation / 推理 Prompt 评测模板

本目录只提供可复制的公开模板，不代表真实任务已经验收。

1. 将 `cases.template.yaml` 复制到私有工作区外的本地评测目录。
2. 用真实但经过脱敏的任务摘要替换 `args`，并仅在确为真实任务时把 `real_case` 改为 `true`。
3. 在 MCP 宿主中实际调用对应 Prompt，人工检查结果后填写 `observations.template.yaml`。
4. 运行：

```bash
memory-center eval-reasoning-prompts \
  --cases /local/private/reasoning-cases.yaml \
  --observations /local/private/reasoning-observations.yaml
```

报告不会回显 Prompt 参数、reviewer 或 evidence refs，只返回逻辑 case ID、聚合检查和 Prompt 内容哈希。模板和静态 smoke 不能替代真实 case。

These public templates are not real acceptance evidence. The report never echoes prompt arguments, reviewer names, or evidence references.
