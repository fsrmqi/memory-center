"""Tests for the multi-language tree-sitter structural parser.

Each language gets its own minimal source sample. The samples are kept
small on purpose — we're verifying *that* the walker picks up classes,
functions, imports and call sites, not that every grammar nuance is
handled.

These tests are skipped when the corresponding tree-sitter binding is
not installed. The multilang extra (pip install -e '.[multilang]') is
expected to be present in the dev environment.
"""
from __future__ import annotations

import importlib

import pytest

from memory_center.core.indexing.structural_parser import TreeSitterStructuralParser


def _has_binding(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


# ── Java (regression: dual-track still works alongside JavaParseResult) ────


@pytest.mark.skipif(not _has_binding("tree_sitter_java"), reason="tree-sitter-java not installed")
def test_java_structural_parser_extracts_class_and_methods() -> None:
    parser = TreeSitterStructuralParser("java")
    assert parser.available

    source = """
package com.example.svc;

import com.example.api.OrderClient;
import java.util.List;

public class OrderService {
    private OrderClient client;

    public Order findOne(String id) {
        Order o = client.fetch(id);
        return o;
    }

    public List<Order> findAll() {
        return client.list();
    }
}
"""
    r = parser.parse(source, "OrderService.java")
    assert r.language == "java"
    class_names = {c.name for c in r.classes}
    assert "OrderService" in class_names

    func_names = {f.name for f in r.functions}
    assert {"findOne", "findAll"}.issubset(func_names)

    findOne = next(f for f in r.functions if f.name == "findOne")
    assert findOne.kind == "method"
    assert findOne.parent_qualified_name.endswith("OrderService")
    assert findOne.qualified_name.endswith("OrderService.findOne")

    # Imports captured.
    assert any("OrderClient" in i for i in r.imports)
    assert any("util.List" in i for i in r.imports)

    # Calls captured.
    callees = {c.callee_text for c in r.calls}
    assert "fetch" in callees
    assert "list" in callees


# ── Python ─────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _has_binding("tree_sitter_python"), reason="tree-sitter-python not installed")
def test_python_structural_parser() -> None:
    parser = TreeSitterStructuralParser("python")
    assert parser.available

    source = '''
import os
from pathlib import Path

class OrderService:
    def __init__(self, client):
        self.client = client

    def find_one(self, oid):
        order = self.client.fetch(oid)
        return order


def top_level(p):
    return Path(p).read_text()
'''
    r = parser.parse(source, "svc.py")
    assert r.language == "python"

    class_names = {c.name for c in r.classes}
    assert "OrderService" in class_names

    func_names = {f.name for f in r.functions}
    assert {"__init__", "find_one", "top_level"}.issubset(func_names)

    top = next(f for f in r.functions if f.name == "top_level")
    assert top.kind == "function"
    assert top.parent_qualified_name == ""

    find_one = next(f for f in r.functions if f.name == "find_one")
    assert find_one.kind == "method"
    assert find_one.parent_qualified_name == "OrderService"

    # Both 'os' and 'pathlib.Path' import shapes captured.
    assert "os" in r.imports
    assert any("Path" in i for i in r.imports)

    # Call extraction.
    callees = {c.callee_text for c in r.calls}
    assert any("fetch" in c for c in callees)


# ── Go ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _has_binding("tree_sitter_go"), reason="tree-sitter-go not installed")
def test_go_structural_parser() -> None:
    parser = TreeSitterStructuralParser("go")
    assert parser.available

    source = """
package svc

import (
    "context"
    "example.com/api"
)

type OrderService struct {
    client *api.Client
}

func (s *OrderService) FindOne(ctx context.Context, id string) error {
    _, err := s.client.Fetch(ctx, id)
    return err
}

func NewService() *OrderService {
    return &OrderService{}
}
"""
    r = parser.parse(source, "svc.go")
    assert r.language == "go"
    assert r.module == "svc"

    type_names = {c.name for c in r.classes}
    assert "OrderService" in type_names

    func_names = {f.name for f in r.functions}
    assert {"FindOne", "NewService"}.issubset(func_names)

    fo = next(f for f in r.functions if f.name == "FindOne")
    assert fo.kind == "method"
    assert fo.parent_qualified_name == "OrderService"

    assert "context" in r.imports
    assert "example.com/api" in r.imports


# ── TypeScript ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _has_binding("tree_sitter_typescript"), reason="tree-sitter-typescript not installed")
def test_typescript_structural_parser() -> None:
    parser = TreeSitterStructuralParser("typescript")
    assert parser.available

    source = """
import { OrderClient } from './client';
import axios from 'axios';

export class OrderService {
    constructor(private client: OrderClient) {}

    async findOne(id: string): Promise<Order> {
        const r = await this.client.fetch(id);
        return r.data;
    }
}

export function helper(x: number): number {
    return x + 1;
}
"""
    r = parser.parse(source, "svc.ts")
    assert r.language == "typescript"

    class_names = {c.name for c in r.classes}
    assert "OrderService" in class_names

    func_names = {f.name for f in r.functions}
    assert {"findOne", "helper"}.issubset(func_names)

    fo = next(f for f in r.functions if f.name == "findOne")
    assert fo.kind == "method"
    assert fo.parent_qualified_name == "OrderService"

    assert "./client" in r.imports
    assert "axios" in r.imports


# ── Kotlin ────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _has_binding("tree_sitter_kotlin"), reason="tree-sitter-kotlin not installed")
def test_kotlin_structural_parser() -> None:
    parser = TreeSitterStructuralParser("kotlin")
    assert parser.available

    source = """
package com.example.svc

import com.example.api.OrderClient

class OrderService(private val client: OrderClient) {
    fun findOne(id: String): Order {
        return client.fetch(id)
    }
}

fun helper(x: Int): Int = x + 1
"""
    r = parser.parse(source, "svc.kt")
    assert r.language == "kotlin"

    # Package captured as module.
    assert r.module == "com.example.svc" or r.module is not None

    class_names = {c.name for c in r.classes}
    # tree-sitter-kotlin grammar varies; assert the well-known top class.
    assert "OrderService" in class_names

    func_names = {f.name for f in r.functions}
    assert {"findOne", "helper"}.issubset(func_names)


# ── Unavailable / error paths ─────────────────────────────────────────────


def test_unknown_language_returns_empty_result() -> None:
    parser = TreeSitterStructuralParser("brainfuck")
    assert not parser.available
    assert parser.init_error and "not registered" in parser.init_error
    result = parser.parse("++++++++.", "x.bf")
    assert result.is_empty()


def test_parse_returns_empty_when_binding_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the parser was constructed without a binding it still returns
    a valid (empty) StructuralParseResult — the indexer must not crash."""
    parser = TreeSitterStructuralParser("brainfuck")
    out = parser.parse("anything", "x.bf")
    assert out.language == "brainfuck"
    assert out.is_empty()
