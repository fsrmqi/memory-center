"""Independent-ish Git co-change evaluation for graph impact predictions."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

ALGORITHM_VERSION = "git_cochange_weighted_file_neighbors_v2"


def evaluate_git_cochange(
    workspace_file: str | Path,
    *,
    max_commits: int = 20,
    max_files_per_commit: int = 20,
    prediction_limit: int = 8,
) -> dict[str, Any]:
    """Measure graph file-neighbor predictions against actual same-commit files.

    This is not perfect causal ground truth, but unlike graph-derived labels it
    is independent of the graph traversal being evaluated.
    """
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    commit_budget = min(max(1, int(max_commits)), 100)
    file_budget = min(max(2, int(max_files_per_commit)), 50)
    prediction_limit = min(max(1, int(prediction_limit)), 100)
    observations: list[dict[str, Any]] = []
    environment_errors: list[dict[str, str]] = []

    with RuntimeStore(store.graph_db_path) as graph:
        remaining = commit_budget
        for service in config.services:
            if remaining <= 0:
                break
            repo = config.resolve_service_path(service)
            if not (repo / ".git").exists():
                continue
            try:
                commits = _read_commits(repo, min(remaining, commit_budget), file_budget)
            except (OSError, subprocess.SubprocessError) as exc:
                environment_errors.append(
                    {
                        "service_ref": _stable_ref(service.name),
                        "reason": type(exc).__name__,
                    }
                )
                continue
            prefix = config.service_logical_prefix(service).strip("/")
            for commit_sha, relative_files in commits:
                logical_files = [f"{prefix}/{path}".strip("/") for path in relative_files]
                if len(logical_files) < 2:
                    continue
                for seed in logical_files[: min(5, len(logical_files))]:
                    truth = set(logical_files) - {seed}
                    predicted = set(graph.file_neighbors(seed, limit=prediction_limit))
                    hits = truth & predicted
                    observations.append(
                        {
                            "case_ref": _stable_ref(f"{service.name}:{commit_sha}:{seed}"),
                            "truth_count": len(truth),
                            "prediction_count": len(predicted),
                            "hit_count": len(hits),
                            "precision": len(hits) / len(predicted) if predicted else 0.0,
                            "recall": len(hits) / len(truth) if truth else 1.0,
                        }
                    )
                remaining -= 1
                if remaining <= 0:
                    break

    precisions = [float(row["precision"]) for row in observations]
    recalls = [float(row["recall"]) for row in observations]
    generation = index_control_status(store)
    status = "ready" if observations else "environment_error" if environment_errors else "insufficient_data"
    return {
        "schema_version": 1,
        "benchmark": "git_cochange",
        "ground_truth_mode": "co_change_same_commit_seed_excluded",
        "independence": "independent_of_graph_edges_but_not_causal_ground_truth",
        "algorithm_version": ALGORITHM_VERSION,
        "status": status,
        "summary": {
            "case_count": len(observations),
            "mean_precision": round(sum(precisions) / len(precisions), 4) if precisions else 0.0,
            "mean_recall": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
            "environment_error_count": len(environment_errors),
        },
        "scope": {
            "max_commits": commit_budget,
            "max_files_per_commit": file_budget,
            "prediction_limit": prediction_limit,
            "generation": str(generation.get("active_generation", "") or ""),
        },
        "cases": observations[:100],
        "environment_errors": environment_errors,
        "privacy": "No source, commit messages, absolute paths, or repository names are persisted or returned.",
    }


def _read_commits(repo: Path, limit: int, max_files: int) -> list[tuple[str, list[str]]]:
    output = subprocess.check_output(
        ["git", "log", "--no-merges", f"-n{limit * 3}", "--format=%x1e%H", "--name-only"],
        cwd=repo,
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    commits: list[tuple[str, list[str]]] = []
    for block in output.split("\x1e"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        sha, files = lines[0], list(dict.fromkeys(lines[1:]))[:max_files]
        if len(files) >= 2:
            commits.append((sha, files))
        if len(commits) >= limit:
            break
    return commits


def _stable_ref(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
