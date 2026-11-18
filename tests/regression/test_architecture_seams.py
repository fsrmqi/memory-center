from __future__ import annotations

import ast
import inspect
from importlib.util import resolve_name
from pathlib import Path

import pytest


def _imports_package(path: Path, package: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and ((node.module or "").startswith(package) or (node.module or "") == package.rsplit(".", 1)[-1]):
            return True
        if isinstance(node, ast.Import) and any(alias.name.startswith(package) for alias in node.names):
            return True
    return False


def _function_size(function) -> int:
    source = inspect.getsource(function)
    node = ast.parse(source).body[0]
    return node.end_lineno - node.lineno + 1


def test_walkthrough_runner_does_not_import_query_facade() -> None:
    from memory_center.core.walkthrough import analysis

    tree = ast.parse(inspect.getsource(analysis))
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(module.endswith("orchestrator.query") for module in imports)


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_registry_is_composed_from_route_families() -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_walkthrough_public_operations_are_thin_facades() -> None:
    from memory_center.core.orchestrator import query

    assert _function_size(query.memory_walkthrough_health) < 20
    assert _function_size(query.memory_eval_walkthrough_quality) < 20
    assert _function_size(query.memory_export_walkthrough_artifact) < 20


def test_core_root_contains_only_package_initialization() -> None:
    from memory_center import core

    root = Path(core.__file__).parent
    assert sorted(path.name for path in root.glob("*.py")) == ["__init__.py"]


def test_core_domain_modules_have_one_canonical_path() -> None:
    from memory_center.core.contracting.static import build_contract_snapshot
    from memory_center.core.indexing.control_plane import index_control_status
    from memory_center.core.retrieval.cross_service import route_cross_service_shards
    from memory_center.core.tasks.artifacts import create_task_space

    assert callable(build_contract_snapshot)
    assert callable(index_control_status)
    assert callable(route_cross_service_shards)
    assert callable(create_task_space)


def test_every_core_source_directory_has_a_module_readme() -> None:
    from memory_center import core

    root = Path(core.__file__).parent
    source_dirs = [root, *[path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").exists()]]
    assert not [str(path) for path in source_dirs if not (path / "README.md").exists()]


def test_ambiguous_core_module_names_do_not_return() -> None:
    from memory_center import core

    root = Path(core.__file__).parent
    forbidden = {
        "audit/completion.py",
        "benchmark/models.py",
        "indexing/runner.py",
        "orchestrator/common.py",
        "orchestrator/eval.py",
        "orchestrator/workspace.py",
        "reasoning/models.py",
        "walkthrough/artifact.py",
        "walkthrough/quality.py",
        "walkthrough/runner.py",
    }
    assert not [path for path in forbidden if (root / path).exists()]


def test_non_orchestrator_core_packages_do_not_depend_on_orchestrator() -> None:
    root = Path(__file__).parents[1] / "memory_center" / "core"
    protected_packages = tuple(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "__init__.py").exists() and path.name != "orchestrator"
    )
    offenders = [
        str(path)
        for package in protected_packages
        for path in (root / package).glob("*.py")
        if _imports_package(path, "memory_center.core.orchestrator")
        or _imports_package(path, "..orchestrator")
    ]
    assert not offenders


def test_http_routes_only_depend_on_application_or_foundation() -> None:
    root = Path(__file__).parents[1] / "memory_center" / "http" / "routes"
    forbidden = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module.startswith("memory_center.core.") and not module.startswith("memory_center.core.foundation."):
                forbidden.append(f"{path}:{module}")
    assert not forbidden


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_server_delegates_runtime_and_insight_registration() -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_resume_check_has_its_own_orchestrator_module() -> None:
    from memory_center.core.orchestrator import resume_check, workspace_ops

    assert callable(resume_check.workspace_task_resume_check)
    assert "def workspace_task_resume_check" not in Path(workspace_ops.__file__).read_text(encoding="utf-8")


def test_module_boundary_adr_defines_completion_criteria() -> None:
    adr = Path(__file__).parents[1] / "docs" / "adr" / "0002-module-boundaries-and-completion.md"
    content = adr.read_text(encoding="utf-8")
    assert "本轮验收条件" in content
    assert "core 非 orchestrator 包零依赖" in content


# --- 分层依赖契约 / Layer dependency contract -------------------------------
# 依据 docs/ARCHITECTURE.md 声明的分层方向：
#   service/（生命周期、路由、MCP 边界）-> platform/（控制面、授权、任务、知识、检索）
#   -> application/ + core/（被复用的引擎）
# 以及 memory_center/core/foundation/README.md（“这是系统最低层的应用代码”）。
# ADR-0001 明确要求：新增跨层依赖必须先调整所属 Module，而不是以延迟导入规避循环。
# 因此函数内延迟导入同样计入违规，不因 duck-typing 的 import 位置而豁免。

_LAYER_ORDER = {"core": 0, "application": 1, "platform": 2, "service": 3}

# 底层数量上限：dst 的层级序号大于 src 即为反向依赖。
_LAYER_REMEDY = (
    "Step 1: 确认被依赖的能力属于哪一层（core 提供可复用引擎，application 组合跨领域用例，"
    "platform 提供控制面/授权/任务，service 只做生命周期与入口边界）。\n"
    "Step 2: 若底层确实需要该能力，把它下沉到 core 内合适的子包；若只是类型或错误，"
    "下沉到 core.foundation。不要用函数内延迟导入规避（ADR-0001 第 14 行明确禁止）。"
)

_FOUNDATION_REMEDY = (
    "Step 1: 确认被依赖的符号是否真是基础能力（共享类型、错误、Schema、纯文本与 Token 辅助）。\n"
    "Step 2: 若是，把它下移到 core.foundation 内（例如纯文本清洗归 foundation.text）；"
    "若它依赖工作区 I/O、配置加载、图查询或领域工作流，则调用方上移到 core 内更高层的子包。\n"
    "参考：memory_center/core/foundation/README.md 规定 foundation 不得承载工作区 I/O 与领域工作流。"
)

# 已存在的违规基线。键为 (相对仓库根的路径, 被导入的目标模块)。
# 该列表只允许收缩，不允许增长：修好一处即从基线移除，基线里残留的条目会让测试失败，
# 以免技术债条目变成永久豁免。
_KNOWN_LAYER_VIOLATIONS: dict[tuple[str, str], str] = {
    (
        "memory_center/core/foundation/models.py",
        "memory_center.core.workspace.kinds",
    ): "ServiceConfig.resolved_language 在函数内延迟导入 resolve_kind 规避循环，属 ADR-0001 禁止的做法。",
    (
        "memory_center/core/knowledge/wiki_promotion.py",
        "memory_center.platform.assistant.core",
    ): "为取 WikiError 在函数内延迟导入 platform，反向依赖入口侧控制面。",
    (
        "memory_center/core/knowledge/wiki_promotion.py",
        "memory_center.application.task_shadow_flow",
    ): "晋升编排依赖 application 的任务绑定决策，应把确认编排上移到 application 层。",
}


def _module_layer(module: str) -> tuple[str, str] | None:
    """返回 (顶层层名, core 子包名)；非分层模块返回 None。"""
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "memory_center" or parts[1] not in _LAYER_ORDER:
        return None
    return parts[1], (parts[2] if parts[1] == "core" and len(parts) > 2 else "")


class _ImportCollector(ast.NodeVisitor):
    """收集一个模块的所有内存内导入；区分模块级、函数内延迟与 TYPE_CHECKING。"""

    def __init__(self, module: str, is_package: bool) -> None:
        self.pkg = module if is_package else module.rsplit(".", 1)[0]
        self.found: list[tuple[str, int, str]] = []
        self._type_only = 0
        self._in_function = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._in_function += 1
        self.generic_visit(node)
        self._in_function -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        names = {sub.id for sub in ast.walk(node.test) if isinstance(sub, ast.Name)}
        names |= {sub.attr for sub in ast.walk(node.test) if isinstance(sub, ast.Attribute)}
        if "TYPE_CHECKING" in names:
            self._type_only += 1
            for child in node.body:
                self.visit(child)
            self._type_only -= 1
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def _record(self, target: str, node: ast.AST) -> None:
        kind = "type_checking" if self._type_only else ("deferred" if self._in_function else "module")
        self.found.append((target, getattr(node, "lineno", 0), kind))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            base = resolve_name("." * node.level + (node.module or ""), self.pkg)
        else:
            base = node.module or ""
        if not base:
            return
        self._record(base, node)
        for alias in node.names:
            submodule = f"{base}.{alias.name}"
            candidate = Path(*submodule.split("."))
            pkg_root = Path(__file__).parents[1]
            if (pkg_root / candidate).with_suffix(".py").exists() or (
                pkg_root / candidate / "__init__.py"
            ).exists():
                self._record(submodule, node)


def _iter_layer_violations() -> tuple[list[tuple[str, str, int, str]], list[str]]:
    """返回 (违规列表, 无法静态判定的动态导入线索)。"""
    pkg_root = Path(__file__).parents[1]
    violations: list[tuple[str, str, int, str]] = []
    dynamic: list[str] = []

    for path in sorted((pkg_root / "memory_center").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel_parts = list(path.relative_to(pkg_root).with_suffix("").parts)
        is_package = rel_parts[-1] == "__init__"
        if is_package:
            rel_parts = rel_parts[:-1]
        module = ".".join(rel_parts)

        source = _module_layer(module)
        if source is None:
            continue

        source_text = path.read_text(encoding="utf-8")
        if "import_module(" in source_text or "__import__(" in source_text:
            dynamic.append(str(path.relative_to(pkg_root)))

        tree = ast.parse(source_text, filename=str(path))
        collector = _ImportCollector(module, is_package)
        collector.visit(tree)

        for target, lineno, kind in collector.found:
            destination = _module_layer(target)
            if destination is None:
                continue
            src_top, src_sub = source
            dst_top, dst_sub = destination
            rel_path = str(path.relative_to(pkg_root))
            if _LAYER_ORDER[dst_top] > _LAYER_ORDER[src_top]:
                violations.append((rel_path, target, lineno, f"{src_top}->{dst_top} ({kind})"))
            elif src_top == dst_top == "core" and src_sub == "foundation" and dst_sub != "foundation":
                violations.append((rel_path, target, lineno, f"foundation->{dst_sub} ({kind})"))

    return violations, dynamic


def test_layer_dependency_contract() -> None:
    violations, _dynamic = _iter_layer_violations()
    actual = {(rel_path, target) for rel_path, target, _lineno, _edge in violations}

    new_offenders = sorted(actual - set(_KNOWN_LAYER_VIOLATIONS))
    stale_baseline = sorted(set(_KNOWN_LAYER_VIOLATIONS) - actual)

    details = [
        f"{rel_path}:{lineno}  {target}  [{edge}]"
        for rel_path, target, lineno, edge in violations
        if (rel_path, target) in new_offenders
    ]

    assert not new_offenders, (
        "分层依赖违规（需按下方步骤修复，而不是加入基线）：\n  "
        + "\n  ".join(details)
        + f"\n\n{_LAYER_REMEDY}\n\n{_FOUNDATION_REMEDY}"
    )
    assert not stale_baseline, (
        "以下基线条目已不再违规，请从 _KNOWN_LAYER_VIOLATIONS 中删除，保持技术债清单只减不增：\n  "
        + "\n  ".join(f"{rel_path} -> {target}" for rel_path, target in stale_baseline)
    )

