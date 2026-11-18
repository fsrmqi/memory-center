"""基础层的文本脱敏能力。

``safe_reason`` 原本位于 ``core.observability.diagnostics``，导致
``core.foundation.errors``（基础错误类型）反向依赖 ``core.observability``。
按 ``foundation/README.md`` 的职责定义，纯文本辅助属于基础层，因此真实实现落在
此处；``observability.diagnostics`` 保留同名再导出以兼容既有调用点。

边界：本模块只做纯字符串处理，不得引入工作区 I/O、配置加载或日志输出。
"""
from __future__ import annotations

import re

# Patterns that indicate sensitive content in error messages
_SENSITIVE_PATTERNS = [
    re.compile(r"/Users/\S+"),           # macOS home paths
    re.compile(r"/home/\S+"),            # Linux home paths
    re.compile(r"C:\\\\Users\\\\\S+"),   # Windows paths
    re.compile(r"[A-Z]:\\\\\S+"),        # Windows drive paths
    re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style keys
    re.compile(r"(?i)traceback \(most recent call last\)"),  # full tracebacks
]


def safe_reason(exc: Exception | None = None, reason: str | None = None) -> str:
    """Produce a safe reason string from an exception or literal.

    Strips:
    - Absolute file paths (macOS, Linux, Windows)
    - Secrets / tokens / API keys
    - Full tracebacks
    - Excessively long messages (>200 chars)

    Returns a short, safe reason string.
    """
    if exc is not None:
        raw = type(exc).__name__
    elif reason is not None:
        raw = reason
    else:
        return ""

    for pat in _SENSITIVE_PATTERNS:
        raw = pat.sub("[REDACTED]", raw)

    # Truncate long messages
    if len(raw) > 200:
        raw = raw[:197] + "..."

    return raw


__all__ = ["safe_reason"]
