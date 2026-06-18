# Long-Term Architecture Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Complete the documented backend consistency, incremental indexing, facade typing, observability, benchmark baseline, and reasoning experience work without changing public MCP schemas.

**Architecture:** Add small deep Modules at existing seams: observable reads in `WorkspaceStore`, deletion-aware index reconciliation, typed result envelopes that remain dict-compatible at adapters, one metrics/structured-event interface, portable benchmark baselines, and a quality summary consumed by existing facade results. JSON/JSONL/source files remain facts of record and legacy return values remain available.

**Tech Stack:** Python 3.10+, SQLite, JSON/JSONL, pytest, existing Memory Center CLI/MCP/HTTP adapters.

---

### Task 1: Observable dual-read consistency

**Files:**
- Modify: `memory_center/core/store.py`
- Modify: `memory_center/core/memory_backend.py`
- Create: `tests/test_store_read_consistency.py`
- Modify: `docs/UNIFIED_BACKEND_READ_PATHS.md`

- [x] Write failing tests proving newer files beat stale mirrors, partial JSONL falls back, backend errors are visible, and legal empty mirrors are distinguishable.
- [x] Run `pytest -q tests/test_store_read_consistency.py` and confirm the observable read interface is missing.
- [x] Add `ReadResult(value, source, fallback_used, fallback_reason, consistency_status)` plus `read_json_observed` and `read_jsonl_observed`; keep legacy methods returning only `.value`.
- [x] Re-run the focused tests and confirm all dual-read cases pass.

### Task 2: Deletion- and move-aware incremental indexing

**Files:**
- Modify: `memory_center/core/indexer.py`
- Modify: `memory_center/core/incremental.py`
- Create: `tests/test_incremental_deletion_reconciliation.py`

- [x] Write a failing test that indexes a Java file, deletes or moves it, runs changed-path reindex, and verifies stale file/symbol/API rows and graph nodes disappear.
- [x] Run the focused test and confirm stale rows remain.
- [x] Reconcile scoped indexes against live paths and include deleted paths in partial graph cleanup.
- [x] Re-run focused incremental and indexer tests.

### Task 3: Typed facade result envelopes

**Files:**
- Create: `memory_center/core/result_types.py`
- Modify: `memory_center/core/orchestrator/query.py`
- Create: `tests/test_facade_result_types.py`

- [x] Write failing tests for stable typed lookup/walkthrough metadata and dict conversion.
- [x] Add frozen dataclasses for source diagnostics and facade metadata with `to_dict` helpers.
- [x] Attach typed metadata through additive `_meta` fields so existing response fields and MCP schemas remain compatible.
- [x] Re-run query, facade, MCP, and capability tests.

### Task 4: Unified observability

**Files:**
- Modify: `memory_center/core/metrics.py`
- Create: `memory_center/core/observability.py`
- Modify: `memory_center/core/indexer.py`
- Modify: `memory_center/core/orchestrator/query.py`
- Create: `tests/test_observability.py`

- [x] Write failing tests for structured operation events and latency/quality metrics.
- [x] Add an `OperationObserver` context manager that records duration, outcome, counts, and safe tags through `MetricsCollector` plus JSONL events.
- [x] Instrument reindex and hybrid query entrypoints without logging source content or secrets.
- [x] Re-run focused observability and behavior tests.

### Task 5: Portable benchmark baselines

**Files:**
- Create: `memory_center/core/benchmark/baseline.py`
- Modify: `memory_center/core/benchmark/__init__.py`
- Create: `tests/test_benchmark_baseline.py`
- Modify: `docs/TECHNICAL_GUIDE.md`

- [x] Write failing tests for recording anonymized baseline samples and comparing latency/quality regressions.
- [x] Store only operation, topology size, duration, result count, quality score, parser, and timestamp; reject paths and arbitrary payloads.
- [x] Add median/p95 comparison with configurable warning thresholds.
- [x] Re-run benchmark and privacy-focused tests.

### Task 6: Reasoning quality summary and documentation closure

**Files:**
- Create: `memory_center/core/quality.py`
- Modify: `memory_center/core/orchestrator/query.py`
- Modify: `memory_center/core/audit/completion.py`
- Modify: `memory_center/core/navigation/drilldown.py`
- Create: `tests/test_quality_summary.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/NEXT_PHASE_MASTER_PLAN.md`
- Modify: `docs/ROADMAP.md`

- [x] Write failing tests that classify evidence as fact/inferred/derived and expose freshness, confidence, and verification actions.
- [x] Add a shared quality summary used additively by query, audit, and drill-down results.
- [x] Keep existing fields unchanged and add only `_quality` metadata.
- [x] Update status documents to distinguish completed implementation from future operational validation.
- [x] Run `python3 -m compileall -q memory_center tests`, `git diff --check`, and `pytest -q`.

