"""可重建的本地文档全文索引。

索引文件放在用户缓存目录，不写入知识库。知识库仍只保存原始文档和受治理 Markdown；
缓存可随时删除并通过 ``build_index`` 增量重建。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MAX_INDEX_CHARS = 1_000_000
TEXT_SUFFIXES = {
    ".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml",
    ".xml", ".html", ".htm", ".ini", ".conf", ".rtf", ".mht",
}
EXTRACTABLE_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".docx", ".xlsx", ".pptx"}
METADATA_ONLY_SUFFIXES = {
    ".doc", ".xls", ".ppt", ".xmind", ".bpmn", ".pdm", ".vsd", ".mpp", ".pos",
    ".png", ".jpg", ".jpeg", ".gif", ".svg",
}
INDEXABLE_SUFFIXES = EXTRACTABLE_SUFFIXES | METADATA_ONLY_SUFFIXES
SKIP_DIRS = {".git", ".obsidian", "__pycache__", "target", "build", ".svn"}
_WATCHERS: dict[str, dict[str, Any]] = {}
_WATCHERS_LOCK = threading.RLock()


def cache_path(root: Path) -> Path:
    resolved = root.expanduser().resolve()
    key = hashlib.sha256(str(resolved).encode()).hexdigest()[:12]
    base = resolved.parent / ".knowledge-index"
    return base / f"{resolved.name}-{key}.sqlite3"


def _iter_documents(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep: list[str] = []
        for name in dirnames:
            path = Path(dirpath) / name
            if name in SKIP_DIRS or name.startswith(".") or path.is_symlink():
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or name.startswith((".", "~$")):
                continue
            if path.suffix.lower() in INDEXABLE_SUFFIXES:
                yield path


def _trim(text: str) -> str:
    text = text.replace("\x00", " ")
    return text[:MAX_INDEX_CHARS]


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    parts: list[str] = []
    size = 0
    for page in PdfReader(str(path)).pages:
        text = page.extract_text() or ""
        parts.append(text)
        size += len(text)
        if size >= MAX_INDEX_CHARS:
            break
    return _trim("\n".join(parts))


def _extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text]
    size = sum(map(len, parts))
    for table in doc.tables:
        for row in table.rows:
            text = "\t".join(cell.text for cell in row.cells)
            parts.append(text)
            size += len(text)
            if size >= MAX_INDEX_CHARS:
                return _trim("\n".join(parts))
    return _trim("\n".join(parts))


def _extract_pptx(path: Path) -> str:
    from pptx import Presentation

    parts: list[str] = []
    size = 0
    for slide in Presentation(str(path)).slides:
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text:
                parts.append(text)
                size += len(text)
        if size >= MAX_INDEX_CHARS:
            break
    return _trim("\n".join(parts))


def _extract_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    parts: list[str] = []
    size = 0
    try:
        for sheet in workbook.worksheets:
            parts.append(f"# {sheet.title}")
            size += len(sheet.title) + 2
            for row in sheet.iter_rows(values_only=True):
                values = [str(v) for v in row if v is not None]
                if values:
                    text = "\t".join(values)
                    parts.append(text)
                    size += len(text)
                if size >= MAX_INDEX_CHARS:
                    return _trim("\n".join(parts))
    finally:
        workbook.close()
    return _trim("\n".join(parts))


def extract(path: Path) -> tuple[str, str, str]:
    """返回 title, content, extractor；单文件失败由调用方记录，不中断全库。"""
    suffix = path.suffix.lower()
    title = path.stem
    if suffix in TEXT_SUFFIXES:
        return title, _trim(path.read_text(encoding="utf-8", errors="replace")), "text"
    if suffix == ".pdf":
        return title, _extract_pdf(path), "pypdf"
    if suffix == ".docx":
        return title, _extract_docx(path), "python-docx"
    if suffix == ".pptx":
        return title, _extract_pptx(path), "python-pptx"
    if suffix == ".xlsx":
        return title, _extract_xlsx(path), "openpyxl"
    return title, "", "metadata-only"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    db = sqlite3.connect(path)
    path.chmod(0o600)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """CREATE TABLE IF NOT EXISTS documents (
        path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
        title TEXT NOT NULL, content TEXT NOT NULL, extractor TEXT NOT NULL, error TEXT NOT NULL
        )"""
    )
    db.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(path UNINDEXED, title, content, tokenize='trigram')"
    )
    return db


def build_index(root: Path, force: bool = False, defer_binary: bool = False) -> dict[str, Any]:
    root = root.expanduser().resolve()
    db_path = cache_path(root)
    db = _connect(db_path)
    existing = {
        row[0]: (row[1], row[2], row[3])
        for row in db.execute("SELECT path, mtime_ns, size, extractor FROM documents")
    }
    seen: set[str] = set()
    added = updated = unchanged = failed = 0
    extractors: dict[str, int] = {}
    try:
        for path in _iter_documents(root):
            rel = str(path.relative_to(root))
            seen.add(rel)
            stat = path.stat()
            prior = existing.get(rel)
            if not force and prior and prior[:2] == (stat.st_mtime_ns, stat.st_size) and (prior[2] != "pending" or defer_binary):
                unchanged += 1
                continue
            error = ""
            try:
                if defer_binary and path.suffix.lower() in {".pdf", ".docx", ".xlsx", ".pptx"}:
                    title, content, extractor = path.stem, "", "pending"
                else:
                    title, content, extractor = extract(path)
            except Exception as exc:  # 单个历史文档损坏不阻断全库索引
                title, content, extractor = path.stem, "", "failed"
                error = f"{type(exc).__name__}: {exc}"[:500]
                failed += 1
            extractors[extractor] = extractors.get(extractor, 0) + 1
            db.execute("DELETE FROM documents_fts WHERE path = ?", (rel,))
            db.execute(
                "INSERT INTO documents_fts(path, title, content) VALUES (?, ?, ?)",
                (rel, title, content),
            )
            db.execute(
                """INSERT INTO documents(path, mtime_ns, size, title, content, extractor, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET mtime_ns=excluded.mtime_ns, size=excluded.size,
                title=excluded.title, content=excluded.content, extractor=excluded.extractor, error=excluded.error""",
                (rel, stat.st_mtime_ns, stat.st_size, title, content, extractor, error),
            )
            if prior is None:
                added += 1
            else:
                updated += 1
            if (added + updated) % 50 == 0:
                db.commit()
        removed_paths = set(existing) - seen
        for rel in removed_paths:
            db.execute("DELETE FROM documents WHERE path = ?", (rel,))
            db.execute("DELETE FROM documents_fts WHERE path = ?", (rel,))
        db.commit()
        total = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        error_total = db.execute("SELECT COUNT(*) FROM documents WHERE error != ''").fetchone()[0]
    finally:
        db.close()
    return {
        "cache": str(db_path), "total": total, "added": added, "updated": updated,
        "unchanged": unchanged, "removed": len(removed_paths), "failed_this_run": failed,
        "error_total": error_total,
        "extractors_this_run": extractors,
    }


def index_stats(root: Path) -> dict[str, Any]:
    """读取现有索引的可解释统计；索引不存在时不隐式创建。"""
    db_path = cache_path(root)
    if not db_path.is_file():
        return {
            "exists": False,
            "cache": str(db_path),
            "total": 0,
            "error_total": 0,
            "by_top_level": {},
            "by_extractor": {},
            "error_samples": [],
        }
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        total = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        error_total = db.execute("SELECT COUNT(*) FROM documents WHERE error != ''").fetchone()[0]
        top_rows = db.execute(
            """SELECT CASE WHEN instr(path, '/') = 0 THEN '(根目录)'
                       ELSE substr(path, 1, instr(path, '/') - 1) END AS section,
                      COUNT(*) AS count
               FROM documents GROUP BY section ORDER BY section"""
        ).fetchall()
        extractor_rows = db.execute(
            "SELECT extractor, COUNT(*) AS count FROM documents GROUP BY extractor ORDER BY extractor"
        ).fetchall()
        error_rows = db.execute(
            "SELECT path, error FROM documents WHERE error != '' ORDER BY path LIMIT 20"
        ).fetchall()
        return {
            "exists": True,
            "cache": str(db_path),
            "total": total,
            "error_total": error_total,
            "by_top_level": {row["section"]: row["count"] for row in top_rows},
            "by_extractor": {row["extractor"]: row["count"] for row in extractor_rows},
            "error_samples": [dict(row) for row in error_rows],
        }
    finally:
        db.close()


def search_index(root: Path, query: str, limit: int = 10, scope_prefix: str = "") -> dict[str, Any] | None:
    db_path = cache_path(root)
    if not db_path.is_file():
        return None
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        where_scope = " AND path LIKE ?" if scope_prefix else ""
        params: list[Any] = [query]
        if scope_prefix:
            params.append(scope_prefix.rstrip("/") + "/%")
        params.append(limit)
        use_like = len(query) < 3
        try:
            if use_like:
                raise sqlite3.OperationalError("trigram queries require at least three characters")
            rows = db.execute(
                "SELECT path, title, snippet(documents_fts, 2, '[', ']', '…', 24) AS snippet, bm25(documents_fts) AS score "
                f"FROM documents_fts WHERE documents_fts MATCH ?{where_scope} ORDER BY score LIMIT ?",
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            like_params: list[Any] = [f"%{query}%", f"%{query}%"]
            if scope_prefix:
                like_params.append(scope_prefix.rstrip("/") + "/%")
            like_params.append(limit)
            rows = db.execute(
                "SELECT path, title, substr(content, 1, 300) AS snippet, 0.0 AS score FROM documents "
                f"WHERE (title LIKE ? OR content LIKE ?){where_scope} LIMIT ?",
                like_params,
            ).fetchall()
        return {"cache": str(db_path), "hits": [dict(row) for row in rows]}
    finally:
        db.close()


def read_indexed(root: Path, relative_path: str) -> dict[str, str] | None:
    db_path = cache_path(root)
    if not db_path.is_file():
        return None
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            "SELECT path, title, content, extractor, error FROM documents WHERE path = ?",
            (relative_path,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def _document_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    """以路径、mtime 和大小构成轻量快照；不读取文档正文。"""
    rows = []
    for path in _iter_documents(root):
        stat = path.stat()
        rows.append((str(path.relative_to(root)), stat.st_mtime_ns, stat.st_size))
    return tuple(rows)


def start_watcher(root: Path, interval_seconds: float = 2.0, debounce_seconds: float = 1.0) -> dict[str, Any]:
    """启动单例轮询 watcher；变更稳定后自动调用增量 build_index。"""
    resolved = root.expanduser().resolve()
    key = str(resolved)
    with _WATCHERS_LOCK:
        existing = _WATCHERS.get(key)
        if existing and existing["thread"].is_alive():
            return watcher_status(resolved)
        state: dict[str, Any] = {
            "root": resolved,
            "running": True,
            "last_scan_at": None,
            "last_refresh_at": None,
            "last_result": None,
            "last_error": None,
            "refresh_count": 0,
            "signature": _document_signature(resolved),
            "pending_signature": None,
            "pending_since": None,
            "interval_seconds": interval_seconds,
            "debounce_seconds": debounce_seconds,
        }

        def run() -> None:
            while state["running"]:
                try:
                    signature = _document_signature(resolved)
                    state["last_scan_at"] = time.time()
                    if signature != state["signature"] and signature != state["pending_signature"]:
                        state["pending_signature"] = signature
                        state["pending_since"] = time.monotonic()
                    if state["pending_signature"] is not None and (
                        time.monotonic() - state["pending_since"] >= debounce_seconds
                    ):
                        state["last_result"] = build_index(resolved)
                        state["signature"] = state["pending_signature"]
                        state["pending_signature"] = None
                        state["pending_since"] = None
                        state["last_refresh_at"] = time.time()
                        state["refresh_count"] += 1
                        state["last_error"] = None
                except Exception as exc:  # watcher 绝不终止 MCP 服务
                    state["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
                time.sleep(interval_seconds)

        thread = threading.Thread(target=run, name=f"pawiki-index-{hash(key)}", daemon=True)
        state["thread"] = thread
        _WATCHERS[key] = state
        thread.start()
    return watcher_status(resolved)


def watcher_status(root: Path) -> dict[str, Any]:
    resolved = root.expanduser().resolve()
    with _WATCHERS_LOCK:
        state = _WATCHERS.get(str(resolved))
        if not state:
            return {"running": False, "refresh_count": 0}
        return {
            "running": bool(state["running"] and state["thread"].is_alive()),
            "last_scan_at": state["last_scan_at"],
            "last_refresh_at": state["last_refresh_at"],
            "last_result": state["last_result"],
            "last_error": state["last_error"],
            "refresh_count": state["refresh_count"],
            "pending": state["pending_signature"] is not None,
            "interval_seconds": state["interval_seconds"],
            "debounce_seconds": state["debounce_seconds"],
        }
