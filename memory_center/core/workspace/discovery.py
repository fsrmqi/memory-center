"""5.0 源码只读预览：有界扫描，不读取旧配置、不执行构建。"""
import os
from pathlib import Path

from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.workspace.kinds import SERVICE_KIND_REGISTRY

_SKIP = {"node_modules", "target", "build", "dist", "out", "venv", "__pycache__",
         "src", "test", "tests", "docs", "vendor"}
_MAX_ENTRIES = 2048
_MAX_SERVICES = 64
_SCAN_DEPTH = 2


def canonical_root(raw: str, data_dir: Path) -> Path:
    try:
        path = Path(raw).expanduser()
    except (ValueError, RuntimeError) as exc:
        raise CatalogError("ROOT_INVALID", "源码路径格式无效") from exc
    if not path.is_absolute():
        raise CatalogError("ROOT_NOT_ABSOLUTE", "请使用服务端可访问的绝对源码路径")
    try:
        root = path.resolve(strict=True)
        if not root.is_dir():
            raise CatalogError("ROOT_NOT_DIRECTORY", "源码路径必须是目录")
        if not os.access(root, os.R_OK | os.X_OK):
            raise CatalogError("ROOT_NOT_READABLE", "服务无法读取源码目录")
    except ValueError as exc:
        raise CatalogError("ROOT_INVALID", "源码路径格式无效") from exc
    except FileNotFoundError as exc:
        raise CatalogError("ROOT_NOT_FOUND", "源码目录不存在") from exc
    except (OSError, RuntimeError) as exc:
        raise CatalogError("ROOT_NOT_READABLE", "服务无法解析或读取源码目录") from exc
    service_root = data_dir.resolve()
    if root.is_relative_to(service_root) or service_root.is_relative_to(root):
        raise CatalogError("ROOT_DATA_OVERLAP", "源码目录不能包含服务数据目录，也不能位于其中")
    return root


def _kind(path: Path) -> str | None:
    candidates = [spec for spec in SERVICE_KIND_REGISTRY.values()
                  if any((path / marker).is_file() and not (path / marker).is_symlink()
                         for marker in spec.build_markers)]
    if not candidates:
        return None
    signals = ""
    for marker in ("pom.xml", "build.gradle", "build.gradle.kts"):
        build = path / marker
        if build.is_file() and not build.is_symlink():
            with build.open(encoding="utf-8", errors="ignore") as handle:
                signals += handle.read(16384)
    if "spring-boot" not in signals:
        candidates = [spec for spec in candidates if not spec.spring_aware]
    elif "spring-cloud-starter-gateway" not in signals:
        candidates = [spec for spec in candidates if spec.name != "spring-cloud-gateway"]
    return max(candidates, key=lambda spec: spec.priority).name if candidates else "generic-jvm"


def preview_sources(root: Path) -> dict:
    candidates = []
    remaining = _MAX_ENTRIES
    warnings = set()
    complete = True
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        try:
            kind = _kind(directory)
            if kind:
                relative = directory.relative_to(root).as_posix()
                candidates.append({"name": root.name if relative == "." else relative.replace("/", "-"),
                                   "path": relative, "type": kind})
                if len(candidates) > _MAX_SERVICES:
                    candidates = candidates[:_MAX_SERVICES]
                    complete = False
                    warnings.add("service_limit")
                    break
            if depth == _SCAN_DEPTH:
                continue
            children = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    remaining -= 1
                    if remaining < 0:
                        complete = False
                        warnings.add("entry_limit")
                        break
                    if entry.name.startswith(".") or entry.name in _SKIP:
                        continue
                    if entry.is_symlink():
                        warnings.add("symlinks_skipped")
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        children.append(Path(entry.path))
            if not complete:
                break
            pending.extend((child, depth + 1) for child in sorted(children, reverse=True))
        except OSError:
            complete = False
            warnings.add("unreadable_directory")
            break
    if not candidates and complete:
        candidates = [{"name": root.name, "path": ".", "type": "generic"}]
        warnings.add("generic_fallback")
    candidates.sort(key=lambda service: service["path"])
    for service in candidates:
        path = Path(service["path"])
        service["exclude_paths"] = [other["path"] for other in candidates
                                   if other is not service and Path(other["path"]).is_relative_to(path)]
    return {"root": str(root), "suggested_name": root.name, "services": candidates,
            "scan": {"depth": _SCAN_DEPTH, "entry_limit": _MAX_ENTRIES,
                     "complete": complete, "warnings": sorted(warnings)}}
