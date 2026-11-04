# Security Policy

Memory Center is intended to run locally against source code workspaces.

## Supported versions

Current alpha versions receive best-effort security fixes.

## Reporting a vulnerability

Please open a private security advisory on GitHub if available. If not, open an issue with minimal reproduction details and avoid sharing secrets.

## Security expectations

- Do not commit `.memory-center/memory/` if it may contain private incident details.
- Do not commit generated indexes for proprietary projects unless your team allows it.
- Review agent instruction files before committing them.
- Treat MCP tools as local developer tools; do not expose the MCP server publicly without authentication and network controls.
