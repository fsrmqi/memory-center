from __future__ import annotations

import json
from pathlib import Path

import yaml

from memory_center.core.indexing.java_call_resolver import JavaCallResolver, build_java_class_index
from memory_center.core.indexing.java_regex_parser import RegexJavaParser
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.orchestrator.query import memory_callees
from memory_center.core.storage.graph import node_id
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


def _symbol(project: str, file: str, source: str) -> dict:
    parsed = RegexJavaParser().parse(source, file)
    return {
        "project": project,
        "file": file,
        "package": parsed.package,
        "classes": parsed.classes,
        "interfaces": parsed.interfaces,
        "type_supertypes": parsed.type_supertypes,
        "methods": parsed.methods,
        "method_signatures": parsed.method_signatures,
        "fields": parsed.fields,
        "annotations": parsed.annotations,
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


def test_resolves_package_private_method_parameter_and_local_types() -> None:
    caller = """package com.example.order;
public class CaptchaHandler {
    void validate(LoginRequest request) {
        CaptchaPayload payload = new CaptchaPayload();
        payload.setCode(request.getCode());
    }
}
"""
    target = """package com.example.order;
public class CaptchaPayload {
    public void setCode(String code) {}
}
"""
    symbols = [_symbol("svc", "CaptchaHandler.java", caller), _symbol("svc", "CaptchaPayload.java", target)]
    owner = symbols[0]
    assert owner["method_variable_types"]["validate"] == {
        "request": "LoginRequest",
        "payload": "CaptchaPayload",
    }
    supplements = RegexJavaParser().parse_supplements(caller, "CaptchaHandler.java")
    assert supplements.method_variable_types["validate"] == owner["method_variable_types"]["validate"]
    assert next(call for call in supplements.method_calls if call["method_name"] == "setCode")["owner_method"] == "validate"

    result = _resolve(symbols, "CaptchaHandler.java", "setCode")

    assert result.target_class == "CaptchaPayload"
    assert result.target_method == "setCode"
    assert result.resolution_level == "same_package"


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


def test_static_receiver_without_workspace_source_is_not_counted_as_missing_local_type() -> None:
    caller = """package com.example.order;
public class OrderController {
    void submit() { Assert.notNull("order"); }
}
"""
    symbols = [_symbol("api", "OrderController.java", caller)]

    result = _resolve(symbols, "OrderController.java", "notNull")

    assert result.resolution_level == "unresolved"
    assert result.unresolved_reason == "static_receiver_not_indexed"


def test_this_call_without_workspace_declaration_is_inherited_scope_not_missing_type() -> None:
    symbol = _symbol("api", "OrderController.java", "package com.example; public class OrderController { void run() { this.list(); } }")
    result = _resolve([symbol], "OrderController.java", "list")
    assert result.unresolved_reason == "inherited_method_out_of_scope"


def test_known_workspace_type_object_method_is_inherited_scope_not_polymorphism() -> None:
    caller = """package com.example;
public class OrderFacade {
    private Order order;
    void compare(Order other) { order.equals(other); }
}
"""
    target = """package com.example;
public class Order { private String id; }
"""

    result = _resolve(
        [_symbol("api", "OrderFacade.java", caller), _symbol("api", "Order.java", target)],
        "OrderFacade.java",
        "equals",
    )

    assert result.resolution_level == "unresolved"
    assert result.unresolved_reason == "inherited_method_out_of_scope"


def test_known_workspace_type_unknown_method_stays_polymorphism_candidate() -> None:
    caller = """package com.example;
public class OrderFacade {
    private Order order;
    void process() { order.applyPolicy(); }
}
"""
    target = """package com.example;
public class Order { private String id; }
"""

    result = _resolve(
        [_symbol("api", "OrderFacade.java", caller), _symbol("api", "Order.java", target)],
        "OrderFacade.java",
        "applyPolicy",
    )

    assert result.unresolved_reason == "target_method_not_indexed"


def test_external_static_import_is_not_confused_with_same_named_workspace_type() -> None:
    caller = """package com.example.order;
import com.thirdparty.DateUtil;
public class OrderController {
    void submit() { DateUtil.now(); }
}
"""
    local_collision = """package com.example.internal;
public class DateUtil {
    public static void localOnly() {}
}
"""
    result = _resolve(
        [_symbol("api", "OrderController.java", caller), _symbol("api", "DateUtil.java", local_collision)],
        "OrderController.java",
        "now",
    )

    assert result.resolution_level == "unresolved"
    assert result.unresolved_reason == "static_receiver_not_indexed"


def test_catch_parameter_type_is_available_to_call_resolution() -> None:
    caller = """package com.example.order;
public class OrderController {
    void submit() {
        try { run(); }
        catch (Exception e) { e.getMessage(); }
    }
    void run() {}
}
"""
    symbol = _symbol("api", "OrderController.java", caller)

    assert symbol["method_variable_types"]["submit"]["e"] == "Exception"
    result = _resolve([symbol], "OrderController.java", "getMessage")

    assert result.resolution_level == "unresolved"
    assert result.receiver_type == "Exception"
    assert result.unresolved_reason == "receiver_type_not_indexed"


def test_multi_catch_parameter_remains_unresolved_without_guessing_a_type() -> None:
    caller = """package com.example.order;
public class OrderController {
    void submit() {
        try { run(); }
        catch (IllegalArgumentException | IllegalStateException e) { e.getMessage(); }
    }
    void run() {}
}
"""
    symbol = _symbol("api", "OrderController.java", caller)

    assert "e" not in symbol["method_variable_types"]["submit"]


def test_resolves_inherited_lombok_accessor_to_workspace_parent() -> None:
    caller = """package com.example.order;
public class OrderFacade { void submit(OrderRequest request) { request.getTenantId(); } }
"""
    child = """package com.example.order;
import lombok.Data;
@Data public class OrderRequest extends BaseRequest { private String orderId; }
"""
    parent = """package com.example.order;
import lombok.Data;
@Data public class BaseRequest { private Long tenantId; }
"""
    result = _resolve(
        [_symbol("api", "OrderFacade.java", caller), _symbol("api", "OrderRequest.java", child), _symbol("api", "BaseRequest.java", parent)],
        "OrderFacade.java",
        "getTenantId",
    )

    assert result.target_class == "BaseRequest"
    assert result.resolution_level == "same_package_inherited_lombok_accessor"
    assert result.inferred_target is True


def test_resolves_lombok_boolean_is_prefixed_field_setter() -> None:
    caller = """package com.example.order;
public class OrderFacade { void submit(Result result) { result.setSuccess(true); } }
"""
    target = """package com.example.order;
import lombok.Data;
@Data public class Result { private boolean isSuccess; }
"""

    result = _resolve(
        [_symbol("api", "OrderFacade.java", caller), _symbol("api", "Result.java", target)],
        "OrderFacade.java",
        "setSuccess",
    )

    assert result.target_class == "Result"
    assert result.resolution_level == "same_package_lombok_accessor"
    assert result.matched_signature == "lombok_accessor:isSuccess"


def test_extracts_generic_enhanced_for_variable_type() -> None:
    symbol = _symbol("api", "Demo.java", """package com.example;
import java.util.Map;
public class Demo { void run(Map<String, Long> values) { for (Map.Entry<String, Long> entry : values.entrySet()) { entry.getValue(); } } }
""")
    assert symbol["method_variable_types"]["run"]["entry"] == "Entry"


def test_extracts_try_with_resources_variable_type() -> None:
    symbol = _symbol("api", "Demo.java", "package com.example; public class Demo { void run() { try (InputStream stream = open()) { stream.read(); } } }")
    assert symbol["method_variable_types"]["run"]["stream"] == "InputStream"


def test_resolves_chain_when_return_type_is_unique() -> None:
    caller = """package com.example; public class Caller { void run(Factory factory) { factory.create().execute(); } }"""
    factory = """package com.example; public class Factory { public Result create() { return null; } }"""
    result = """package com.example; public class Result { public void execute() {} }"""
    resolved = _resolve([_symbol("api", "Caller.java", caller), _symbol("api", "Factory.java", factory), _symbol("api", "Result.java", result)], "Caller.java", "execute")
    assert resolved.target_class == "Result"
    assert resolved.resolution_level == "chain_return_type"


def test_resolves_chain_when_lombok_accessor_field_type_is_unique() -> None:
    caller = """package com.example; public class Caller { void run(Envelope envelope) { envelope.getPayload().execute(); } }"""
    envelope = """package com.example; import lombok.Data; @Data public class Envelope { private Payload payload; }"""
    payload = """package com.example; public class Payload { public void execute() {} }"""

    resolved = _resolve(
        [_symbol("api", "Caller.java", caller), _symbol("api", "Envelope.java", envelope), _symbol("api", "Payload.java", payload)],
        "Caller.java",
        "execute",
    )

    assert resolved.target_class == "Payload"
    assert resolved.target_method == "execute"
    assert resolved.resolution_level == "chain_lombok_accessor_return_type"
    assert resolved.confidence == 0.8


def test_lombok_chain_does_not_resolve_field_type_outside_workspace() -> None:
    caller = """package com.example; public class Caller { void run(Envelope envelope) { envelope.getPage().getCurrent(); } }"""
    envelope = """package com.example; import lombok.Data; @Data public class Envelope { private ExternalPage page; }"""

    resolved = _resolve(
        [_symbol("api", "Caller.java", caller), _symbol("api", "Envelope.java", envelope)],
        "Caller.java",
        "getCurrent",
    )

    assert resolved.resolution_level == "unresolved"
    assert resolved.unresolved_reason == "target_method_not_indexed"


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


def test_resolves_lombok_data_accessor_from_explicit_import() -> None:
    caller = """package com.example.order;
import com.example.api.OrderResult;
public class OrderFacade {
    private OrderResult result;
    public String submit() { return result.getCode(); }
}
"""
    target = """package com.example.api;
import lombok.Data;
@Data
public class OrderResult {
    private String code;
}
"""
    result = _resolve(
        [_symbol("svc", "OrderFacade.java", caller), _symbol("api", "OrderResult.java", target)],
        "OrderFacade.java",
        "getCode",
    )
    assert result.target_fqcn == "com.example.api.OrderResult"
    assert result.resolution_level == "import_lombok_accessor"
    assert result.confidence == 0.85
    assert result.inferred_target is True
    assert result.matched_signature == "lombok_accessor:code"


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
    assert result.unresolved_reason == "receiver_type_not_indexed"


def test_parser_does_not_treat_constructor_call_as_bare_method_call() -> None:
    src = """package com.example.order;
public class OrderFacade {
    public void submit() {
        Helper helper = new Helper();
        helper.run();
    }
}
"""
    parsed = RegexJavaParser().parse(src, "OrderFacade.java")
    method_names = {item["method_name"] for item in parsed.method_calls}
    assert "Helper" not in method_names
    assert "run" in method_names


def test_parser_ignores_annotation_expressions_and_field_initializers() -> None:
    src = """package com.example.order;
@PreAuthorize("@ss.hasPermission('order:read')")
public class OrderFacade {
    private ExecutorService executor = Executors.newSingleThreadExecutor();
    private OrderService orderService;

    public void submit() {
        orderService.create();
    }
}
"""
    parsed = RegexJavaParser().parse(src, "OrderFacade.java")
    calls = {(item["receiver"], item["method_name"], item["owner_method"]) for item in parsed.method_calls}

    assert ("ss", "hasPermission", "") not in calls
    assert ("Executors", "newSingleThreadExecutor", "") not in calls
    assert calls == {("orderService", "create", "submit")}


def test_reindex_persists_resolved_call_metadata_and_filters_low_confidence(tmp_path: Path) -> None:
    service = tmp_path / "svc"
    source_dir = service / "src" / "main" / "java" / "com" / "example"
    billing_dir = service / "src" / "main" / "java" / "com" / "billing"
    api_dir = service / "src" / "main" / "java" / "com" / "api"
    other_dir = service / "src" / "main" / "java" / "com" / "other"
    source_dir.mkdir(parents=True)
    billing_dir.mkdir(parents=True)
    api_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    (source_dir / "OrderFacade.java").write_text(
        """package com.example;
import com.billing.InvoiceService;
import com.api.OrderResult;
public class OrderFacade {
    private InvoiceService invoiceService;
    private MissingService missingService;
    private OrderResult orderResult;
    public void submit() {
        invoiceService.create("id");
        missingService.create();
        orderResult.getCode();
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
    (api_dir / "OrderResult.java").write_text(
        """package com.api;
import lombok.Data;
@Data
public class OrderResult {
    private String code;
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
    lombok_target_id = node_id("Method", "svc", "OrderResult", "getCode")
    unresolved_id = node_id("Method", "svc", "MissingService", "create")
    unrelated_id = node_id("Method", "svc", "OtherService", "create")
    with RuntimeStore(store.graph_db_path) as graph:
        conn = graph.connect()
        resolved = conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='CALLS_METHOD'",
            (source_id, target_id),
        ).fetchone()
        unresolved = conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='CALLS_METHOD'",
            (source_id, unresolved_id),
        ).fetchone()
        lombok_accessor = conn.execute(
            "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type='CALLS_METHOD'",
            (source_id, lombok_target_id),
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
    assert resolved_meta["unresolved_reason"] == ""
    assert lombok_accessor is not None
    lombok_meta = json.loads(lombok_accessor["metadata_json"])
    assert lombok_accessor["confidence"] == 0.85
    assert lombok_meta["resolution_level"] == "import_lombok_accessor"
    assert lombok_meta["matched_signature"] == "lombok_accessor:code"
    assert lombok_meta["inferred_target"] is True
    assert unresolved is not None
    assert unresolved["confidence"] == 0.3
    unresolved_meta = json.loads(unresolved["metadata_json"])
    assert unresolved_meta["resolution_level"] == "unresolved"
    assert unresolved_meta["unresolved_reason"] == "receiver_type_not_indexed"
    assert unrelated is None

    default_chain = memory_callees(str(workspace), "OrderFacade.submit", depth=1, limit=10)
    assert {edge["target"]["name"] for edge in default_chain["callees"]} == {"InvoiceService.create"}
    full_chain = memory_callees(str(workspace), "OrderFacade.submit", depth=1, limit=10, min_confidence=0)
    assert {edge["target"]["name"] for edge in full_chain["callees"]} == {
        "InvoiceService.create",
        "MissingService.create",
    }
