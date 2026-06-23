from __future__ import annotations

import json
from pathlib import Path

import yaml

from memory_center.core.config import load_workspace_config
from memory_center.core.graph import GraphStore, node_id
from memory_center.core.indexer import reindex_workspace
from memory_center.core.indexing.java_call_resolver import JavaCallResolver, build_java_class_index
from memory_center.core.indexing.java_regex_parser import RegexJavaParser
from memory_center.core.orchestrator.query import memory_callees
from memory_center.core.store import WorkspaceStore


def _symbol(project: str, file: str, source: str) -> dict:
    parsed = RegexJavaParser().parse(source, file)
    return {
        "project": project,
        "file": file,
        "package": parsed.package,
        "classes": parsed.classes,
        "interfaces": parsed.interfaces,
        "methods": parsed.methods,
        "method_signatures": parsed.method_signatures,
        "imports": parsed.imports,
        "field_types": parsed.field_types,
        "method_variable_types": parsed.method_variable_types,
        "method_calls": parsed.method_calls,
    }


def _resolve(symbols: list[dict], owner_file: str, method_name: str):
    index = build_java_class_index(symbols)
    resolver = JavaCallResolver(index)
    owner = next(item for item in symbols if item["file"] == owner_file)
    call = next(item for item in owner["method_calls"] if item["method_name"] == method_name)
    return resolver.resolve_call(owner, call)


def test_resolves_same_class_this_call() -> None:
    src = """package com.example.order;
public class OrderService {
    public void process() { this.validate(); }
    public void validate() {}
}
"""
    result = _resolve([_symbol("svc", "OrderService.java", src)], "OrderService.java", "validate")
    assert result.target_class == "OrderService"
    assert result.target_method == "validate"
    assert result.resolution_level == "same_class"
    assert result.confidence == 1.0


def test_resolves_same_package_receiver_type() -> None:
    caller = """package com.example.order;
public class OrderFacade {
    private PaymentService paymentService;
    public void submit() { paymentService.pay(); }
}
"""
    target = """package com.example.order;
public class PaymentService {
    public void pay() {}
}
"""
    result = _resolve(
        [_symbol("svc", "OrderFacade.java", caller), _symbol("svc", "PaymentService.java", target)],
        "OrderFacade.java",
        "pay",
    )
    assert result.target_class == "PaymentService"
    assert result.resolution_level == "same_package"
    assert result.confidence == 0.9


def test_resolves_explicit_import_receiver_type() -> None:
    caller = """package com.example.order;
import com.example.billing.InvoiceService;
public class OrderFacade {
    private InvoiceService invoiceService;
    public void submit() { invoiceService.create(); }
}
"""
    target = """package com.example.billing;
public class InvoiceService {
    public void create() {}
}
"""
    result = _resolve(
        [_symbol("svc", "OrderFacade.java", caller), _symbol("svc", "InvoiceService.java", target)],
        "OrderFacade.java",
        "create",
    )
    assert result.target_fqcn == "com.example.billing.InvoiceService"
    assert result.resolution_level == "import"
    assert result.confidence == 0.85


def test_resolves_wildcard_import_receiver_type() -> None:
    caller = """package com.example.order;
import com.example.billing.*;
public class OrderFacade {
    private InvoiceService invoiceService;
    public void submit() { invoiceService.create(); }
}
"""
    target = """package com.example.billing;
public class InvoiceService {
    public void create() {}
}
"""
    result = _resolve(
        [_symbol("svc", "OrderFacade.java", caller), _symbol("svc", "InvoiceService.java", target)],
        "OrderFacade.java",
        "create",
    )
    assert result.target_class == "InvoiceService"
    assert result.resolution_level == "wildcard_import"
    assert result.confidence == 0.6


def test_resolves_static_import_unqualified_call() -> None:
    caller = """package com.example.order;
import static com.example.util.OrderNames.normalize;
public class OrderFacade {
    public void submit() { normalize("a"); }
}
"""
    target = """package com.example.util;
public class OrderNames {
    public static String normalize(String value) { return value; }
}
"""
    result = _resolve(
        [_symbol("svc", "OrderFacade.java", caller), _symbol("svc", "OrderNames.java", target)],
        "OrderFacade.java",
        "normalize",
    )
    assert result.target_class == "OrderNames"
    assert result.resolution_level == "static_import"
    assert result.confidence == 0.85


