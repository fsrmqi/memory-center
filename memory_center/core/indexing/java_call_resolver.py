from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_JAVA_OBJECT_METHODS = frozenset({
    "clone",
    "equals",
    "finalize",
    "getClass",
    "hashCode",
    "notify",
    "notifyAll",
    "toString",
    "wait",
})


@dataclass(frozen=True)
class ClassInfo:
    project: str
    file: str
    package: str
    name: str
    fqcn: str
    type_kind: str = "class"
    methods: set[str] = field(default_factory=set)
    method_signatures: list[dict[str, Any]] = field(default_factory=list)
    fields: set[str] = field(default_factory=set)
    field_types: dict[str, str] = field(default_factory=dict)
    annotations: set[str] = field(default_factory=set)
    imports: tuple[str, ...] = ()
    supertypes: tuple[str, ...] = ()


@dataclass(frozen=True)
class JavaClassIndex:
    by_fqcn: dict[str, ClassInfo]
    by_package_simple: dict[tuple[str, str], ClassInfo]
    by_simple: dict[str, list[ClassInfo]]
    by_project_file: dict[tuple[str, str], list[ClassInfo]]


@dataclass(frozen=True)
class ResolvedCall:
    source_project: str
    source_file: str
    source_class: str
    source_method: str
    target_project: str
    target_file: str
    target_class: str
    target_method: str
    target_fqcn: str
    confidence: float
    resolution_level: str
    receiver: str = ""
    receiver_type: str = ""
    line: int = 0
    arg_count: int | None = None
    matched_signature: str = ""
    inferred_target: bool = False
    unresolved_reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def build_java_class_index(symbols: list[dict[str, Any]]) -> JavaClassIndex:
    by_fqcn: dict[str, ClassInfo] = {}
    by_package_simple: dict[tuple[str, str], ClassInfo] = {}
    by_simple: dict[str, list[ClassInfo]] = {}
    by_project_file: dict[tuple[str, str], list[ClassInfo]] = {}

    for sym in symbols:
        package = str(sym.get("package") or "")
        project = str(sym.get("project") or "")
        file = str(sym.get("file") or "")
        methods = {str(item) for item in sym.get("methods", []) if item}
        signatures = list(sym.get("method_signatures", []) or [])
        fields = {str(item) for item in sym.get("fields", []) if item}
        annotations = {str(item) for item in sym.get("annotations", []) if item}
        for name in list(sym.get("classes", []) or []) + list(sym.get("interfaces", []) or []):
            class_name = str(name or "").strip()
            if not class_name:
                continue
            fqcn = f"{package}.{class_name}" if package else class_name
            info = ClassInfo(
                project=project,
                file=file,
                package=package,
                name=class_name,
                fqcn=fqcn,
                type_kind=str((sym.get("type_kinds", {}) or {}).get(class_name, "class") or "class"),
                methods=methods,
                method_signatures=signatures,
                fields=fields,
                field_types={str(key): str(value) for key, value in (sym.get("field_types", {}) or {}).items() if key and value},
                annotations=annotations,
                imports=tuple(str(item) for item in sym.get("imports", []) if item),
                supertypes=tuple(str(item) for item in (sym.get("type_supertypes", {}) or {}).get(class_name, []) if item),
            )
            by_fqcn[fqcn] = info
            by_package_simple[(package, class_name)] = info
            by_simple.setdefault(class_name, []).append(info)
            by_project_file.setdefault((project, file), []).append(info)

    return JavaClassIndex(
        by_fqcn=by_fqcn,
        by_package_simple=by_package_simple,
        by_simple=by_simple,
        by_project_file=by_project_file,
    )


