"""P0 index hot path regression tests.

These tests lock in the P0-0 contract documented in
``docs/benchmarks/P0_INDEX_HOT_PATH_DESIGN.md``:

1. ``JavaSymbol.to_dict()`` must match ``dataclasses.asdict`` byte-for-byte
   (key set, key order, value equality), and ``core.models.to_dict`` must
   prefer the object's own ``to_dict`` when present.
2. ``storage.metadata.metadata_json`` must be byte-equivalent to
   ``json.dumps(meta or {}, ensure_ascii=False)`` for both empty and
   non-empty payloads; the empty-dict path must skip the encoder.
3. ``TreeSitterJavaParser`` with supplements-only hot path must produce the
   same ``JavaParseResult`` as the legacy "always full regex + merge"
   behaviour for representative Spring controller / Feign / Kafka files,
   including every file shipped under ``examples/spring-cloud-demo``.
4. The ``MEMORY_CENTER_PARSER_FULL_DUAL=1`` escape hatch must restore the
   legacy behaviour deterministically.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from unittest import mock

import pytest

from memory_center.core.indexing.tree_sitter_parser import (
    _HAS_TREE_SITTER,
    TreeSitterJavaParser,
)
from memory_center.core.models import JavaSymbol
from memory_center.core.models import to_dict as models_to_dict
from memory_center.core.storage.metadata import metadata_json


def _make_symbol() -> JavaSymbol:
    return JavaSymbol(
        project="p",
        file="f.java",
        parser="tree-sitter",
        package="com.example",
        classes=["A", "B"],
        interfaces=["I"],
        methods=["m"],
        method_signatures=[{"identity": "m()", "name": "m", "parameter_types": [], "line": 1}],
        fields=["x"],
        class_lines={"A": 1, "B": 10},
        interface_lines={"I": 4},
        method_lines={"m": 12},
        field_lines={"x": 8},
        annotations=["RestController"],
        imports=["java.util.List"],
        field_types={"x": "String"},
        constants={"K": "v"},
        method_variable_types={"m": {"local": "String"}},
        bean_injections=[{"field_name": "svc", "type": "Svc"}],
        method_calls=[{"callee": "Svc.do", "line": 5}],
        dto_field_usages=[{"dto": "Req", "field": "id"}],
        config_usages=[{"key": "foo.bar"}],
        data_resources=[{"kind": "mongo", "name": "users"}],
    )


class TestJavaSymbolToDict:
    def test_matches_asdict_key_set_and_order(self) -> None:
        sym = _make_symbol()
        expected = asdict(sym)
        actual = sym.to_dict()
        assert list(actual.keys()) == list(expected.keys())
        assert actual == expected

    def test_models_to_dict_prefers_own_method(self) -> None:
        sym = _make_symbol()
        with mock.patch.object(JavaSymbol, "to_dict", wraps=sym.to_dict) as spy:
            payload = models_to_dict(sym)
        spy.assert_called_once()
        assert payload["project"] == "p"

    def test_returned_collections_are_shallow_copies(self) -> None:
        sym = _make_symbol()
        payload = sym.to_dict()
        payload["classes"].append("Z")
        payload["class_lines"]["Z"] = 99
        payload["method_variable_types"]["m"]["local"] = "Integer"
        # Top-level list/dict fields must be isolated copies.
        assert "Z" not in sym.classes
        assert "Z" not in sym.class_lines
        # Nested dict-of-dict is also defensively copied at both levels.
        assert sym.method_variable_types["m"]["local"] == "String"


class TestMetadataJson:
    @pytest.mark.parametrize(
        "meta",
        [None, {}, {"a": 1}, {"中文": "值"}, {"nested": {"x": [1, 2, 3]}}],
    )
    def test_matches_json_dumps(self, meta) -> None:
        expected = json.dumps(meta or {}, ensure_ascii=False)
        assert metadata_json(meta) == expected

    def test_empty_fast_path_is_literal(self) -> None:
        assert metadata_json(None) == "{}"
        assert metadata_json({}) == "{}"

    def test_empty_fast_path_skips_json_encoder(self) -> None:
        with mock.patch("memory_center.core.storage.metadata.json.dumps") as dumps:
            metadata_json({})
            metadata_json(None)
        dumps.assert_not_called()


_SAMPLES = {
    "controller.java": """
