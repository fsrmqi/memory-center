# Contributing

Thanks for your interest in Memory Center.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[mcp,dev]
pytest
ruff check .
```

## Contribution areas

Good first areas:

- improve Spring annotation extraction
- add Maven/Gradle dependency indexing
- add Nacos config readers
- improve rule matching
- add examples for real-world Spring Cloud patterns
- improve docs for Codex, Claude Code, Cursor and Copilot integration

## Pull request checklist

Before opening a PR:

- add or update tests
- run `pytest`
- run `ruff check .`
- update docs if behavior changes
- keep public APIs stable or document breaking changes

## Design principles

1. The MCP server must never invent project facts.
2. Rule checks should be explainable.
3. Local workspace data should be transparent files, not opaque hidden state.
4. Public components should avoid vendor lock-in.
5. Spring Cloud conventions should work out of the box, but extension points should be generic.
