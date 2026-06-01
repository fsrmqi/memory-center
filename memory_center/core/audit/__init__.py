"""Audit — completion tracking and documentation alignment."""
from .completion import (
    AUDIT_LOG_FILE,
    DESIGN_DECISIONS_FILE,
    generate_audit_report,
    get_design_decisions,
    record_design_decision,
    run_completion_audit,
)

__all__ = [
    "AUDIT_LOG_FILE",
    "DESIGN_DECISIONS_FILE",
    "generate_audit_report",
    "get_design_decisions",
    "record_design_decision",
    "run_completion_audit",
]
