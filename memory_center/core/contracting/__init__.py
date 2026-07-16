"""Contract snapshot, runtime evidence, and compatibility governance."""

from .runtime import ingest_runtime_contract_samples, runtime_contract_compatibility, set_contract_migration
from .static import (
    CONTRACT_DIFF_FILE,
    CONTRACT_SNAPSHOT_FILE,
    build_contract_snapshot,
    contract_semantic_report,
    diff_contract_snapshots,
)

__all__ = [
    "CONTRACT_DIFF_FILE",
    "CONTRACT_SNAPSHOT_FILE",
    "build_contract_snapshot",
    "contract_semantic_report",
    "diff_contract_snapshots",
    "ingest_runtime_contract_samples",
    "runtime_contract_compatibility",
    "set_contract_migration",
]
