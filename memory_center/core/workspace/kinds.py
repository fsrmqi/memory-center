"""Service kind detection — filesystem probing for build markers.

服务类型探测 —— 通过构建文件标记识别目录所属的 service kind。

归属：注册表（``ServiceKindSpec`` / ``SERVICE_KIND_REGISTRY`` / ``resolve_kind``
等纯数据与查表）已下沉到 ``core.foundation.service_kinds``；本模块只保留需要读取
构建文件的探测逻辑（工作区 I/O），并再导出注册表符号，保持
``memory_center.core.workspace.kinds`` 的既有导入路径继续可用。
"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.foundation.service_kinds import (  # noqa: F401  (re-export)
    SERVICE_KIND_REGISTRY,
    ServiceKindSpec,
    is_known_kind,
    list_kind_names,
    resolve_kind,
)


def detect_kind_from_path(path: Path) -> str | None:
    """Inspect a directory and return the best-matching service kind name.

    Returns ``None`` when no marker is found (the caller decides whether
    to skip the directory or fall back to ``generic``).

    Detection rules:
    1. Each kind's ``build_markers`` are tested against the directory.
       Any match makes the kind a candidate.
    2. Spring is upgraded from ``generic-jvm`` when ``pom.xml`` mentions
       ``spring-boot-starter`` (or ``build.gradle`` does). Detection
       remains cheap — only a single file read per candidate.
    3. Among candidates, the highest ``priority`` wins.

    扫描目录,返回最匹配的 service kind 名;无标记时返回 None。
    """
    if not path.exists() or not path.is_dir():
        return None

    candidates: list[ServiceKindSpec] = []
    for spec in SERVICE_KIND_REGISTRY.values():
        if not spec.build_markers:
            continue
        if any((path / marker).exists() for marker in spec.build_markers):
            candidates.append(spec)

    if not candidates:
        return None

    # Spring upgrade: if both generic-jvm and a Spring kind match the same
    # markers, prefer the Spring kind only when the build file references
    # spring-boot-starter. Otherwise prefer generic-jvm to avoid false
    # positive Spring annotation extraction on plain JVM projects.
    has_jvm_build = any(
        (path / m).exists() for m in ("pom.xml", "build.gradle", "build.gradle.kts")
    )
    if has_jvm_build:
        spring_signal = _has_spring_signal(path)
        if not spring_signal:
            candidates = [c for c in candidates if not c.spring_aware]
            # If filtering removed everything, fall back to generic-jvm.
            if not candidates:
                return "generic-jvm"
        else:
            # Spring detected. Gateway is a narrower kind than the generic
            # Spring Boot service — only keep it when the build file
            # explicitly pulls in spring-cloud-starter-gateway. This avoids
            # mis-detecting every Spring Boot app as a gateway just because
            # gateway has the highest priority in the registry.
            if not _has_gateway_signal(path):
                candidates = [c for c in candidates if c.name != "spring-cloud-gateway"]

    # Highest priority wins; ties resolved by registration order.
    candidates.sort(key=lambda spec: -spec.priority)
    return candidates[0].name


def _has_spring_signal(path: Path) -> bool:
    """Cheap check for Spring Boot in a build file.

    Reads at most the first 16 KB of each known build file. Avoids parsing
    XML/Groovy/Kotlin DSL — we just look for the ``spring-boot`` substring,
    which is good enough for kind detection (false positives are harmless
    because they only flip ``spring_aware``, not the language).
    """
    for marker in ("pom.xml", "build.gradle", "build.gradle.kts"):
        build_file = path / marker
        if not build_file.exists():
            continue
        try:
            head = build_file.read_text(encoding="utf-8", errors="ignore")[:16384]
        except OSError:
            continue
        if "spring-boot" in head or "org.springframework.boot" in head:
            return True
    return False


def _has_gateway_signal(path: Path) -> bool:
    """True iff a build file mentions ``spring-cloud-starter-gateway``.

    Same cheap read as ``_has_spring_signal``. Used to disambiguate the
    high-priority ``spring-cloud-gateway`` kind from generic Spring Boot
    apps that happen to share the same build markers.
    """
    for marker in ("pom.xml", "build.gradle", "build.gradle.kts"):
        build_file = path / marker
        if not build_file.exists():
            continue
        try:
            head = build_file.read_text(encoding="utf-8", errors="ignore")[:16384]
        except OSError:
            continue
        if "spring-cloud-starter-gateway" in head:
            return True
    return False


__all__ = [
    "ServiceKindSpec",
    "SERVICE_KIND_REGISTRY",
    "resolve_kind",
    "is_known_kind",
    "list_kind_names",
    "detect_kind_from_path",
]
