"""P0 真实场景 benchmark.

衡量 P0(service kind registry / SQLite PRAGMA + executemany /
多语言 parser registry)在真实工作区上的 reindex 收益。

用法:
    .venv/bin/python scripts/bench_p0_real.py \\
        --workspace /path/to/workspace/.memory-center/workspace.yaml \\
        --runs 1

输出:
- 单次 reindex wall-clock
- SQLite PRAGMA 实测值(WAL / cache / temp_store / mmap)
- graph 节点/边总数
- multilang 节点统计(Module/Class/Function + DEFINES/IMPORTS/CALLS)
- 单次 reindex 前后 db 文件大小

脚本本身不切 git 分支;切分支由调用方控制(例如在独立 worktree / clone 里跑)。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n //= 1024 if unit == "B" else 1024
    return f"{n}TB"


def _pragma_snapshot(db_path: Path) -> dict[str, Any]:
    """读 db 的实际 PRAGMA 状态。

    PRAGMA 是 per-connection 的设置(WAL 例外,它写在 db header);裸 sqlite3
    打开只能拿到 SQLite 默认值。要看 memory-center 实际配置生效,必须通过
    GraphStore 拿连接。
    """
    if not db_path.exists():
        return {"missing": True}
    try:
        from memory_center.core.graph import GraphStore  # noqa: PLC0415

        from memory_center.core.storage.pragmas import read_pragma_state  # noqa: PLC0415
    except ImportError:
        # baseline 分支可能还没有 pragmas 模块;退回到裸读 + 标记。
        conn = sqlite3.connect(str(db_path))
        try:
            out: dict[str, Any] = {"_note": "pragmas module not present; raw conn shows defaults only"}
            for key in ("journal_mode", "synchronous", "cache_size", "temp_store", "mmap_size"):
                row = conn.execute(f"PRAGMA {key}").fetchone()
                out[key] = row[0] if row else None
            return out
        finally:
            conn.close()
    with GraphStore(db_path) as graph:
        return dict(read_pragma_state(graph.connect()))


def _graph_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    try:
        out: dict[str, int] = {}
        out["nodes"] = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        out["edges"] = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        rows = conn.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall()
        out["nodes_by_type"] = dict(rows)
        rows = conn.execute("SELECT type, COUNT(*) FROM edges GROUP BY type").fetchall()
        out["edges_by_type"] = dict(rows)
        return out
    finally:
        conn.close()


def _run_reindex(workspace_file: Path) -> tuple[float, dict[str, Any]]:
    """跑一次 reindex_workspace,返回 (耗时秒, result dict)。"""
    # Import 放在函数内,确保 git checkout 后能拿到最新代码。
    from memory_center.core.config import load_workspace_config
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.store import WorkspaceStore

    config = load_workspace_config(str(workspace_file))
    store = WorkspaceStore(workspace_file)
    t0 = time.perf_counter()
    result = reindex_workspace(config, store)
    elapsed = time.perf_counter() - t0
    return elapsed, result


def _cleanup_index(workspace_file: Path) -> None:
    """清掉旧索引,保证 reindex 是冷启动。"""
    ctx_dir = workspace_file.parent
    for sub in ("index", "graph", "semantic", "evaluation"):
        p = ctx_dir / sub
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def _workspace_from_env() -> Path | None:
    """工作区路径只从环境变量取，脚本不内置私有默认值。"""
    raw = os.environ.get("MEMORY_CENTER_REAL_WORKSPACE", "").strip()
    return Path(raw) if raw else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="P0 reindex benchmark on a real workspace.",
        epilog="工作区路径必须显式提供（--workspace 或 MEMORY_CENTER_REAL_WORKSPACE），"
               "脚本不内置任何私有路径，例如 /path/to/workspace/.memory-center/workspace.yaml。",
    )
    parser.add_argument("--workspace", type=Path, help="workspace.yaml 路径（默认取 MEMORY_CENTER_REAL_WORKSPACE）")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("/tmp/mc-p0-bench.json"))
    parser.add_argument("--label", default="HEAD", help="给本次跑加一个标签,例如 baseline / after-p0")
    args = parser.parse_args()

    workspace_arg = args.workspace or _workspace_from_env()
    if workspace_arg is None:
        parser.error(
            "必须提供工作区：--workspace /path/to/workspace/.memory-center/workspace.yaml "
            "或环境变量 MEMORY_CENTER_REAL_WORKSPACE=/path/to/workspace/.memory-center/workspace.yaml"
        )
    workspace_file = workspace_arg.expanduser().resolve()
    assert workspace_file.exists(), workspace_file
    ctx_dir = workspace_file.parent

    print(f"== bench label={args.label} workspace={workspace_file}")

    samples: list[dict[str, Any]] = []
    for i in range(args.runs):
        print(f"-- run {i + 1}/{args.runs}: clearing index...")
        _cleanup_index(workspace_file)
        print(f"-- run {i + 1}/{args.runs}: reindex...")
        elapsed, result = _run_reindex(workspace_file)
        graph_db = ctx_dir / "graph" / "graph.db"
        snap = {
            "run": i + 1,
            "elapsed_s": round(elapsed, 3),
            "graph_db_bytes": graph_db.stat().st_size if graph_db.exists() else 0,
            "graph_db_human": _human_bytes(graph_db.stat().st_size) if graph_db.exists() else "0",
            "pragmas": _pragma_snapshot(graph_db),
            "graph": _graph_counts(graph_db),
        }
        samples.append(snap)
        print(json.dumps(snap, ensure_ascii=False, indent=2))

    summary = {
        "label": args.label,
        "workspace": str(workspace_file),
        "samples": samples,
    }
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
