from __future__ import annotations

from memory_center.core.foundation.result_types import FacadeMetadata, attach_facade_metadata


def test_facade_metadata_has_stable_dict_contract() -> None:
    metadata = FacadeMetadata(
        operation="mc_lookup",
        result_kind="lookup",
        evidence_level="indexed",
        schema_version=1,
    )
    assert metadata.to_dict() == {
        "operation": "mc_lookup",
        "result_kind": "lookup",
        "evidence_level": "indexed",
        "schema_version": 1,
        "compatibility": "additive",
    }


def test_attach_facade_metadata_preserves_existing_payload() -> None:
    payload = {"results": [{"id": "one"}], "returned": 1}
    enriched = attach_facade_metadata(payload, operation="memory_query_hybrid", result_kind="lookup")
    assert enriched["results"] == payload["results"]
    assert enriched["returned"] == 1
    assert enriched["_meta"]["operation"] == "memory_query_hybrid"
    assert "_meta" not in payload
