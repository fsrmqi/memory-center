# Session Recall Evaluation / 会话召回评测

复制 `cases.template.yaml` 到工作区外的私有目录，填入脱敏真实 case：

```bash
memory-center eval-session-recall \
  --workspace /path/to/.memory-center/workspace.yaml \
  --cases /private/session-recall-cases.yaml
```

评测通过实际 `workspace_resume_context` 读取 L1 case，并区分：

- `hit`：预期 source session 的 case 已被 resume 返回；
- `case_not_indexed`：L1 中不存在预期 source session；
- `retrieval_miss`：L1 存在，但 query token 未命中该 case；
- `ranking_miss`：token 已命中，但被 resume 的结果窗口截断；
- `evidence_insufficient`：case 缺少 query 或 expected source session。

报告只返回 query 与 session ID 的 SHA-256 短哈希，并聚合 `related_case_match_modes`（`exact|cjk_bigram|none`），用于区分精确命中与中文 fallback。真实 query、任务名、路径、session ID 和 case 正文不得提交。

如需审查 fallback 是否返回过多候选，为 case 添加 `allowed_source_session_ids`。报告会返回 `precision_review` 和 `unexpected_source_session_sha256`；`unexpected` 仅表示需要人工审核，绝不自动标为误报。
