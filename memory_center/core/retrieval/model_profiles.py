"""可审查的 embedding 模型档案，切换必须显式触发 reindex。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

MODEL_PROFILE_FILE = "retrieval-model-profile.json"
PROFILES = {
    "balanced": {"embedding_model": "sentence-transformers/all-MiniLM-L6-v2", "dimension": 384},
    "multilingual": {"embedding_model": "BAAI/bge-m3", "dimension": 1024},
}


def retrieval_model_profile(workspace_file: str | Path, profile: str = "", apply: bool = False) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    current = store.read_json_prefer_backend(MODEL_PROFILE_FILE, {})
    if not profile:
        return {"active": current, "available": PROFILES, "next_action": "select a profile and run a full reindex"}
    selected = PROFILES.get(profile.strip().lower())
    if not selected:
        return {"status": "invalid_profile", "available": sorted(PROFILES)}
    payload = {"schema_version": 1, "name": profile.strip().lower(), **selected}
    if apply:
        store.write_json(MODEL_PROFILE_FILE, payload)
    return {
        "status": "applied" if apply else "preview",
        "profile": payload,
        "requires_full_reindex": True,
        "next_action": "reindex with MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers",
    }
