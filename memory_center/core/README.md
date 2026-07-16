# Core Architecture

`core/` is the domain boundary of Memory Center. The root contains no implementation: choose a child package by responsibility.

- `foundation/` and `storage/` are lower layers and must not import orchestration or adapters.
- Domain packages expose facts or bounded operations; `orchestrator/` composes them.
- CLI, MCP, HTTP, and hooks live outside this directory and call canonical package paths only.