package com.acme.demo;
import java.util.List;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
@RestController
public class FooController {
    private static final String K = "v";
    @Autowired private BarService barService;
    @Value("${foo.bar}") private String fooBar;
    @GetMapping("/foo") public List<String> foo() { return barService.list(); }
}
interface BarService { java.util.List<String> list(); }
""",
    "feign.java": """
package com.acme.demo;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
@FeignClient(name = "user-svc")
public interface UserClient {
    @GetMapping("/v1/users/{id}")
    UserDTO get(String id);
}
record UserDTO(String id, String name) {}
""",
    "kafka.java": """
package com.acme.demo;
import org.springframework.kafka.annotation.KafkaListener;
public class OrderConsumer {
    @KafkaListener(topics = "${kafka.topic.order}")
    public void onMessage(String payload) { System.out.println(payload); }
}
""",
}


def _spring_cloud_demo_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "examples" / "spring-cloud-demo"
    return sorted(root.rglob("*.java"))


@pytest.mark.skipif(not _HAS_TREE_SITTER, reason="tree-sitter not installed")
class TestParserSupplementsEquivalence:
    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch):
        monkeypatch.delenv("MEMORY_CENTER_PARSER_FULL_DUAL", raising=False)
        yield
        monkeypatch.delenv("MEMORY_CENTER_PARSER_FULL_DUAL", raising=False)

    @pytest.mark.parametrize("name", sorted(_SAMPLES.keys()))
    def test_supplements_match_full_dual_for_samples(self, name, monkeypatch) -> None:
        src = _SAMPLES[name]
        parser = TreeSitterJavaParser()
        if not parser.available:  # pragma: no cover - covered by skipif
            pytest.skip("tree-sitter parser unavailable at runtime")
        monkeypatch.setenv("MEMORY_CENTER_PARSER_FULL_DUAL", "1")
        legacy = parser.parse(src, name)
        monkeypatch.delenv("MEMORY_CENTER_PARSER_FULL_DUAL", raising=False)
        fast = parser.parse(src, name)
        assert asdict(fast) == asdict(legacy), name

    def test_supplements_match_for_spring_cloud_demo(self, monkeypatch) -> None:
        parser = TreeSitterJavaParser()
        if not parser.available:  # pragma: no cover
            pytest.skip("tree-sitter parser unavailable at runtime")
        files = _spring_cloud_demo_files()
        assert files, "expected at least one example Java file"
        diffs = []
        for path in files:
            src = path.read_text(encoding="utf-8")
            monkeypatch.setenv("MEMORY_CENTER_PARSER_FULL_DUAL", "1")
            legacy = parser.parse(src, str(path))
            monkeypatch.delenv("MEMORY_CENTER_PARSER_FULL_DUAL", raising=False)
            fast = parser.parse(src, str(path))
            if asdict(fast) != asdict(legacy):
                diffs.append(path.name)
        assert not diffs, f"supplements diverged for: {diffs}"

    def test_supplements_path_records_diagnostic_counter(self, monkeypatch) -> None:
        parser = TreeSitterJavaParser()
        if not parser.available:  # pragma: no cover
            pytest.skip("tree-sitter parser unavailable at runtime")
        parser.reset_diagnostics()
        parser.parse(_SAMPLES["controller.java"], "controller.java")
        d = parser.diagnostics
        assert d["supplement_call_count"] == 1
        assert d["full_regex_fallback_count"] == 0
        assert d["full_dual_mode"] is False

    def test_full_dual_mode_records_diagnostic_counter(self, monkeypatch) -> None:
        parser = TreeSitterJavaParser()
        if not parser.available:  # pragma: no cover
            pytest.skip("tree-sitter parser unavailable at runtime")
        parser.reset_diagnostics()
        monkeypatch.setenv("MEMORY_CENTER_PARSER_FULL_DUAL", "1")
        parser.parse(_SAMPLES["controller.java"], "controller.java")
        d = parser.diagnostics
        assert d["full_regex_fallback_count"] == 1
        assert d["supplement_call_count"] == 0
        assert d["full_dual_mode"] is True
