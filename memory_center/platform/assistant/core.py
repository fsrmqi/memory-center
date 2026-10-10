"""Personal Assistant Wiki MCP 核心逻辑层。

把 Personal Assistant Wiki（personal-assistant-wiki 长期知识与治理层）的规则封装成可复用的纯函数：
  lookup   — 查：走增量全文索引，返回证据路径 + 摘要
  brief    — 备：为具体任务组装最小上下文包
  read     — 读：安全读取 wiki 内文本，支持分页续读
  archive  — 存：按目录约定预检/确认归档 + 登记索引
  promote  — 记：把已确认、可复用的结论晋升为长期知识
  validate — 校验：索引断链 + 正文 phantom 引用 + 受治理文档契约
  clean    — 清：扫描编译垃圾出报告（只报告不删除，删除留给客户端确认后执行）

红线约定（写死在代码里，客户端无需提醒）：
  1. 收件箱/ 只增不改 —— promote/archive 永不写收件箱
  2. 删除走废纸篓 —— clean 只扫描，不删除
  3. L1 凭据不入库 —— archive 执行源白名单与敏感文件拦截
  4. 文档归档物理复制 —— archive 不创建可能在未来漂移为源码入口的目录链接
  5. 不钻符号链接目录 —— 遍历一律 followlinks=False（外部大型资料仅登记路径）
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
from datetime import date, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from memory_center.platform.assistant import indexer

# 公司清单从模块注册表读取，避免注册表与代码双重维护。
CATEGORIES = ("项目资料", "公司研究")

TEXT_EXTENSIONS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv",
    ".xml", ".html", ".htm", ".ini", ".conf",
}
MAX_READ_FILE_BYTES = 5 * 1024 * 1024
MAX_READ_CHARS = 20_000
SENSITIVE_FILE_NAMES = {
    ".env", "credentials", "credentials.json", "id_rsa", "id_ed25519",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
DISALLOWED_KNOWLEDGE_SUFFIXES = {
    ".java", ".class", ".jar", ".war", ".ear", ".py", ".pyc", ".js", ".ts", ".tsx", ".jsx",
    ".jsp", ".sh", ".zsh", ".sql", ".dll", ".exe", ".msi", ".cab", ".zip", ".rar", ".7z",
    ".tar", ".gz",
}
DISALLOWED_KNOWLEDGE_NAMES = {"pom.xml", "package.json", "pyproject.toml", "setup.py"}
ALLOWED_ARCHIVE_SUFFIXES = {
    ".md", ".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".tsv", ".html", ".htm", ".rtf", ".mht", ".xmind", ".bpmn", ".pdm",
    ".vsd", ".mpp", ".pos", ".png", ".jpg", ".jpeg", ".gif", ".svg",
}
ARCHIVE_JUNK_NAMES = {".ds_store", "thumbs.db"}
MAX_ARCHIVE_FILES = 5_000
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
KNOWLEDGE_TYPES = {"事实", "决策", "规则", "验证结果", "风险", "下一步"}
COMPANY_MODULE_ALIASES = {"website", "media", "newmedia", "ucap"}
COMPANY_MODULE_ALIAS_TARGET = "kaipuyun"
COMPANY_MODULE_ALIAS_UNTIL = date(2026, 12, 31)
SENSITIVE_CONTENT_RULES = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api_token", re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("credential_assignment", re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s]{8,}")),
)
SENSITIVE_CONTENT_PATTERNS = tuple(pattern for _, pattern in SENSITIVE_CONTENT_RULES)
REQUIRED_FRONTMATTER_FIELDS = (
    "title", "module", "owner", "created", "updated", "version", "status",
)
REQUIRED_GOVERNANCE_PATHS = ("助手规则/最高宪法.md",)
DOCUMENT_STATUSES = {"草稿", "生效", "归档", "待确认"}
EXPECTED_TOP_LEVEL_DIRS = (
    "个人档案", "工作", "研究", "技术", "方法", "助手能力", "收件箱", "知识沉淀", "助手规则", "模板",
)

_INDEX_NAME = "索引.md"
_AUTO_INDEX_LOCK = threading.Lock()


class WikiError(Exception):
    """wiki 操作业务异常（会原样透传给 MCP 客户端）。"""


def _resolve(root: Path) -> Path:
    return root.expanduser().resolve()


def _safe_join(root: Path, *parts: str) -> Path:
    """目标路径必须落在 wiki 根内，防止工具被当作任意文件读写通道。"""
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root):
        raise WikiError(f"路径越界：{target} 不在 wiki 根 {root} 内")
    return target


def _registered_companies(root: Path) -> tuple[str, ...]:
    """从模块注册表的公司目录列提取公司名。"""
    registry = root / "模块注册表.md"
    if not registry.is_file():
        raise WikiError("缺少 模块注册表.md，无法确定合法公司目录")
    text = registry.read_text(encoding="utf-8", errors="replace")
    companies = sorted(set(re.findall(r"`工作/([^/`]+)/`", text)))
    if not companies:
        raise WikiError("模块注册表.md 未登记任何公司目录")
    return tuple(companies)


def _registered_modules(root: Path) -> set[str]:
    """从模块注册表第一列提取 module 短码。"""
    registry = root / "模块注册表.md"
    if not registry.is_file():
        return set()
    text = registry.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"^\|\s*`([^`]+)`\s*\|", text, re.MULTILINE))


def _append_text(path: Path, text: str) -> None:
    """带进程锁的真实追加写，避免并发调用覆盖既有内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.expanduser().resolve()) for root in roots)


