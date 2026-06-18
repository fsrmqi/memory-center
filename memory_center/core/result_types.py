from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class FacadeMetadata:
    operation: str
    result_kind: str
    evidence_level: str = "unknown"
    schema_version: int = 1
    compatibility: str = "additive"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def attach_facade_metadata(
    payload: Dict[str, Any],
    *,
    operation: str,
    result_kind: str,
    evidence_level: str = "unknown",
    schema_version: int = 1,
) -> Dict[str, Any]:
    enriched = dict(payload)
    enriched["_meta"] = FacadeMetadata(
        operation=operation,
        result_kind=result_kind,
        evidence_level=evidence_level,
        schema_version=schema_version,
    ).to_dict()
    return enriched
