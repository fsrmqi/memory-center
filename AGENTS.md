# Memory Center Agent Instructions / 记忆中心 Agent 指令

## 中文

本仓库实现 **Memory Center（记忆中心）**：面向 AI 编程助手的 MCP 项目记忆服务，用于多 Agent 公共空间、项目上下文、跨服务影响分析和经验沉淀。

修改代码前必须遵守：

1. 优先阅读 `README.md`、`docs/ARCHITECTURE.md`、`docs/MCP_GUIDE.md`。
2. 变更 MCP tool schema 时必须保持兼容，若不兼容必须在 README、CHANGELOG、docs 中明确说明。
3. 修改 Spring Cloud 索引器、规则匹配、CLI、MCP Server 时必须补充或更新测试。
4. 所有面向用户的说明尽量保持中英文双语。
5. 不要提交真实私有项目生成的 `.memory-center/index` 或 `.memory-center/memory` 内容。
6. 不要把私有路径、公司内部服务名、真实密钥写进示例。

## English

This repository implements **Memory Center**, an MCP-native project memory service and shared context center for AI coding agents.

Before making broad changes:

1. Read `README.md`, `docs/ARCHITECTURE.md`, and `docs/MCP_GUIDE.md`.
2. Keep MCP tool schemas backward-compatible unless a breaking change is explicitly documented.
3. Add or update tests when changing the Spring Cloud indexer, rule matching, CLI, or MCP server.
4. Keep public-facing documentation bilingual when possible.
5. Do not commit generated `.memory-center/index` or `.memory-center/memory` content from private workspaces.
6. Do not include private paths, internal service names, or secrets in examples.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **memory-center** (11099 symbols, 26098 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/memory-center/context` | Codebase overview, check index freshness |
| `gitnexus://repo/memory-center/clusters` | All functional areas |
| `gitnexus://repo/memory-center/processes` | All execution flows |
| `gitnexus://repo/memory-center/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