def _sensitive_name(path: Path) -> bool:
    name = path.name.lower()
    return name in SENSITIVE_FILE_NAMES or name.endswith(SENSITIVE_SUFFIXES)


def _find_sensitive_path(source: Path) -> Path | None:
    """拒绝把常见明文凭据文件归档或链接进 wiki。"""
    if _sensitive_name(source) or any(part.lower() == ".ssh" for part in source.parts):
        return source
    if not source.is_dir():
        return None
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for name in dirnames + filenames:
            candidate = Path(dirpath) / name
            if _sensitive_name(candidate) or name.lower() == ".ssh":
                return candidate
    return None


def _archive_inventory(source: Path) -> tuple[list[Path], int]:
    """列出真实归档文件并计算总大小；垃圾文件不归档，符号链接由上层拒绝。"""
    files = [source] if source.is_file() else [p for p in source.rglob("*") if p.is_file() and not p.is_symlink()]
    files = [p for p in files if p.name.lower() not in ARCHIVE_JUNK_NAMES]
    return files, sum(p.stat().st_size for p in files)


def _find_sensitive_content(files: list[Path]) -> Path | None:
    """对可读文本做轻量凭据特征扫描，避免常见密钥混入长期知识。"""
    readable = {".md", ".txt", ".csv", ".tsv", ".html", ".htm", ".rtf", ".mht"}
    for path in files:
        if path.suffix.lower() not in readable or path.stat().st_size > MAX_READ_FILE_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if sensitive_text_reason(text):
            return path
    return None


def sensitive_text_reason(text: str) -> str | None:
    """返回正文命中的凭据类别，不返回原始值，避免错误信息二次泄漏。"""
    for reason, pattern in SENSITIVE_CONTENT_RULES:
        if pattern.search(text):
            return reason
    return None


def _scope_prefix(root: Path, scope: str) -> str:
    if not scope:
        return ""
    domain_map = {
        "工作": "工作",
        "研究": "研究",
        "技术": "技术",
        "个人档案": "个人档案",
        "方法": "方法",
        "助手能力": "助手能力",
        "知识沉淀": "知识沉淀",
    }
    if scope in domain_map:
        return domain_map[scope]
    companies = _registered_companies(root)
    if scope in companies:
        return f"工作/{scope}"
    if scope in _registered_modules(root):
        marker = f"module: {scope}"
        for project in list(root.glob("工作/*/项目/*.md")) + list(root.glob("技术/项目/*.md")):
            if marker in project.read_text(encoding="utf-8", errors="replace"):
                return str(project.parent.relative_to(root))
    valid = tuple(domain_map) + companies + tuple(sorted(_registered_modules(root)))
    raise WikiError(f"scope 未登记：{scope}；可选领域、公司或 module：{valid}")


def _path_has_symlink(root: Path, relative_path: Path) -> bool:
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _walk_md(root: Path, skip_dirs: tuple[str, ...] = ()) -> list[Path]:
    """遍历 wiki 下所有 .md，不跟随符号链接、可跳过指定目录。"""
    hits: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # 就地过滤子目录（os.walk 会按修改后的 dirnames 继续下钻）
        keep: list[str] = []
        for d in dirnames:
            if d in skip_dirs or d.startswith("."):
                continue
            p = Path(dirpath) / d
            if p.is_symlink():  # 符号链接目录不钻
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            if f.endswith(".md"):
                hits.append(Path(dirpath) / f)
    return hits