def test_overload_keeps_matching_signature_evidence() -> None:
    caller = """package com.example.order;
import com.example.billing.InvoiceService;
public class OrderFacade {
    private InvoiceService invoiceService;
    public void submit() { invoiceService.create("id"); }
}
"""
    target = """package com.example.billing;
public class InvoiceService {
    public void create() {}
    public void create(String id) {}
}
"""
    result = _resolve(
        [_symbol("svc", "OrderFacade.java", caller), _symbol("svc", "InvoiceService.java", target)],
        "OrderFacade.java",
        "create",
    )
    assert result.arg_count == 1
    assert result.matched_signature == "create(String)"
    assert result.resolution_level == "import"


def test_unresolved_call_is_low_confidence_and_not_bound_to_random_same_name() -> None:
    caller = """package com.example.order;
public class OrderFacade {
    private UnknownService unknownService;
    public void submit() { unknownService.create(); }
}
"""
    unrelated = """package com.example.other;
public class OtherService {
    public void create() {}
}
"""
    result = _resolve(
        [_symbol("svc", "OrderFacade.java", caller), _symbol("svc", "OtherService.java", unrelated)],
        "OrderFacade.java",
        "create",
    )
    assert result.resolution_level == "unresolved"
    assert result.confidence == 0.3
    assert result.target_class == "UnknownService"


def test_reindex_persists_resolved_call_metadata_and_filters_low_confidence(tmp_path: Path) -> None:
    service = tmp_path / "svc"
    source_dir = service / "src" / "main" / "java" / "com" / "example"
    billing_dir = service / "src" / "main" / "java" / "com" / "billing"
    other_dir = service / "src" / "main" / "java" / "com" / "other"
    source_dir.mkdir(parents=True)
    billing_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    (source_dir / "OrderFacade.java").write_text(
        """package com.example;
import com.billing.InvoiceService;
public class OrderFacade {
    private InvoiceService invoiceService;
    private MissingService missingService;
    public void submit() {
        invoiceService.create("id");
        missingService.create();
    }
}
""",
        encoding="utf-8",
    )
    (billing_dir / "InvoiceService.java").write_text(
        """package com.billing;
public class InvoiceService {
    public void create() {}
    public void create(String id) {}
}
""",
        encoding="utf-8",
    )
    (other_dir / "OtherService.java").write_text(
        """package com.other;
public class OtherService {
    public void create() {}
}
""",
        encoding="utf-8",
    )
    workspace_dir = tmp_path / ".memory-center"
    workspace_dir.mkdir()
    workspace = workspace_dir / "workspace.yaml"
    workspace.write_text(
        yaml.safe_dump(
            {
                "workspace": "resolver-demo",
                "root": str(tmp_path),
                "services": [{"name": "svc", "path": "svc"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    store = WorkspaceStore(str(workspace))
    reindex_workspace(load_workspace_config(workspace), store)

    source_id = node_id("Method", "svc", "OrderFacade", "submit")
    target_id = node_id("Method", "svc", "InvoiceService", "create")
    unresolved_id = node_id("Method", "svc", "MissingService", "create")
    unrelated_id = node_id("Method", "svc", "OtherService", "create")
    with GraphStore(store.graph_db_path) as graph:
        conn = graph.connect()
        resolved = conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='CALLS_METHOD'",
            (source_id, target_id),
        ).fetchone()
        unresolved = conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='CALLS_METHOD'",
            (source_id, unresolved_id),
        ).fetchone()
        unrelated = conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='CALLS_METHOD'",
            (source_id, unrelated_id),
        ).fetchone()

    assert resolved is not None
    resolved_meta = json.loads(resolved["metadata_json"])
    assert resolved["confidence"] == 0.85
    assert resolved_meta["resolution_level"] == "import"
    assert resolved_meta["matched_signature"] == "create(String)"
    assert unresolved is not None
    assert unresolved["confidence"] == 0.3
    assert json.loads(unresolved["metadata_json"])["resolution_level"] == "unresolved"
    assert unrelated is None

    default_chain = memory_callees(str(workspace), "OrderFacade.submit", depth=1, limit=10)
    assert {edge["target"]["name"] for edge in default_chain["callees"]} == {"InvoiceService.create"}
    full_chain = memory_callees(str(workspace), "OrderFacade.submit", depth=1, limit=10, min_confidence=0)
    assert {edge["target"]["name"] for edge in full_chain["callees"]} == {
        "InvoiceService.create",
        "MissingService.create",
    }
