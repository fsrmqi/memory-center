from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore


def generate_skills(workspace_file: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Generate bounded Agent Skill drafts from historical task memory."""

    store = WorkspaceStore(workspace_file)
    out = Path(output_dir) if output_dir else store.base_dir / "skills" / "generated"
    out.mkdir(parents=True, exist_ok=True)
    cases = store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=1000)
    if not cases:
        cases = [{
            "task": "Spring Cloud safe change",
            "projects": [],
            "files": [],
            "flow": "Controller/Consumer → Service → Feign/MQ/Data",
            "risk_points": ["contract compatibility", "idempotency", "observability"],
        }]
    files = []
    manifest = {}
    for i, case in enumerate(cases[-20:], start=1):
        slug = _slug(case.get("task", f"case-{i}"))[:60] or f"case-{i}"
        path = out / slug / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_skill_page(case), encoding="utf-8")
        files.append(str(path.relative_to(out)))
        manifest[slug] = {
            "case_index": len(cases) - 20 + i - 1,
            "task": case.get("task", ""),
            "path": str(path.relative_to(out)),
        }
    manifest_path = out / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "generated": True,
        "output_dir": str(out),
        "files": files,
        "manifest": str(manifest_path.relative_to(out)),
    }


def _skill_page(case: dict[str, Any]) -> str:
    task = case.get("task", "Spring Cloud task")
    flow = case.get("flow", "")
    files = case.get("files", [])
    risk_points = case.get("risk_points", [])
    projects = case.get("projects", [])
    prompt_template = f"""You are working on a task similar to: {task}

Before making changes:
1. Read these files: {', '.join(f'`{f}`' for f in files) if files else '(none specified)'}
2. Follow this flow: {flow}
3. Watch for these risks: {', '.join(risk_points) if risk_points else '(none specified)'}

After changes:
- Run: memory-center eval-write-quality --workspace <ws> --task-id <tid>
- Verify: memory-center eval-regression-suite --workspace <ws>"""
    trigger = f"Task involves: {', '.join(projects) if projects else '(any project)'}"
    if flow:
        trigger += f" | Flow: {flow}"
    files_section = "\n".join(f"- `{f}`" for f in files)
    risks_section = "\n".join(f"- {r}" for r in risk_points)
    return (
        f"# Skill: {task}\n\n"
        f"## When to use / 适用场景\n\n"
        f"Use this skill when the task resembles this historical case.\n\n"
        f"当新任务与该历史案例类似时，优先读取本 Skill。\n\n"
        f"## Trigger / 触发条件\n\n{trigger}\n\n"
        f"## Flow / 流程\n\n{flow}\n\n"
        f"## Important files / 关键文件\n\n{files_section}\n\n"
        f"## Risk checklist / 风险检查\n\n{risks_section}\n\n"
        f"## Prompt Template / 提示模板\n\n```markdown\n{prompt_template}\n```\n"
    )


def _slug(text: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())