class JavaCallResolver:
    """Resolve Java method-call evidence to a single best target.

    The resolver is intentionally compiler-light: it uses facts already
    extracted during indexing and applies deterministic fallbacks from
    highest to lowest precision.
    """

    def __init__(self, class_index: JavaClassIndex):
        self.class_index = class_index

    def resolve_call(self, owner_symbol: dict[str, Any], call: dict[str, Any]) -> ResolvedCall:
        owner = self._owner_class(owner_symbol)
        target_method = str(call.get("method_name") or "")
        receiver = str(call.get("receiver") or "")
        owner_method = str(call.get("owner_method") or "")
        receiver_type = self._receiver_type(owner_symbol, call)
        arg_count = _safe_int_or_none(call.get("arg_count"))

        candidates: list[tuple[ClassInfo, str, float]] = []
        candidates.extend(self._same_class_candidates(owner, receiver, receiver_type, target_method))
        candidates.extend(self._static_import_candidates(owner_symbol, receiver, target_method))
        candidates.extend(self._explicit_import_candidates(owner_symbol, receiver_type, receiver, target_method))
        candidates.extend(self._same_package_candidates(owner_symbol, receiver_type, receiver, target_method))
        candidates.extend(self._wildcard_import_candidates(owner_symbol, receiver_type, receiver, target_method))

        chain_method = str(call.get("chain_receiver_method") or "")
        if chain_method:
            chain_arg_count = _safe_int_or_none(call.get("chain_arg_count"))
            chain_argument_types = _chain_argument_types(owner_symbol, call)
            for info, _level, _confidence in candidates:
                return_type = _method_return_type(
                    info.method_signatures,
                    chain_method,
                    arg_count=chain_arg_count,
                    argument_types=chain_argument_types,
                )
                resolution_level = "chain_return_type"
                confidence = 0.78
                if not return_type:
                    lombok_field = _lombok_accessor_field(info, chain_method)
                    return_type = _normalize_type_name(info.field_types.get(lombok_field, "")) if lombok_field else ""
                    resolution_level = "chain_lombok_accessor_return_type"
                    confidence = 0.8
                if not return_type and chain_method in {"builder", "toBuilder"} and _has_lombok_builder(info):
                    # Lombok @Builder: ``X.builder()`` returns the generated
                    # builder whose setters mirror the class fields and whose
                    # ``build()`` returns the annotated class itself.
                    return_type = info.name
                    resolution_level = "chain_lombok_builder"
                    confidence = 0.78
                return_candidates = self.class_index.by_simple.get(return_type, []) if return_type else []
                if len(return_candidates) == 1:
                    return_info = return_candidates[0]
                    if target_method in return_info.methods:
                        return self._resolved(owner_symbol, owner, call, return_info, resolution_level, confidence, arg_count)
                    lombok_field = _lombok_accessor_field(return_info, target_method)
                    if lombok_field:
                        return self._resolved(
                            owner_symbol,
                            owner,
                            call,
                            return_info,
                            f"{resolution_level}_lombok_accessor",
                            confidence,
                            arg_count,
                            inferred_target=True,
                            matched_signature=f"lombok_accessor:{lombok_field}",
                        )
                    if resolution_level == "chain_lombok_builder":
                        builder_field = _lombok_builder_field(return_info, target_method)
                        if builder_field:
                            return self._resolved(
                                owner_symbol, owner, call, return_info,
                                f"{resolution_level}_setter", confidence, arg_count,
                                inferred_target=True, matched_signature=f"lombok_builder_setter:{builder_field}",
                            )
                        if target_method == "build":
                            return self._resolved(
                                owner_symbol, owner, call, return_info,
                                f"{resolution_level}_build", 0.8, arg_count,
                                inferred_target=True, matched_signature="lombok_builder_build",
                            )

        # Receiver types proven from a lambda parameter (collection element
        # generics, functional-interface generics) are locally provable but one
        # inference step further than a declared variable; surface that origin
        # in the resolution level instead of the lookup path that found the
        # class (import / same_package / ...). The class-literal-neighbor
        # shape is a heuristic (the callee signature is invisible), so it gets
        # its own origin and conservative confidence.
        receiver_origin = str(call.get("receiver_type_origin") or "")
        lambda_origin = receiver_origin in {"lambda_param", "class_literal_lambda"}
        heuristic_cap = 0.7 if receiver_origin == "class_literal_lambda" else 1.0

        for info, level, confidence in candidates:
            effective_level = receiver_origin if lambda_origin else level
            confidence = min(confidence, heuristic_cap)
            if target_method in info.methods:
                return self._resolved(owner_symbol, owner, call, info, effective_level, confidence, arg_count)
            if target_method in {"builder", "toBuilder"} and _has_lombok_builder(info):
                return self._resolved(
                    owner_symbol, owner, call, info,
                    f"{effective_level}_lombok_builder", min(0.85, heuristic_cap), arg_count,
                    inferred_target=True, matched_signature="lombok_builder",
                )
            lombok_field = _lombok_accessor_field(info, target_method)
            if lombok_field:
                return self._resolved(
                    owner_symbol,
                    owner,
                    call,
                    info,
                    f"{effective_level}_lombok_accessor",
                    confidence,
                    arg_count,
                    inferred_target=True,
                    matched_signature=f"lombok_accessor:{lombok_field}",
                )
            for ancestor in self._ancestor_candidates(info):
                if target_method in ancestor.methods:
                    return self._resolved(
                        owner_symbol, owner, call, ancestor,
                        f"{effective_level}_inherited", min(0.8, heuristic_cap), arg_count,
                    )
                lombok_field = _lombok_accessor_field(ancestor, target_method)
                if lombok_field:
                    return self._resolved(
                        owner_symbol, owner, call, ancestor,
                        f"{effective_level}_inherited_lombok_accessor", min(0.82, heuristic_cap), arg_count,
                        inferred_target=True, matched_signature=f"lombok_accessor:{lombok_field}",
                    )

        fallback_class = receiver_type or _class_like_receiver(receiver) or "unknown"
        return ResolvedCall(
            source_project=str(owner_symbol.get("project") or ""),
            source_file=str(owner_symbol.get("file") or ""),
            source_class=owner.name,
            source_method=owner_method,
            target_project=str(owner_symbol.get("project") or ""),
            target_file="",
            target_class=fallback_class,
            target_method=target_method,
            target_fqcn=fallback_class,
            confidence=0.3,
            resolution_level="unresolved",
            receiver=receiver,
            receiver_type=receiver_type,
            line=int(call.get("line") or 0),
            arg_count=arg_count,
            inferred_target=True,
            unresolved_reason=self._unresolved_reason(
                owner_symbol,
                receiver,
                receiver_type,
                target_method,
                call=call,
            ),
            evidence=dict(call),
        )

    def _resolved(
        self,
        owner_symbol: dict[str, Any],
        owner: ClassInfo,
        call: dict[str, Any],
        info: ClassInfo,
        level: str,
        confidence: float,
        arg_count: int | None,
        *,
        inferred_target: bool = False,
        matched_signature: str = "",
    ) -> ResolvedCall:
        target_method = str(call.get("method_name") or "")
        return ResolvedCall(
            source_project=str(owner_symbol.get("project") or ""),
            source_file=str(owner_symbol.get("file") or ""),
            source_class=owner.name,
            source_method=str(call.get("owner_method") or ""),
            target_project=info.project,
            target_file=info.file,
            target_class=info.name,
            target_method=target_method,
            target_fqcn=info.fqcn,
            confidence=confidence,
            resolution_level=level,
            receiver=str(call.get("receiver") or ""),
            receiver_type=self._receiver_type(owner_symbol, call),
            line=int(call.get("line") or 0),
            arg_count=arg_count,
            matched_signature=matched_signature or _match_signature(info.method_signatures, target_method, arg_count),
            inferred_target=inferred_target,
            evidence=dict(call),
        )

    def _unresolved_reason(
        self,
        owner_symbol: dict[str, Any],
        receiver: str,
        receiver_type: str,
        target_method: str,
        *,
        call: dict[str, Any] | None = None,
    ) -> str:
        if not receiver_type:
            if receiver in {"this", "super"}:
                return "inherited_method_out_of_scope"
            if not receiver:
                return "unqualified_or_dynamic"
            # A capitalized receiver is a static-style call.  It is not
            # evidence that local variable type extraction failed, and must
            # never be turned into a workspace edge when the class is absent.
            static_type = _class_like_receiver(receiver)
            if static_type:
                candidates = self._visible_type_candidates(owner_symbol, static_type)
                if not candidates:
                    return "static_receiver_not_indexed"
                if any(target_method in info.methods for info in candidates):
                    return "static_receiver_without_visible_import"
                if any(info.type_kind == "enum" for info in candidates) and target_method in {"values", "valueOf"}:
                    return "generated_enum_method_out_of_scope"
                return "target_method_not_indexed"
            return "receiver_type_missing"
        candidates = self.class_index.by_simple.get(receiver_type, [])
        if not candidates:
            return "receiver_type_not_indexed"
        if any(target_method in info.methods for info in candidates):
            return "target_out_of_scope"
        if any(_lombok_accessor_field(info, target_method) for info in candidates):
            return "lombok_target_out_of_scope"
        chain_reason = self._chain_unresolved_reason(candidates, owner_symbol, call or {})
        if chain_reason:
            return chain_reason
        # ``Object`` methods are inherited by every workspace class but are
        # normally absent from the source-defined method index. They are not
        # a local polymorphism gap and must not produce a synthetic edge.
        if target_method in _JAVA_OBJECT_METHODS:
            return "inherited_method_out_of_scope"
        if any(self._has_unindexed_parent(info) for info in candidates):
            return "inherited_method_out_of_scope"
        return "target_method_not_indexed"

    def _chain_unresolved_reason(
        self,
        candidates: list[ClassInfo],
        owner_symbol: dict[str, Any],
        call: dict[str, Any],
    ) -> str:
        chain_method = str(call.get("chain_receiver_method") or "")
        if not chain_method:
            return ""
        chain_arg_count = _safe_int_or_none(call.get("chain_arg_count"))
        argument_types = _chain_argument_types(owner_symbol, call)
        for info in candidates:
            return_type = _method_return_type(
                info.method_signatures,
                chain_method,
                arg_count=chain_arg_count,
                argument_types=argument_types,
            )
            if not return_type:
                lombok_field = _lombok_accessor_field(info, chain_method)
                return_type = _normalize_type_name(info.field_types.get(lombok_field, "")) if lombok_field else ""
            if return_type and not self.class_index.by_simple.get(return_type):
                return "chain_return_type_not_indexed"
        return ""

    def _has_unindexed_parent(self, info: ClassInfo, visited: set[str] | None = None) -> bool:
        if not info.supertypes:
            return False
        seen = set(visited or ())
        if info.fqcn in seen:
            return False
        seen.add(info.fqcn)
        ancestors = self._ancestor_candidates(info)
        indexed = {candidate.name for candidate in ancestors}
        if any(parent not in indexed for parent in info.supertypes):
            return True
        return any(self._has_unindexed_parent(ancestor, seen) for ancestor in ancestors)

    def _visible_type_candidates(self, owner_symbol: dict[str, Any], class_name: str) -> list[ClassInfo]:
        """Return only workspace classes visible to this source file.

        A simple-name lookup is intentionally insufficient here: a project
        can contain a local ``DateUtil`` while the source imports a third-party
        ``DateUtil``. Treating that collision as a local missing method sends
        external static calls into the polymorphism queue and encourages false
        call edges. Visibility mirrors the resolver's import/package rules.
        """

        candidates: list[ClassInfo] = []
        package = str(owner_symbol.get("package") or "")
        same_package = self.class_index.by_package_simple.get((package, class_name))
        if same_package:
            candidates.append(same_package)
        for imported in _normal_imports(owner_symbol.get("imports", []) or []):
            if imported.endswith(f".{class_name}"):
                info = self.class_index.by_fqcn.get(imported)
                if info:
                    candidates.append(info)
        for imported_package in _wildcard_import_packages(owner_symbol.get("imports", []) or []):
            info = self.class_index.by_package_simple.get((imported_package, class_name))
            if info:
                candidates.append(info)
        return _unique_class_infos(candidates)

    def _ancestor_candidates(self, info: ClassInfo) -> list[ClassInfo]:
        """Follow only directly visible, workspace-declared parent types."""

        candidates: list[ClassInfo] = []
        for parent in info.supertypes:
            same_package = self.class_index.by_package_simple.get((info.package, parent))
            if same_package:
                candidates.append(same_package)
            for imported in _normal_imports(list(info.imports)):
                if imported.endswith(f".{parent}"):
                    target = self.class_index.by_fqcn.get(imported)
                    if target:
                        candidates.append(target)
            for imported_package in _wildcard_import_packages(list(info.imports)):
                target = self.class_index.by_package_simple.get((imported_package, parent))
                if target:
                    candidates.append(target)
        return _unique_class_infos(candidates)

    def _owner_class(self, owner_symbol: dict[str, Any]) -> ClassInfo:
        project = str(owner_symbol.get("project") or "")
        file = str(owner_symbol.get("file") or "")
        classes = self.class_index.by_project_file.get((project, file), [])
        if classes:
            return classes[0]
        class_name = (owner_symbol.get("classes") or owner_symbol.get("interfaces") or [Path(file).stem or "unknown"])[0]
        package = str(owner_symbol.get("package") or "")
        fqcn = f"{package}.{class_name}" if package else str(class_name)
        return ClassInfo(
            project=project,
            file=file,
            package=package,
            name=str(class_name),
            fqcn=fqcn,
            type_kind=str((owner_symbol.get("type_kinds", {}) or {}).get(str(class_name), "class") or "class"),
        )

    def _receiver_type(self, owner_symbol: dict[str, Any], call: dict[str, Any]) -> str:
        receiver = str(call.get("receiver") or "")
        owner_method = str(call.get("owner_method") or "")
        direct = str(call.get("receiver_type") or "")
        if direct:
            return _normalize_type_name(direct)
        method_types = owner_symbol.get("method_variable_types", {}) or {}
        field_types = owner_symbol.get("field_types", {}) or {}
        return _normalize_type_name(
            str((method_types.get(owner_method, {}) or {}).get(receiver) or field_types.get(receiver) or "")
        )

    def _same_class_candidates(
        self,
        owner: ClassInfo,
        receiver: str,
        receiver_type: str,
        target_method: str,
    ) -> list[tuple[ClassInfo, str, float]]:
        if receiver in {"", "this", "super"} or receiver_type == owner.name or receiver == owner.name:
            return [(owner, "same_class", 1.0)]
        if not receiver and target_method in owner.methods:
            return [(owner, "same_class", 1.0)]
        return []

    def _same_package_candidates(
        self,
        owner_symbol: dict[str, Any],
        receiver_type: str,
        receiver: str,
        _target_method: str,
    ) -> list[tuple[ClassInfo, str, float]]:
        class_name = receiver_type or _class_like_receiver(receiver)
        package = str(owner_symbol.get("package") or "")
        info = self.class_index.by_package_simple.get((package, class_name))
        return [(info, "same_package", 0.9)] if info else []

    def _explicit_import_candidates(
        self,
        owner_symbol: dict[str, Any],
        receiver_type: str,
        receiver: str,
        _target_method: str,
    ) -> list[tuple[ClassInfo, str, float]]:
        class_name = receiver_type or _class_like_receiver(receiver)
        if not class_name:
            return []
        for imp in _normal_imports(owner_symbol.get("imports", []) or []):
            if imp.endswith(f".{class_name}"):
                info = self.class_index.by_fqcn.get(imp)
                if info:
                    return [(info, "import", 0.85)]
        return []

    def _wildcard_import_candidates(
        self,
        owner_symbol: dict[str, Any],
        receiver_type: str,
        receiver: str,
        _target_method: str,
    ) -> list[tuple[ClassInfo, str, float]]:
        class_name = receiver_type or _class_like_receiver(receiver)
        if not class_name:
            return []
        for package in _wildcard_import_packages(owner_symbol.get("imports", []) or []):
            info = self.class_index.by_package_simple.get((package, class_name))
            if info:
                return [(info, "wildcard_import", 0.6)]
        return []

    def _static_import_candidates(
        self,
        owner_symbol: dict[str, Any],
        receiver: str,
        target_method: str,
    ) -> list[tuple[ClassInfo, str, float]]:
        if receiver:
            return []
        candidates: list[tuple[ClassInfo, str, float]] = []
        for imp in _static_imports(owner_symbol.get("imports", []) or []):
            if imp.endswith(".*"):
                class_fqcn = imp[:-2]
                info = self.class_index.by_fqcn.get(class_fqcn)
                if info:
                    candidates.append((info, "static_wildcard_import", 0.6))
                continue
            class_fqcn, _, method = imp.rpartition(".")
            if method != target_method:
                continue
            info = self.class_index.by_fqcn.get(class_fqcn)
            if info:
                candidates.append((info, "static_import", 0.85))
        return candidates


