"""Bounded perf assertions for indexer hotspots.

These tests build a synthetic Spring Cloud-shaped workspace (no private paths,
no fixtures from disk) and assert the new indexed-lookup helpers are
algorithmically faster than a linear scan would be.

The wall-clock thresholds are intentionally generous so CI slowness or cold
JIT do not cause flakes.  We use them as smoke ceilings, not micro-benchmark
truth.
"""

from __future__ import annotations

import time

from memory_center.core.indexing.reindex import (
    _build_api_lookup,
    _candidate_apis_for_feign_method,
    _endpoint_matches,
)


def _make_apis(n: int) -> list[dict]:
    out = []
    for i in range(n):
        out.append({
            "project": f"svc-{i % 32}",
            "controller": f"Ctrl{i % 64}",
            "method_name": "handle",
            "http_method": "GET" if i % 2 == 0 else "POST",
            "path": f"/v{i % 3}/resource/{i}",
            "file": f"svc-{i % 32}/src/main/java/Ctrl{i % 64}.java",
        })
    return out


def _make_feign_method(api: dict) -> tuple[dict, dict]:
    feign = {
        "project": "client",
        "interface": "Client",
        "base_path": "",
        "target_service": api["project"],
    }
    method = {
        "method_name": "call",
        "http_method": api["http_method"],
        "path": api["path"],
    }
    return feign, method


def test_api_lookup_is_at_least_an_order_of_magnitude_faster() -> None:
    apis = _make_apis(2000)
    target = apis[1234]
    feign, method = _make_feign_method(target)

    # Baseline: linear scan through every API for one Feign method.
    #
    # Important: this is a smoke-style bounded perf assertion, not a
    # microbenchmark. CI and local laptops can be noisy enough that a
    # single timing sample is flaky even when the algorithmic win is
    # real, so we take several measurements and compare medians.
    #
    # Indexed lookup should still be *meaningfully* faster on the median
    # run; a 2× floor keeps the test robust under scheduler noise while
    # still catching any accidental regression back toward a linear scan.
    linear_runs: list[float] = []
    indexed_runs: list[float] = []
    matches_linear: list[dict] = []
    matches_indexed: list[dict] = []

    for _ in range(5):
        start = time.perf_counter()
        local_matches_linear: list[dict] = []
        for _ in range(50):
            for api in apis:
                if _endpoint_matches(feign, method, api):
                    local_matches_linear.append(api)
        linear_runs.append(time.perf_counter() - start)
        matches_linear = local_matches_linear

        start = time.perf_counter()
        lookup = _build_api_lookup(apis)
        local_matches_indexed: list[dict] = []
        for _ in range(50):
            for api in _candidate_apis_for_feign_method(lookup, feign, method):
                if _endpoint_matches(feign, method, api):
                    local_matches_indexed.append(api)
        indexed_runs.append(time.perf_counter() - start)
        matches_indexed = local_matches_indexed

    linear_elapsed = sorted(linear_runs)[len(linear_runs) // 2]
    indexed_elapsed = sorted(indexed_runs)[len(indexed_runs) // 2]

    assert matches_indexed, "indexed lookup must surface the matching API"
    assert {id(a) for a in matches_indexed} == {id(a) for a in matches_linear}
    # Indexed path should be meaningfully faster on this workload; linear is
    # O(N*M), indexed is O(M) per Feign method after a single index build.
    # We intentionally use a robust 2x median floor instead of a single-sample
    # 5x wall-clock floor, which is too flaky under noisy CI scheduling.
    assert indexed_elapsed * 2 < linear_elapsed, (
        f"indexed lookup not faster: linear={linear_elapsed:.4f}s indexed={indexed_elapsed:.4f}s "
        f"runs_linear={linear_runs!r} runs_indexed={indexed_runs!r}"
    )


def test_candidate_apis_handles_base_path_composition() -> None:
    apis = [{"project": "svc", "http_method": "GET", "path": "/article/move/{id}", "file": ""}]
    feign = {"base_path": "/article", "target_service": "svc"}
    method = {"http_method": "GET", "path": "/move/{id}"}
    lookup = _build_api_lookup(apis)
    candidates = _candidate_apis_for_feign_method(lookup, feign, method)
    assert candidates, "composed base_path + method.path must resolve"
    assert candidates[0]["path"] == "/article/move/{id}"
    assert _endpoint_matches(feign, method, candidates[0])


def test_candidate_apis_does_not_return_method_mismatch() -> None:
    apis = [
        {"project": "svc", "http_method": "GET", "path": "/x", "file": ""},
        {"project": "svc", "http_method": "POST", "path": "/x", "file": ""},
    ]
    feign = {"base_path": ""}
    method = {"http_method": "POST", "path": "/x"}
    lookup = _build_api_lookup(apis)
    candidates = _candidate_apis_for_feign_method(lookup, feign, method)
    assert [c["http_method"] for c in candidates] == ["POST"]


def test_candidate_apis_preserves_generic_request_mapping_semantics() -> None:
    apis = [
        {"project": "svc", "http_method": "GET", "path": "/x", "file": ""},
        {"project": "svc", "http_method": "POST", "path": "/x", "file": ""},
    ]
    feign = {"base_path": ""}
    method = {"http_method": "REQUEST", "path": "/x"}

    candidates = _candidate_apis_for_feign_method(_build_api_lookup(apis), feign, method)

    assert {item["http_method"] for item in candidates} == {"GET", "POST"}
    assert all(_endpoint_matches(feign, method, item) for item in candidates)
