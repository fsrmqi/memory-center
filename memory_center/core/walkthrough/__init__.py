"""Method walkthrough support modules.

The submodules here own pure helpers used by ``orchestrator/query.py`` to build
a method-level walkthrough.  ``orchestrator/query.py`` remains the compatibility
facade; this package is intentionally split so each helper can be unit-tested
without going through the orchestrator.
"""

from . import answer, continuations, escalation, risks, symbols
from .cache import WalkthroughCache
from .evaluation import evaluate_walkthrough_result
from .report import render_walkthrough_markdown, slugify_walkthrough_symbol

__all__ = [
    "WalkthroughCache",
    "evaluate_walkthrough_result",
    "render_walkthrough_markdown",
    "slugify_walkthrough_symbol",
    "answer",
    "continuations",
    "escalation",
    "risks",
    "symbols",
]