def _normal_imports(imports: list[str]) -> list[str]:
    return [item.strip() for item in imports if item and not item.strip().startswith("static ") and not item.strip().endswith(".*")]


def _static_imports(imports: list[str]) -> list[str]:
    result: list[str] = []
    for item in imports:
        value = str(item or "").strip()
        if value.startswith("static "):
            result.append(value.removeprefix("static ").strip())
    return result


def _wildcard_import_packages(imports: list[str]) -> list[str]:
    result: list[str] = []
    for item in imports:
        value = str(item or "").strip()
        if value.startswith("static "):
            continue
        if value.endswith(".*"):
            result.append(value[:-2])
    return result


def _class_like_receiver(receiver: str) -> str:
    if receiver and receiver[0:1].isupper():
        return receiver
    return ""


def _normalize_type_name(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    clean = clean.split("<", 1)[0].rstrip("[]")
    return clean.split(".")[-1]


def _unique_class_infos(candidates: list[ClassInfo]) -> list[ClassInfo]:
    result: list[ClassInfo] = []
    seen: set[str] = set()
    for info in candidates:
        if info.fqcn in seen:
            continue
        seen.add(info.fqcn)
        result.append(info)
    return result


def _safe_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _match_signature(signatures: list[dict[str, Any]], method_name: str, arg_count: int | None) -> str:
    for item in signatures:
        if item.get("name") != method_name:
            continue
        parameter_types = item.get("parameter_types", []) or []
        if arg_count is None or len(parameter_types) == arg_count:
            return str(item.get("identity") or "")
    return ""


def _method_return_type(
    signatures: list[dict[str, Any]],
    method_name: str,
    *,
    arg_count: int | None = None,
    argument_types: tuple[str, ...] = (),
) -> str:
    candidates = [item for item in signatures if item.get("name") == method_name]
    if arg_count is not None:
        candidates = [item for item in candidates if len(item.get("parameter_types", []) or []) == arg_count]
    if argument_types:
        typed_candidates = [
            item
            for item in candidates
            if _parameter_types_match(item.get("parameter_types", []) or [], argument_types)
        ]
        if typed_candidates:
            candidates = typed_candidates
    matches = {
        _normalize_type_name(str(item.get("return_type") or "").split()[-1])
        for item in candidates
        if str(item.get("return_type") or "").strip()
    }
    matches.discard("")
    return matches.pop() if len(matches) == 1 else ""


def _chain_argument_types(owner_symbol: dict[str, Any], call: dict[str, Any]) -> tuple[str, ...]:
    owner_method = str(call.get("owner_method") or "")
    variables = (owner_symbol.get("method_variable_types", {}) or {}).get(owner_method, {}) or {}
    fields = owner_symbol.get("field_types", {}) or {}
    types: list[str] = []
    for name in call.get("chain_argument_names", []) or []:
        value = str(name or "")
        resolved = str(variables.get(value) or fields.get(value) or "")
        if not resolved:
            return ()
        types.append(_normalize_type_name(resolved))
    return tuple(types)


def _parameter_types_match(parameter_types: list[Any], argument_types: tuple[str, ...]) -> bool:
    if len(parameter_types) != len(argument_types):
        return False
    return all(
        _normalize_type_name(str(parameter_type)) == _normalize_type_name(argument_type)
        for parameter_type, argument_type in zip(parameter_types, argument_types, strict=True)
    )


def _lombok_accessor_field(info: ClassInfo, method_name: str) -> str:
    """Return the backing field when Lombok makes an accessor deterministic."""

    annotation_names = {item.split(".")[-1].lower() for item in info.annotations}
    for prefix, required_annotations in (
        ("get", {"data", "getter", "value"}),
        ("is", {"data", "getter", "value"}),
        ("set", {"data", "setter"}),
    ):
        suffix = method_name[len(prefix):] if method_name.startswith(prefix) else ""
        if not suffix or not suffix[0].isupper() or not (annotation_names & required_annotations):
            continue
        field_name = suffix[0].lower() + suffix[1:]
        # Lombok treats a boolean field named ``isSuccess`` as property
        # ``success``: it generates ``isSuccess()`` and ``setSuccess(...)``.
        # The source declaration retains the ``is`` prefix, so checking only
        # the JavaBeans property name loses a deterministic local edge.
        for candidate in (field_name, f"is{suffix}"):
            if candidate in info.fields:
                return candidate
    return ""


def _has_lombok_builder(info: ClassInfo) -> bool:
    """Return True when the class is annotated with Lombok ``@Builder``."""

    return any(str(item).split(".")[-1].lower() == "builder" for item in info.annotations)


def _lombok_builder_field(info: ClassInfo, method_name: str) -> str:
    """Return the field name when a builder setter mirrors a class field."""

    if not method_name or not _has_lombok_builder(info):
        return ""
    return method_name if method_name in info.fields else ""
