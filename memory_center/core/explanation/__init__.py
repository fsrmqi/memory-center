"""Explanation schema module (D-03)."""
from .schema import (
    Explanation,
    explanation_entry,
    merge_explanations,
    backward_compat_wrapper,
    display_rule_for_strength,
    DISPLAY_RULES,
)

__all__ = [
    "Explanation",
    "explanation_entry",
    "merge_explanations",
    "backward_compat_wrapper",
    "display_rule_for_strength",
    "DISPLAY_RULES",
]
