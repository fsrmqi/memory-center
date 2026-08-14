"""Time-safe Git co-change calibration and evaluation."""
from __future__ import annotations

import hashlib
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

ALGORITHM_VERSION = "git_cochange_walk_forward_v3"


def evaluate_git_cochange(
    workspace_file: str | Path,
    *,
    max_commits: int = 20,
    max_files_per_commit: int = 20,
    prediction_limit: int = 8,
    warmup_commits: int = 5,
    apply: bool = False,
) -> dict[str, Any]:
    """Evaluate pair priors using only commits older than each test commit."""
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    commit_budget = min(max(1, int(max_commits)), 100)
    file_budget = min(max(2, int(max_files_per_commit)), 50)
    prediction_limit = min(max(1, int(prediction_limit)), 100)
    warmup = min(max(1, int(warmup_commits)), 50)
    observations: list[dict[str, Any]] = []
    environment_errors: list[dict[str, str]] = []
    pair_history: dict[str, dict[str, list[int]]] = defaultdict(dict)
    popularity: dict[str, int] = defaultdict(int)
    evaluated_commits = training_commits = sequence = 0

    with RuntimeStore(store.graph_db_path) as graph:
        remaining = commit_budget
        for service in config.services:
            if remaining <= 0:
                break
            repo = config.resolve_service_path(service)
            if not (repo / ".git").exists():
                continue
            try:
                commits = _read_commits(repo, remaining + warmup, file_budget)
            except (OSError, subprocess.SubprocessError) as exc:
                environment_errors.append({"service_ref": _stable_ref(service.name), "reason": type(exc).__name__})
                continue
            prefix = config.service_logical_prefix(service).strip("/")
            for index, (_commit_sha, relative_files) in enumerate(commits):
                logical_files = [f"{prefix}/{path}".strip("/") for path in relative_files]
                if len(logical_files) < 2:
                    continue
                if index >= warmup and remaining > 0:
                    for seed in logical_files[: min(5, len(logical_files))]:
                        truth = set(logical_files) - {seed}
                        predicted = set(_historical_predictions(pair_history, seed, prediction_limit))
                        baseline = set(_popularity_predictions(popularity, seed, prediction_limit))
                        current_graph = set(graph.file_neighbors(seed, limit=prediction_limit))
                        observations.append(
                            _observation(service.name, sequence, seed, truth, predicted, baseline, current_graph)
                        )
                    evaluated_commits += 1
                    remaining -= 1
                else:
                    training_commits += 1
                _update_history(pair_history, popularity, logical_files, sequence)
                sequence += 1
                if remaining <= 0:
                    break

        precisions = [float(row["precision"]) for row in observations]
        recalls = [float(row["recall"]) for row in observations]
        baseline_precisions = [float(row["baseline_precision"]) for row in observations]
        baseline_recalls = [float(row["baseline_recall"]) for row in observations]
        graph_precisions = [float(row["current_graph_precision"]) for row in observations]
        graph_recalls = [float(row["current_graph_recall"]) for row in observations]
        mean_precision = _mean(precisions)
        mean_recall = _mean(recalls)
        baseline_precision = _mean(baseline_precisions)
        baseline_recall = _mean(baseline_recalls)
        eligible = (
            evaluated_commits >= 5
            and len(observations) >= 20
            and mean_precision >= baseline_precision
            and mean_recall >= baseline_recall
        )
        applied_count = 0
        if apply and eligible:
            applied_count = graph.replace_cochange_priors(
                _hashed_priors(pair_history, limit=20_000),
                trained_at=datetime.now(timezone.utc).isoformat(),
            )

    generation = index_control_status(store)
    status = "ready" if observations else "environment_error" if environment_errors else "insufficient_data"
    return {
        "schema_version": 2,
        "benchmark": "git_cochange",
        "ground_truth_mode": "walk_forward_same_commit_seed_excluded",
        "temporal_integrity": "train_commits_strictly_precede_each_evaluation_commit",
        "current_graph_role": "diagnostic_only_not_used_for_calibration",
        "algorithm_version": ALGORITHM_VERSION,
        "status": status,
        "summary": {
            "case_count": len(observations),
            "evaluated_commit_count": evaluated_commits,
            "training_commit_count": training_commits,
            "mean_precision": mean_precision,
            "mean_recall": mean_recall,
            "baseline_mean_precision": baseline_precision,
            "baseline_mean_recall": baseline_recall,
            "current_graph_mean_precision": _mean(graph_precisions),
            "current_graph_mean_recall": _mean(graph_recalls),
            "environment_error_count": len(environment_errors),
        },
        "calibration": {
            "eligible": eligible,
            "applied": bool(apply and eligible),
            "applied_prior_count": applied_count,
            "reason": "walk_forward_not_better_than_past_only_popularity_or_insufficient_samples" if not eligible else "",
        },
        "scope": {
            "max_commits": commit_budget,
            "warmup_commits": warmup,
            "max_files_per_commit": file_budget,
            "prediction_limit": prediction_limit,
            "generation": str(generation.get("active_generation", "") or ""),
        },
        "cases": observations[:100],
        "environment_errors": environment_errors,
        "privacy": "Only hashes and aggregate counts are returned or persisted; paths, messages, repository names, and source are excluded.",
    }


