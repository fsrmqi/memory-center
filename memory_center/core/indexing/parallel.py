"""Parallel indexing — ThreadPoolExecutor-based parallel file parser.

Replaces the 2.x single-threaded os.walk + parse loop with parallel
file parsing for 3-5x speedup on multi-core machines.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .base import JavaParseResult


def walk_project_files(
    root: Path,
    extensions: tuple[str, ...] = (".java",),
    config_names: tuple[str, ...] = ("application.yml", "application.yaml", "application.properties", "bootstrap.yml", "bootstrap.yaml"),
) -> tuple[list[Path], list[Path]]:
    """Walk a project directory and collect Java and config files."""
    java_files: list[Path] = []
    config_files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip common non-source directories
        dirnames[:] = [
            d for d in dirnames
            if d not in {".git", "target", "build", "node_modules", "__pycache__", ".idea", ".vscode"}
        ]

        for filename in filenames:
            filepath = Path(dirpath) / filename
            if filepath.suffix in extensions:
                java_files.append(filepath)
            elif filename in config_names:
                config_files.append(filepath)

    return java_files, config_files


def parse_files_parallel(
    files: list[tuple[str, Path]],
    parse_fn: Callable[[str, str], JavaParseResult],
    max_workers: int | None = None,
) -> list[tuple[str, Path, JavaParseResult | None]]:
    """Parse multiple files in parallel using a thread pool.

    Args:
        files: List of (service_name, file_path) tuples
        parse_fn: Function that takes (text, file_path) and returns JavaParseResult
        max_workers: Maximum number of threads. When ``None`` the value is
            chosen via :func:`estimate_optimal_workers` based on file count
            and CPU. Pass an integer to override (mostly useful in tests).

    Returns:
        List of (service_name, file_path, parse_result) tuples
    """
    results: list[tuple[str, Path, JavaParseResult | None]] = []
    workers = max_workers if max_workers is not None else estimate_optimal_workers(len(files))
    if workers <= 1 or len(files) <= 1:
        # No point spinning up a pool for a single file; the overhead
        # outweighs any speedup.
        for svc, path in files:
            results.append(_parse_one(svc, path, parse_fn))
        return results

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_parse_one, svc, path, parse_fn): (svc, path)
            for svc, path in files
        }
        for future in as_completed(futures):
            results.append(future.result())

    return results


def _parse_one(
    service: str,
    path: Path,
    parse_fn: Callable[[str, str], JavaParseResult],
) -> tuple[str, Path, JavaParseResult | None]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        result = parse_fn(text, str(path))
        return (service, path, result)
    except Exception:
        return (service, path, None)


def estimate_optimal_workers(file_count: int, max_workers: int = 32) -> int:
    """Pick a thread count for parsing ``file_count`` files.

    Parsing is mostly IO-bound (read source from disk) with a short CPU
    burst per file (tree-sitter walk). For an IO-bound workload the rule
    of thumb is ``2 × cpu_count`` capped at a reasonable ceiling — 32 is
    enough to saturate macOS / Linux file IO on a modern laptop without
    drowning the disk in head-of-line blocking. The previous default of
    8 was chosen for 2.x's CPU-bound regex parser and is too conservative
    for tree-sitter + LZ4 reads.

    Small batches still run sequentially: thread pool overhead dominates
    when there's fewer than a handful of files.
    """
    if file_count <= 4:
        return 1
    cpu_count = os.cpu_count() or 4
    optimal = min(cpu_count * 2, max_workers, file_count)
    return max(2, optimal)
