"""Service kind registry — declares how each service type maps to language,
build markers, source layout, and indexer behaviors.

This module is the single source of truth for "what kinds of services
memory-center understands". Adding a new kind only requires registering a
ServiceKindSpec here; the rest of the system queries this registry instead
of hard-coding Spring/Java assumptions.

服务类型注册表 —— 声明每种 service type 对应的语言、构建标记、源码布局和索引器行为。
新增类型只需在此注册 ServiceKindSpec,其他模块从注册表查询,避免硬编码 Spring/Java 假设。

归属：注册表本身是纯数据与纯函数，属于基础层（共享类型 + 常量 + 查表）。
目录探测 ``detect_kind_from_path`` 需要读取构建文件，属于工作区 I/O，
保留在 ``core.workspace.kinds``，并从本模块取注册表。

此前 ``ServiceConfig.resolved_language`` 需要延迟导入 ``core.workspace.kinds``
才能拿到 ``resolve_kind``，构成 foundation 反向依赖 workspace；拆分后该依赖消失。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceKindSpec:
    """One entry in the service kind registry.

    Attributes:
        name: Canonical kind name (e.g. ``"spring-boot-service"``).
        language: Primary language identifier or ``None`` for protocol/generic.
        build_markers: Files whose presence in a directory strongly implies
            this kind. Ordering matters only for documentation — detection
            picks the most specific kind via priority instead.
        source_dirs: Conventional source subdirectories (used by future
            indexer routing). Defaults to ``("src",)``.
        spring_aware: When True, indexer enables Spring-specific extractors
            (annotations, Bean injection, Feign, MQ). When False, only the
            generic structural parser runs.
        priority: Higher value wins when multiple kinds match the same
            directory. Spring is highest because ``pom.xml`` + Spring
            parent is a stronger signal than just ``pom.xml``.
        description_zh / description_en: Human-readable description, used
            by ``memory-center status`` / ``doctor`` for diagnostics.
    """

    name: str
    language: str | None
    build_markers: tuple[str, ...]
    source_dirs: tuple[str, ...] = ("src",)
    spring_aware: bool = False
    priority: int = 10
    description_zh: str = ""
    description_en: str = ""


# ── Registry ────────────────────────────────────────────────────────────────
# Order is for documentation only. ``detect_kind_from_path`` ranks by priority.

SERVICE_KIND_REGISTRY: dict[str, ServiceKindSpec] = {
    # ── Spring family (priority 90~100, beat plain JVM) ────────────────────
    "spring-cloud-gateway": ServiceKindSpec(
        name="spring-cloud-gateway",
        language="java",
        build_markers=("pom.xml", "build.gradle", "build.gradle.kts"),
        spring_aware=True,
        priority=100,
        description_zh="Spring Cloud Gateway 网关",
        description_en="Spring Cloud Gateway",
    ),
    "spring-boot-service": ServiceKindSpec(
        name="spring-boot-service",
        language="java",
        build_markers=("pom.xml", "build.gradle", "build.gradle.kts"),
        spring_aware=True,
        priority=90,
        description_zh="Spring Boot 应用",
        description_en="Spring Boot application",
    ),
    "spring-boot-task": ServiceKindSpec(
        name="spring-boot-task",
        language="java",
        build_markers=("pom.xml", "build.gradle"),
        spring_aware=True,
        priority=90,
        description_zh="Spring Boot 任务调度服务",
        description_en="Spring Boot batch/task service",
    ),
    "shared-library": ServiceKindSpec(
        name="shared-library",
        language="java",
        build_markers=("pom.xml", "build.gradle"),
        spring_aware=True,
        priority=80,
        description_zh="共享库 / API 契约模块",
        description_en="Shared Java library / API contract module",
    ),
    # ── Generic JVM (priority 50) ──────────────────────────────────────────
    "generic-jvm": ServiceKindSpec(
        name="generic-jvm",
        language="java",
        build_markers=("pom.xml", "build.gradle", "build.gradle.kts"),
        spring_aware=False,
        priority=50,
        description_zh="通用 JVM 项目(非 Spring)",
        description_en="Generic JVM project (non-Spring)",
    ),
    "kotlin-module": ServiceKindSpec(
        name="kotlin-module",
        language="kotlin",
        build_markers=("build.gradle.kts", "settings.gradle.kts"),
        spring_aware=False,
        priority=55,
        description_zh="Kotlin 模块",
        description_en="Kotlin module",
    ),
    # ── Other ecosystems (priority 40~70) ──────────────────────────────────
    "python-package": ServiceKindSpec(
        name="python-package",
        language="python",
        build_markers=("pyproject.toml", "setup.py", "setup.cfg"),
        priority=70,
        description_zh="Python 包 / 项目",
        description_en="Python package",
    ),
    "node-app": ServiceKindSpec(
        name="node-app",
        language="typescript",
        build_markers=("package.json",),
        priority=60,
        description_zh="Node.js / TypeScript 应用",
        description_en="Node.js / TypeScript application",
    ),
    "go-module": ServiceKindSpec(
        name="go-module",
        language="go",
        build_markers=("go.mod",),
        priority=70,
        description_zh="Go 模块",
        description_en="Go module",
    ),
    "rust-crate": ServiceKindSpec(
        name="rust-crate",
        language="rust",
        build_markers=("Cargo.toml",),
        priority=70,
        description_zh="Rust crate",
        description_en="Rust crate",
    ),
    # ── Fallback (priority 0) ──────────────────────────────────────────────
    "generic": ServiceKindSpec(
        name="generic",
        language=None,
        build_markers=(),
        source_dirs=(".",),
        priority=0,
        description_zh="未识别类型 / 通用目录",
        description_en="Unknown or generic directory",
    ),
}


# ── Public helpers ──────────────────────────────────────────────────────────


def resolve_kind(type_name: str | None) -> ServiceKindSpec:
    """Return the spec for ``type_name``, falling back to ``generic``.

    Unknown types resolve to ``generic`` silently — callers that want to
    distinguish "known" from "fell back" should compare ``spec.name`` to
    ``type_name`` themselves.
    """
    if not type_name:
        return SERVICE_KIND_REGISTRY["generic"]
    return SERVICE_KIND_REGISTRY.get(type_name, SERVICE_KIND_REGISTRY["generic"])


def is_known_kind(type_name: str | None) -> bool:
    """True iff ``type_name`` is registered (not the silent fallback)."""
    return bool(type_name) and type_name in SERVICE_KIND_REGISTRY


def list_kind_names() -> list[str]:
    """All registered kind names, in stable order."""
    return list(SERVICE_KIND_REGISTRY.keys())


__all__ = [
    "ServiceKindSpec",
    "SERVICE_KIND_REGISTRY",
    "resolve_kind",
    "is_known_kind",
    "list_kind_names",
]