def _observation(
    service: str,
    sequence: int,
    seed: str,
    truth: set[str],
    predicted: set[str],
    baseline: set[str],
    current_graph: set[str],
) -> dict[str, Any]:
    hits = truth & predicted
    baseline_hits = truth & baseline
    graph_hits = truth & current_graph
    return {
        "case_ref": _stable_ref(f"{service}:{sequence}:{seed}"),
        "truth_count": len(truth),
        "prediction_count": len(predicted),
        "hit_count": len(hits),
        "precision": len(hits) / len(predicted) if predicted else 0.0,
        "recall": len(hits) / len(truth) if truth else 1.0,
        "baseline_precision": len(baseline_hits) / len(baseline) if baseline else 0.0,
        "baseline_recall": len(baseline_hits) / len(truth) if truth else 1.0,
        "current_graph_precision": len(graph_hits) / len(current_graph) if current_graph else 0.0,
        "current_graph_recall": len(graph_hits) / len(truth) if truth else 1.0,
    }


def _update_history(
    history: dict[str, dict[str, list[int]]], popularity: dict[str, int], files: list[str], sequence: int
) -> None:
    unique = list(dict.fromkeys(files))
    for path in unique:
        popularity[path] = popularity.get(path, 0) + 1
        targets = history.setdefault(path, {})
        for candidate in unique:
            if candidate == path:
                continue
            state = targets.setdefault(candidate, [0, 0])
            state[0] += 1
            state[1] = sequence


def _historical_predictions(history: dict[str, dict[str, list[int]]], seed: str, limit: int) -> list[str]:
    return [
        path
        for path, _state in sorted(
            history.get(seed, {}).items(), key=lambda item: (-item[1][0], -item[1][1], item[0])
        )[:limit]
    ]


def _popularity_predictions(popularity: dict[str, int], seed: str, limit: int) -> list[str]:
    return [path for path, _count in sorted(popularity.items(), key=lambda item: (-item[1], item[0])) if path != seed][:limit]


def _hashed_priors(history: dict[str, dict[str, list[int]]], *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed, candidates in history.items():
        maximum = max((state[0] for state in candidates.values()), default=0)
        if maximum <= 0:
            continue
        for candidate, state in candidates.items():
            rows.append(
                {
                    "seed_ref": _path_ref(seed),
                    "candidate_ref": _path_ref(candidate),
                    "support": state[0],
                    "score": round(state[0] / maximum, 6),
                }
            )
    rows.sort(key=lambda row: (-int(row["support"]), str(row["seed_ref"]), str(row["candidate_ref"])))
    return rows[:limit]


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
    commits.reverse()
    return commits


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _path_ref(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:24]


def _stable_ref(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
