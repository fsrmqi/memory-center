# Golden Benchmark Template

This folder contains:

- `workspace.yaml`: public demo workspace config
- `cases.yaml`: public demo golden suite
- `cases.template.yaml`: starting point for a private benchmark file

Use `cases.template.yaml` as the public starting point for a private benchmark file.

使用 `cases.template.yaml` 作为公开模板，再复制出你自己的私有 benchmark 文件。

Recommended flow / 推荐流程:

1. Copy the template outside the repo or into an ignored local path.
2. Replace `query`, `expected_anchors`, `expected_edges`, and `forbidden_anchors` with your real chain.
3. Run:

```bash
memory-center reindex --workspace examples/golden-benchmark/workspace.yaml
memory-center eval-golden \
  --workspace examples/golden-benchmark/workspace.yaml \
  --cases examples/golden-benchmark/cases.yaml
```

Or run a private workspace and private cases file directly:

```bash
memory-center eval-golden \
  --workspace /path/to/.memory-center/workspace.yaml \
  --cases /path/to/private-cases.yaml
```

Notes / 说明:

- Keep only logical identifiers in the cases file.
- Do not store absolute file paths, source snippets, secrets, or private business data.
- Real workspaces such as an existing monorepo `.memory-center/workspace.yaml` are supported directly.
