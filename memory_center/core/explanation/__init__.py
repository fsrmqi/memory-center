"""Explanation schema module (D-03)."""
from .schema import (
    DISPLAY_RULES,
    Explanation,
    backward_compat_wrapper,
    display_rule_for_strength,
    explanation_entry,
    merge_explanations,
)

__all__ = [
    "Explanation",
    "explanation_entry",
    "merge_explanations",
    "backward_compat_wrapper",
    "display_rule_for_strength",
    "DISPLAY_RULES",
]
