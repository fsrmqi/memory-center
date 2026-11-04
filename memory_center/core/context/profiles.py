"""面向宿主模型的上下文条目预算策略。"""
from __future__ import annotations

MODEL_BUDGET_PROFILES: dict[str, dict[str, int]] = {
    "codex": {"services": 3, "files": 4, "refs": 4, "steps": 3, "tasks": 3, "events": 3, "findings": 3},
    "claude-code": {"services": 5, "files": 5, "refs": 5, "steps": 4, "tasks": 5, "events": 4, "findings": 4},
    "gemini": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "deepseek": {"services": 3, "files": 3, "refs": 3, "steps": 2, "tasks": 3, "events": 2, "findings": 2},
    "cursor-agent": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "glm": {"services": 3, "files": 3, "refs": 3, "steps": 2, "tasks": 3, "events": 2, "findings": 2},
    "qwen": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "generic-mcp-agent": {"services": 5, "files": 5, "refs": 5, "steps": 4, "tasks": 5, "events": 4, "findings": 4},
}


def normalize_model_name(model_name: str) -> str:
    raw = (model_name or "").strip().lower()
    aliases = {"openai-codex": "codex", "claude": "claude-code", "claudecode": "claude-code", "cursor": "cursor-agent", "cursorai": "cursor-agent"}
    raw = aliases.get(raw, raw)
    if raw.startswith("gemini"):
        return "gemini"
    if raw.startswith("deepseek"):
        return "deepseek"
    if raw.startswith(("glm", "chatglm")):
        return "glm"
    if raw.startswith("qwen"):
        return "qwen"
    return raw if raw in MODEL_BUDGET_PROFILES else "generic-mcp-agent"


def budget_limits(budget: str, model: str = "") -> dict[str, int]:
    level = (budget or "medium").strip().lower()
    level = level if level in {"tiny", "small", "medium", "large"} else "medium"
    profile = MODEL_BUDGET_PROFILES[normalize_model_name(model)]
    if level == "tiny":
        return {key: 1 for key in profile}
    if level == "small":
        return {key: max(1, value // 2) for key, value in profile.items()}
    if level == "large":
        return dict(profile)
    return {key: max(2, int(value * 0.7)) for key, value in profile.items()}
