from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from filelock import FileLock


class WorkspaceStore:
    def __init__(self, workspace_file: str | Path):
        self.workspace_file = Path(workspace_file).expanduser().resolve()
        self.base_dir = self.workspace_file.parent
        self.index_dir = self.base_dir / "index"
        self.rules_dir = self.base_dir / "rules"
        self.memory_dir = self.base_dir / "memory"
        self.instructions_dir = self.base_dir / "instructions"
        self.graph_dir = self.base_dir / "graph"
        self.lock_file = self.base_dir / "store.lock"
        for p in [self.index_dir, self.rules_dir, self.memory_dir, self.instructions_dir, self.graph_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, data: Any) -> None:
        path = self.index_dir / name
        with FileLock(str(self.lock_file)):
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_json(self, name: str, default: Any) -> Any:
        path = self.index_dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def append_jsonl(self, name: str, item: Dict[str, Any]) -> None:
        path = self.memory_dir / name
        item = dict(item)
        item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        with FileLock(str(self.lock_file)):
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def read_jsonl(self, name: str, limit: int = 50) -> List[Dict[str, Any]]:
        path = self.memory_dir / name
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows

    @property
    def graph_db_path(self) -> Path:
        return self.graph_dir / "graph.db"