def _title_of(path: Path) -> str:
    """取文档首个标题行（H1/H2）作摘要。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("# "):
                    return line.lstrip("# ").strip()[:80]
                if line.startswith("## "):
                    return line.lstrip("# ").strip()[:80]
    except OSError:
        pass
    return ""


def _rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root))


# =====================================================================
# assistant_knowledge/search — 查
# =====================================================================

def _refresh_index(root: Path) -> dict[str, Any] | None:
    """查询增量刷新；大型迁入任务进行中返回已发布索引与明确状态。"""
    try:
        job = root.parent / "index-job.json"
        if job.exists() and json.loads(job.read_text()).get("state") in {"queued", "running"}:
            return {"status": "indexing", "negative_claim_allowed": False, "stats": indexer.index_stats(root)}
        with _AUTO_INDEX_LOCK:
            exists = indexer.index_stats(root)["exists"]
            return {"mode": "incremental" if exists else "initial", "build": indexer.build_index(root)}
    except (OSError, sqlite3.Error) as exc:
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:300]}

def lookup(root: Path, query: str, scope: str = "", limit: int = 10, _refresh: bool = True) -> dict[str, Any]:
    """优先查询自动增量刷新的全文索引；索引不可用时回退 Markdown 轻量检索。"""
    root = _resolve(root)
    query = (query or "").strip()
    if not query:
        raise WikiError("query 不能为空")
    if not 1 <= limit <= 100:
        raise WikiError("limit 需在 1 到 100 之间")
    scope_prefix = _scope_prefix(root, scope)
    refresh = _refresh_index(root) if _refresh else None
    indexed = indexer.search_index(root, query, limit=limit, scope_prefix=scope_prefix)
    if indexed is not None:
        return {
            "query": query,
            "scope": scope or "全部知识",
            "index": indexed["cache"],
            "hits": indexed["hits"],
            "total_hits": len(indexed["hits"]),
            "index_refresh": refresh,
            "hint": "结果来自自动初始化、后台增量刷新的全文索引；snippet 中方括号标出命中片段",
        }

    ql = query.lower()

    # 回退检索跳过大型项目资料树；完整内容由增量全文索引提供。
    skip = ("docs_crms", "workspaces2016", "项目资料", "收件箱", ".workbuddy", ".git", ".obsidian")
    docs: list[dict[str, Any]] = []
    for p in _walk_md(root, skip_dirs=skip):
        title = _title_of(p)
        rel = _rel(root, p)
        if scope_prefix and not (rel == scope_prefix or rel.startswith(scope_prefix.rstrip("/") + "/")):
            continue
        score = 0
        name = p.name.lower()
        if ql in name:
            score += 5
        if ql in title.lower():
            score += 3
        # 正文开头 30 行关键词命中（索引表格/文档导语是主要来源）
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                head = "".join(islice(fh, 30)).lower()
            if ql in head:
                score += 2
        except OSError:
            pass
        if score > 0:
            docs.append({"path": rel, "title": title or p.stem, "score": score})

    # --- 第二层：项目资料目录结构（scope 命中时）---
    dir_hits: list[dict[str, Any]] = []
    if scope and scope in _registered_companies(root):
        scope_dir = _safe_join(root, "工作", scope, "项目资料")
        if scope_dir.is_dir():
            for dirpath, dirnames, filenames in os.walk(scope_dir, followlinks=False):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in dirnames + filenames:
                    if ql in name.lower():
                        dir_hits.append(
                            {"path": _rel(root, Path(dirpath) / name), "title": name, "score": 1}
                        )

    docs.sort(key=lambda d: -d["score"])
    dir_hits.sort(key=lambda d: d["path"])
    return {
        "query": query,
        "scope": scope or "全部（知识层）",
        "doc_hits": docs[:limit],
        "dir_hits": dir_hits[:limit],
        "total_doc_hits": len(docs),
        "total_dir_hits": len(dir_hits),
        "index_refresh": refresh,
        "hint": "全文索引暂不可用，当前仅搜索 Markdown 和限定公司文件名",
    }


def brief(root: Path, task: str, scope: str = "", limit: int = 12) -> dict[str, Any]:
    """为具体任务返回按职责分组的最小证据包，交由调用端模型综合判断。"""
    task = (task or "").strip()
    if not task:
        raise WikiError("task 不能为空")
    result = lookup(root, task, scope=scope, limit=limit)
    raw_hits = result.get("hits") or result.get("doc_hits", [])
    if len(raw_hits) < min(3, limit):
        combined = {hit.get("path", ""): hit for hit in raw_hits}
        terms = [term for term in re.split(r"[\s,，。；;：:、/]+", task) if len(term) >= 2]
        for term in terms:
            partial = lookup(root, term, scope=scope, limit=limit, _refresh=False)
            for hit in partial.get("hits") or partial.get("doc_hits", []):
                combined.setdefault(hit.get("path", ""), hit)
                if len(combined) >= limit:
                    break
        raw_hits = list(combined.values())[:limit]
    groups: dict[str, list[dict[str, Any]]] = {
        "user_context": [], "projects": [], "methods": [], "business": [], "other": [],
    }
    for hit in raw_hits:
        path = hit.get("path", "")
        if path.startswith("个人档案/"):
            group = "user_context"
        elif "/项目/" in path:
            group = "projects"
        elif path.startswith(("方法/", "助手能力/")):
            group = "methods"
        elif path.startswith(("工作/", "研究/", "技术/")):
            group = "business"
        else:
            group = "other"
        groups[group].append(hit)
    return {
        "task": task,
        "scope": scope or "全部知识",
        "context": groups,
        "source_count": sum(len(items) for items in groups.values()),
        "assistant_protocol": [
            "区分事实、推断、偏好和未决项",
            "代码事实与调用链交给 Memory Center 复核",
            "仅在产生确认且可复用增量时晋升长期知识",
            "task 描述应来自 Memory Center 当前绑定任务或 Shadow intent；无可信锚点时本结果仅作背景浏览，不得作为当前任务知识",
        ],
        "index_hint": result.get("hint", ""),
    }


# =====================================================================
# assistant_knowledge/read — 读
# =====================================================================

def read(
    root: Path,
    path: str,
    start_line: int = 1,
    max_chars: int = 12_000,
) -> dict[str, Any]:
    """安全读取 wiki 内的文本文件；不允许路径越界或经过符号链接。"""
    root = _resolve(root)
    cleaned_path = (path or "").strip()
    raw_path = Path(cleaned_path)
    if not cleaned_path or raw_path.is_absolute():
        raise WikiError("path 需为 wiki 根目录下的相对路径")
    if _path_has_symlink(root, raw_path):
        raise WikiError("禁止读取符号链接或其下内容")
    target = _safe_join(root, *raw_path.parts)
    if not target.is_file():
        raise WikiError(f"文件不存在：{path}")
    if start_line < 1:
        raise WikiError("start_line 必须大于等于 1")
    max_chars = min(max(1, max_chars), MAX_READ_CHARS)

    extractor = "text"
    indexed = False
    if target.suffix.lower() in TEXT_EXTENSIONS:
        size = target.stat().st_size
        if size > MAX_READ_FILE_BYTES:
            raise WikiError(f"文件过大：{size} bytes，单文件上限 {MAX_READ_FILE_BYTES} bytes")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    else:
        entry = indexer.read_indexed(root, _rel(root, target))
        if not entry:
            _refresh_index(root)
            entry = indexer.read_indexed(root, _rel(root, target))
        if not entry:
            raise WikiError("该文档尚无可读索引，且自动增量索引未能生成正文")
        if not entry["content"]:
            detail = entry["error"] or f"{target.suffix or '[无扩展名]'} 当前只支持文件名索引"
            raise WikiError(f"该文档没有可提取正文：{detail}")
        lines = entry["content"].splitlines(keepends=True)
        extractor = entry["extractor"]
        indexed = True

    selected: list[str] = []
    used = 0
    next_line: int | None = None
    last_line = start_line - 1
    for number, line in enumerate(lines, start=1):
        if number < start_line:
            continue
        if used + len(line) > max_chars:
            next_line = number
            break
        selected.append(line)
        used += len(line)
        last_line = number

    return {
        "path": _rel(root, target),
        "start_line": start_line,
        "end_line": last_line,
        "next_start_line": next_line,
        "truncated": next_line is not None,
        "content": "".join(selected),
        "extractor": extractor,
        "from_index": indexed,
    }


# =====================================================================
# assistant_memory/archive — 存
# =====================================================================

def archive(
    root: Path,
    source_path: str,
    destination: str = "",
    company: str = "",
    category: str = "项目资料",
    confirm: bool = False,
    allowed_source_roots: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """把文件/目录归档进 wiki，并登记索引。

    规则：
      - destination 显式指定工作/研究/技术下目标目录；或由 company + category 决定公司位置
      - 目标已存在 → 报错不覆盖
      - 只允许明确的文档、表格、演示、图像和流程图类型
      - 单次最多 5000 文件 / 500MB，大型资料只登记路径
      - 不创建目录符号链接，避免外部目录后续加入源码时绕过边界
      - 登记：在目标 索引.md 的「归档记录」小节追加一行
      - confirm=False 时只返回预检结果，不执行写入
    """
    root = _resolve(root)
    raw_src = Path(source_path).expanduser()
    if raw_src.is_symlink():
        raise WikiError("归档源不能是符号链接；请提供真实文档路径或只在项目卡中登记外部路径")
    src = raw_src.resolve()
    if not src.exists():
        raise WikiError(f"源不存在：{src}")
    if not allowed_source_roots:
        raise WikiError("未配置允许归档的源目录；请通过 --allowed-source-root 显式授权")
    if not _is_within(src, allowed_source_roots):
        allowed = ", ".join(str(p.expanduser().resolve()) for p in allowed_source_roots)
        raise WikiError(f"源路径未获授权：{src}；允许范围：{allowed}")
    sensitive = _find_sensitive_path(src)
    if sensitive:
        raise WikiError(f"检测到疑似 L1 凭据文件，禁止归档：{sensitive}")
    if src.is_dir():
        linked = next((p for p in src.rglob("*") if p.is_symlink()), None)
        if linked:
            raise WikiError(f"归档目录包含符号链接，禁止导入：{linked}；请改为文档路径引用")
    candidates, total_bytes = _archive_inventory(src)
    if not candidates:
        raise WikiError("归档源没有可归档文档")
    if len(candidates) > MAX_ARCHIVE_FILES or total_bytes > MAX_ARCHIVE_BYTES:
        raise WikiError(
            f"归档规模超限：{len(candidates)} 文件 / {total_bytes} bytes；"
            f"上限 {MAX_ARCHIVE_FILES} 文件 / {MAX_ARCHIVE_BYTES} bytes，请只在项目卡登记外部路径"
        )
    for candidate in candidates:
        suffix = candidate.suffix.lower()
        if candidate.name.lower() in DISALLOWED_KNOWLEDGE_NAMES or suffix not in ALLOWED_ARCHIVE_SUFFIXES:
            raise WikiError(
                f"知识库只接收白名单内文档，检测到不允许的类型：{candidate}；"
                "请留在独立工程、Memory Center workspace 或 legacy-project-archives"
            )
    sensitive_content = _find_sensitive_content(candidates)
    if sensitive_content:
        raise WikiError(f"检测到疑似 L1 凭据内容，禁止归档：{sensitive_content}")

    if destination:
        relative = Path(destination.strip())
        allowed_destinations = {"工作", "研究", "技术"}
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] not in allowed_destinations:
            raise WikiError("destination 必须是 工作/、研究/ 或 技术/ 下不含 .. 的知识库相对目录")
        if _path_has_symlink(root, relative):
            raise WikiError("destination 不能经过符号链接")
        target_dir = _safe_join(root, *relative.parts)
    elif company:
        companies = _registered_companies(root)
        if company not in companies:
            raise WikiError(f"company 需为 模块注册表.md 已登记公司之一：{companies}")
        if category not in CATEGORIES:
            raise WikiError(f"category 需为 {CATEGORIES} 之一")
        target_dir = _safe_join(root, "工作", company, category)
    else:
        raise WikiError("必须显式提供 destination，或提供 company + category；不再默认归入个人项目")

    target = target_dir / src.name

    if target.exists() or target.is_symlink():
        raise WikiError(f"目标已存在（不覆盖）：{_rel(root, target)}")

    preview = {
        "source": str(src),
        "target": _rel(root, target),
        "mode": "copy",
        "file_count": len(candidates),
        "total_bytes": total_bytes,
        "confirmed": confirm,
    }
    if not confirm:
        return {
            **preview,
            "status": "需要确认",
            "note": "预检通过；确认源与目标无误后，以 confirm=true 再次调用",
        }

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        if src.is_dir():
            shutil.copytree(src, target, symlinks=False, ignore=shutil.ignore_patterns(".DS_Store", "Thumbs.db", "__MACOSX"))
        else:
            shutil.copy2(src, target)
    except OSError as exc:
        raise WikiError(f"复制失败：{exc}") from exc
    mode = "copy"

    try:
        # 登记索引（带锁追加，不改写既有内容）
        index_path = target_dir / _INDEX_NAME
        record = (
            f"- {datetime.now():%Y-%m-%d} 归档 `{src.name}` → `{_rel(root, target)}`（{mode}）"
        )
        if index_path.exists():
            text = index_path.read_text(encoding="utf-8")
            if "## 归档记录" in text:
                _append_text(index_path, record + "\n")
                index_note = "已追加到归档记录"
            else:
                _append_text(index_path, "\n## 归档记录\n\n" + record + "\n")
                index_note = "已新建归档记录小节"
        else:
            today = date.today().isoformat()
            title = f"{company or '个人项目'}归档索引"
            _append_text(
                index_path,
                "---\n"
                f"title: {title}\n"
                "module: system\n"
                "owner: 管理员\n"
                f"created: {today}\n"
                f"updated: {today}\n"
                "version: v1.0\n"
                "status: 生效\n"
                "tags: [索引, 归档]\n"
                "related: [模块注册表.md]\n"
                "---\n\n"
                f"# {company or '个人项目'} — 索引\n\n## 归档记录\n\n{record}\n",
            )
            index_note = "索引不存在，已新建"
    except OSError as exc:
        # 目标是本次刚创建的，索引失败时回滚，避免半完成归档。
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as rollback_exc:
            raise WikiError(f"索引登记失败且目标回滚失败：{exc}；{rollback_exc}") from exc
        raise WikiError(f"索引登记失败，已回滚归档目标：{exc}") from exc

    return {
        "source": str(src),
        "target": _rel(root, target),
        "mode": mode,
        "file_count": len(candidates),
        "total_bytes": total_bytes,
        "confirmed": True,
        "index_update": index_note,
        "note": "已物理复制文档型资料；源码与大型外部资料请只登记路径",
    }


# =====================================================================
# assistant_memory/promote — 记
# =====================================================================

def promote(
    root: Path,
    title: str,
    content: str,
    source: str,
    knowledge_type: str = "事实",
    module: str = "system",
    source_refs: list[str] | None = None,
    confirm: bool = False,
    task_id: str = "",
) -> dict[str, Any]:
    """把已确认且可复用的增量晋升为受治理长期知识；默认仅预检。

    ``task_id`` 是可选的 Memory Center 任务锚点（Session-first 约定）：传入时
    会写入 frontmatter ``task_id`` 与返回 metadata，供反向追溯；不参与内容哈希
    以外的任何检索或焦点判定。
    """
    root = _resolve(root)
    title = (title or "").strip()
    content = (content or "").strip()
    source = (source or "").strip()
    requested_module = (module or "").strip()
    module_routing: dict[str, str] | None = None
    if date.today() <= COMPANY_MODULE_ALIAS_UNTIL and requested_module.lower() in COMPANY_MODULE_ALIASES:
        module = COMPANY_MODULE_ALIAS_TARGET
        module_routing = {
            "requested": requested_module,
            "resolved": module,
            "reason": "company_module_alias",
            "valid_until": COMPANY_MODULE_ALIAS_UNTIL.isoformat(),
        }
    else:
        module = requested_module
    if not title or not content or not source:
        raise WikiError("title、content、source 均不能为空")
    if knowledge_type not in KNOWLEDGE_TYPES:
        raise WikiError(f"knowledge_type 需为 {tuple(sorted(KNOWLEDGE_TYPES))} 之一")
    if module not in _registered_modules(root):
        fallback = ""
        if date.today() <= date(2026, 12, 31):
            fallback = "；若明显属于开普云公司业务但项目不明确，可改用 kaipuyun，个人事项禁止使用此兜底（有效至 2026-12-31）"
        raise WikiError(f"module 未在 模块注册表.md 登记：{module}{fallback}")
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", title, flags=re.UNICODE).strip("-")[:80]
    if not slug:
        raise WikiError("title 无法生成合法文件名")
    today = date.today().isoformat()
    target_dir = _safe_join(root, "知识沉淀", "长期知识")
    target = target_dir / f"{today}-{slug}.md"
    if target.exists():
        raise WikiError(f"长期知识已存在（不覆盖）：{_rel(root, target)}")
    relative_target = _rel(root, target)
    normalized_refs: list[str] = []
    for value in [source, *(source_refs or [])]:
        cleaned = value.strip()[:300] if isinstance(value, str) else ""
        if cleaned and cleaned not in normalized_refs:
            normalized_refs.append(cleaned)
        if len(normalized_refs) >= 30:
            break
    document = (
        "---\n"
        f"title: {title}\nmodule: {module}\nowner: 管理员\ncreated: {today}\nupdated: {today}\n"
        f"version: v1.0\nstatus: 生效\ntags: [长期知识, {knowledge_type}]\nrelated: []\n"
        f"source: {source}\nsource_refs: {json.dumps(normalized_refs, ensure_ascii=False)}\n"
        f"knowledge_type: {knowledge_type}\n---\n\n"
        f"# {title}\n\n{content}\n"
    )
    preview = {
        "schema_version": 2,
        "knowledge_id": f"pawiki-{hashlib.sha256(relative_target.encode('utf-8')).hexdigest()[:16]}",
        "path": relative_target,
        "target": relative_target,
        "title": title,
        "knowledge_type": knowledge_type,
        "module": module,
        "source": source,
        "source_refs": normalized_refs,
        "content_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "confirmed": confirm,
    }
    anchor_task_id = str(task_id or "").strip()
    if anchor_task_id:
        # 锚点进 frontmatter 与 metadata；仅在确认写入前注入，不影响预检哈希。
        document = document.replace(
            f"knowledge_type: {knowledge_type}\n---",
            f"knowledge_type: {knowledge_type}\ntask_id: {anchor_task_id}\n---",
        )
        preview["task_id"] = anchor_task_id
        preview["content_sha256"] = hashlib.sha256(document.encode("utf-8")).hexdigest()
    if module_routing:
        preview["module_routing"] = module_routing
    if not confirm:
        return {**preview, "status": "需要确认", "note": "预检通过；确认内容值得长期复用后以 confirm=true 再次调用"}
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as fh:
            fh.write(document)
    except OSError as exc:
        raise WikiError(f"长期知识写入失败：{exc}") from exc
    return {**preview, "confirmed": True, "status": "已晋升", "note": "任务过程仍由 Memory Center 保存；本文件仅保留稳定增量"}


# =====================================================================
# assistant_admin/validate — 校验
# =====================================================================

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)\)")  # markdown 链接 (path)
_WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)")  # obsidian wiki 链接 [[path
_RELATED_RE = re.compile(r"^related:\s*\[([^\]]*)\]", re.MULTILINE)
_BODY_REF_RE = re.compile(r"`([^`]+)`")  # 正文反引号包裹的引用（索引「文件」区列出的文件名等）
# 索引正文中显式列出的 Markdown 路径；占位符由扫描逻辑跳过。
_BODY_CARD_TOKEN = re.compile(r"^[^*<>{}]+\.md$")


def _is_governed_md(root: Path, path: Path) -> bool:
    """只治理本库维护的知识文档；导入的历史资料保持原样。"""
    rel = path.relative_to(root)
    parts = rel.parts
    if not parts or parts[0] == "收件箱":
        return False
    if parts[0] == "工作":
        if "项目资料" in parts:
            return path.name == _INDEX_NAME
        return path.suffix == ".md"
    if parts[0] == "技术":
        if "参考资料" in parts:
            return path.name == _INDEX_NAME
        return path.suffix == ".md"
    return parts[0] in {
        "个人档案", "研究", "方法", "助手能力", "知识沉淀", "模板", "助手规则",
    } or len(parts) == 1


def _frontmatter_fields(text: str) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def _check_ref(p: Path, ref: str, root: Path) -> tuple[bool, str]:
    """解析一个引用：先按「相对当前文件目录」找，找不到再按「相对 wiki 根」找（本库两种基准混用），
    最后全库按文件名找。返回 (是否找到, 失败原因)。"""
    ref = ref.strip().strip('"\'')
    if not ref or ref.startswith(("http://", "https://", "mailto:", "#")):
        return True, ""
    relative_candidate = (p.parent / ref).resolve()
    root_candidate = (root / ref).resolve()
    if relative_candidate.is_relative_to(root) and relative_candidate.exists():
        return True, ""
    if root_candidate.is_relative_to(root) and root_candidate.exists():
        return True, ""
    if Path(ref).is_absolute() or not root_candidate.is_relative_to(root):
        return False, "引用越界"
    found = any(f.name == ref or f.name == ref + ".md" for f in _walk_md(root))
    return found, "找不到" if not found else ""


def _scan_body_file_refs(p: Path, root: Path) -> list[dict[str, str]]:
    """扫描 索引.md 正文中显式列出的 Markdown 路径，捕获幽灵条目。

    范围严格收窄，避免误报：
      - 只处理 索引.md
      - 只认以 .md 结尾的反引号路径
      - 跳过含 * < > { } 的占位符 / glob
      - 同时支持相对当前索引和相对 Wiki 根的路径
    """
    if p.name != _INDEX_NAME:
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # 去掉 frontmatter，避免与 related 重复校验
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            text = text[end + 4:]
    missing: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _BODY_REF_RE.finditer(text):
        token = m.group(1).strip()
        if any(ch in token for ch in "*<>{}"):
            continue
        if not _BODY_CARD_TOKEN.match(token):
            continue
        if token in seen:
            continue
        seen.add(token)
        ok, _ = _check_ref(p, token, root)
        if ok:
            continue
        missing.append({"from": _rel(root, p), "ref": token, "kind": "body-ref", "why": "索引列出的卡片文件不存在"})
    return missing


def validate(root: Path) -> dict[str, Any]:
    """校验：最高治理文件、索引断链、正文 phantom 引用、frontmatter 与 module 注册。"""
    root = _resolve(root)
    governance_issues = [
        {"path": rel, "issue": "缺少最高治理文件"}
        for rel in REQUIRED_GOVERNANCE_PATHS
        if not (root / rel).is_file()
    ]
    broken: list[dict[str, str]] = []
    checked = 0
    markdown_files = _walk_md(root)
    for p in markdown_files:
        if p.name != _INDEX_NAME:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # 1) frontmatter related: [a, b]（本库索引的主要引用方式）
        m = _RELATED_RE.search(text)
        if m:
            for ref in m.group(1).split(","):
                checked += 1
                ok, why = _check_ref(p, ref, root)
                if not ok:
                    broken.append({"from": _rel(root, p), "ref": ref.strip(), "kind": "related", "why": why})
        # 2) markdown 链接
        for m in _LINK_RE.finditer(text):
            ref = m.group(1)
            checked += 1
            ok, why = _check_ref(p, ref, root)
            if not ok:
                broken.append({"from": _rel(root, p), "ref": ref, "kind": "md-link", "why": why})
        # 3) obsidian 双链
        for m in _WIKI_LINK_RE.finditer(text):
            ref = m.group(1).strip()
            if not ref:
                continue
            checked += 1
            ok, why = _check_ref(p, ref, root)
            if not ok:
                broken.append({"from": _rel(root, p), "ref": ref, "kind": "wiki-link", "why": why})

    modules = _registered_modules(root)
    governed = 0
    frontmatter_issues: list[dict[str, Any]] = []
    for p in markdown_files:
        if not _is_governed_md(root, p):
            continue
        # 4) 正文反引号文件引用存在性（捕获索引「文件」区 phantom 引用）
        for miss in _scan_body_file_refs(p, root):
            broken.append(miss)
        governed += 1
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            frontmatter_issues.append({"path": _rel(root, p), "issues": [f"读取失败：{exc}"]})
            continue
        fields = _frontmatter_fields(text)
        issues: list[str] = []
        if fields is None:
            issues.append("缺少或无法解析 frontmatter")
        else:
            missing = [field for field in REQUIRED_FRONTMATTER_FIELDS if not fields.get(field)]
            if missing:
                issues.append("缺少字段：" + ", ".join(missing))
            module = fields.get("module", "")
            if module and module not in modules:
                issues.append(f"module 未登记：{module}")
            status = fields.get("status", "")
            if status and status not in DOCUMENT_STATUSES:
                issues.append(f"status 非法：{status}")
        if issues:
            frontmatter_issues.append({"path": _rel(root, p), "issues": issues})

    boundary_issues: list[dict[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git" and not (Path(dirpath) / d).is_symlink()]
        for name in filenames:
            path = Path(dirpath) / name
            lower = name.lower()
            if lower in ARCHIVE_JUNK_NAMES:
                boundary_issues.append({"path": _rel(root, path), "issue": "系统垃圾文件"})
            elif lower in DISALLOWED_KNOWLEDGE_NAMES or path.suffix.lower() in DISALLOWED_KNOWLEDGE_SUFFIXES:
                boundary_issues.append({"path": _rel(root, path), "issue": "源码、构建物或压缩档案不应进入知识库"})

    return {
        "checked_links": checked,
        "broken_count": len(broken),
        "broken": broken[:50],
        "governed_markdown_count": governed,
        "frontmatter_issue_count": len(frontmatter_issues),
        "frontmatter_issues": frontmatter_issues[:50],
        "boundary_issue_count": len(boundary_issues),
        "boundary_issues": boundary_issues[:50],
        "governance_issue_count": len(governance_issues),
        "governance_issues": governance_issues,
        "ok": not governance_issues and not broken and not frontmatter_issues and not boundary_issues,
        "note": "最高宪法、链接、正文 phantom 引用、frontmatter 和文档边界均纳入检查；导入资料不强制 frontmatter，外部链接不校验；问题清单各列前 50 条",
    }


def _external_link_inventory(root: Path) -> list[dict[str, Any]]:
    """列出 Wiki 中的外部符号链接，但不遍历或读取链接目标内容。"""
    links: list[dict[str, Any]] = []

    def record(path: Path) -> None:
        raw_target = os.readlink(path)
        try:
            resolved = path.resolve(strict=True)
            available = True
            target_type = "目录" if resolved.is_dir() else "文件" if resolved.is_file() else "其他"
        except OSError:
            resolved = (path.parent / raw_target).resolve()
            available = False
            target_type = "缺失"
        links.append({
            "path": _rel(root, path),
            "target": str(resolved),
            "raw_target": raw_target,
            "available": available,
            "target_type": target_type,
        })

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        keep: list[str] = []
        for name in dirnames:
            path = current / name
            if path.is_symlink():
                record(path)
            elif name.startswith(".") or name in {"target", "build", "__pycache__"}:
                continue
            else:
                keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            path = current / name
            if path.is_symlink():
                record(path)
    return sorted(links, key=lambda item: item["path"])


def analyze(root: Path) -> dict[str, Any]:
    """基于现有索引和真实文件结构生成稳定概览，不临时编写分析脚本。"""
    root = _resolve(root)
    validation = validate(root)
    index = indexer.index_stats(root)
    links = _external_link_inventory(root)
    top_level = sorted(
        path.name for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
    )
    missing_top_level = [name for name in EXPECTED_TOP_LEVEL_DIRS if name not in top_level]
    unexpected_top_level = [name for name in top_level if name not in EXPECTED_TOP_LEVEL_DIRS]
    research_root = root / "研究"
    research_directions = sorted(
        path.name for path in research_root.iterdir()
        if research_root.is_dir() and path.is_dir() and not path.is_symlink()
    ) if research_root.is_dir() else []
    work_root = root / "工作"
    companies = sorted(
        path.name for path in work_root.iterdir()
        if work_root.is_dir() and path.is_dir() and not path.is_symlink()
    ) if work_root.is_dir() else []
    broken_links = [item for item in links if not item["available"]]
    warnings: list[str] = []
    if not index["exists"]:
        warnings.append("全文索引尚未初始化")
    elif index["error_total"]:
        warnings.append(f"全文索引有 {index['error_total']} 个源文件提取失败")
    if not validation["ok"]:
        warnings.append("Wiki 治理校验未通过")
    if broken_links:
        warnings.append(f"有 {len(broken_links)} 个外部符号链接失效")
    if missing_top_level:
        warnings.append("缺少标准顶层目录：" + "、".join(missing_top_level))
    if unexpected_top_level:
        warnings.append("存在非标准顶层目录：" + "、".join(unexpected_top_level))
    return {
        "status": "可用" if index["exists"] and validation["ok"] and not broken_links else "需关注",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root),
        "structure": {
            "top_level": top_level,
            "missing_top_level": missing_top_level,
            "unexpected_top_level": unexpected_top_level,
            "research_directions": research_directions,
            "companies": companies,
        },
        "index": index,
        "external_links": {"count": len(links), "broken_count": len(broken_links), "items": links},
        "validation": {
            "ok": validation["ok"],
            "checked_links": validation["checked_links"],
            "broken_count": validation["broken_count"],
            "frontmatter_issue_count": validation["frontmatter_issue_count"],
            "boundary_issue_count": validation["boundary_issue_count"],
            "governance_issue_count": validation["governance_issue_count"],
        },
        "warnings": warnings,
    }


def initialize(root: Path, force: bool = False) -> dict[str, Any]:
    """一键建立或刷新全文索引，并返回结构、外部入口和治理分析。"""
    root = _resolve(root)
    build = indexer.build_index(root, force=force)
    return {"action": "initialize", "index_build": build, "analysis": analyze(root)}


# =====================================================================
# assistant_admin/scan — 清（只报告）
# =====================================================================

def clean(root: Path, scope: str = "business") -> dict[str, Any]:
    """扫描编译垃圾，只出报告不删除。

    scope:
      - business：工作/ 下的 .svn / target / .class / .pyc / __pycache__ / .DS_Store
      - full：wiki 全库
    删除动作请由客户端 AI 确认后自行走废纸篓（/usr/bin/trash），本工具永不删除。
    """
    root = _resolve(root)
    if scope not in {"business", "full"}:
        raise WikiError("scope 仅支持 business 或 full")
    base = root / "工作" if scope == "business" else root
    if not base.is_dir():
        raise WikiError(f"scope={scope} 的扫描根不存在：{base}")

    found: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") or d in (".svn",)]
        for d in list(dirnames):
            p = Path(dirpath) / d
            if p.is_symlink():
                dirnames.remove(d)
                continue
            if d in {".svn", "target", "__pycache__"}:
                found.append({"path": _rel(root, p), "type": "dir", "name": d})
                dirnames.remove(d)
        for f in filenames:
            if f == ".DS_Store" or f.endswith((".class", ".pyc")):
                found.append({"path": _rel(root, Path(dirpath) / f), "type": "file", "name": f})

    dirs = [f for f in found if f["type"] == "dir"]
    files = [f for f in found if f["type"] == "file"]
    return {
        "scope": scope,
        "scan_root": _rel(root, base),
        "dir_junk_count": len(dirs),
        "file_junk_count": len(files),
        "dirs": dirs[:100],
        "files": files[:100],
        "safety": "本工具只扫描不删除；如需清理，客户端确认后走 /usr/bin/trash（废纸篓可恢复）",
    }
