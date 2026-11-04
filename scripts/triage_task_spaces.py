#!/usr/bin/env python3
"""Task space 分诊报告（只读，不修改任何数据）。

扫描任务空间的 summary-history.md 轮替记录，按每次写入的 Intent/Task 头与
任务标题（meta.json）的相关性分组，标记 KEEP（主题一致）/ SUSPECT（疑似污染），
供人工确认后另行处置。判定口径与生产匹配器一致：workspace 名、框架通名、
短 token 不计相关性；title/intent 子串重叠需 ≥2 个非通名 token。

用法:
    python3 scripts/triage_task_spaces.py --workspace <workspace.yaml> \
        [--tasks 任务A,任务B] [--min-score 2] [--out report.md]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from memory_center.core.foundation.text import base_tokenize  # noqa: E402
from memory_center.core.workspace.config import load_workspace_config  # noqa: E402

FRAMEWORK_TOKENS = {
    "feign", "kafka", "rocketmq", "redis", "elasticsearch", "mysql", "mongo", "mongodb",
    "controller", "service", "dto", "api", "http", "rest", "gateway", "spring", "boot",
    "java", "config", "consumer", "producer", "topic", "queue", "token", "login",
    "mc", "start", "lookup", "close", "sync", "impl", "bean", "util", "common",
}
HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}T[^\s]+) / (\S+)", re.MULTILINE)
TASK_LINE_RE = re.compile(r"\*\*(?:Task|Intent)\*\*: (.+)")
STALE_DAYS = 14


def weak(token: str, workspace_name: str) -> bool:
    if token in FRAMEWORK_TOKENS or token.isdigit() or len(token) <= 2:
        return True
    if workspace_name and (workspace_name.startswith(token) or token.startswith(workspace_name)):
        return True
    return False


def discriminative_tokens(text: str, workspace_name: str) -> set[str]:
    return {
        tok
        for tok in base_tokenize(str(text or ""))
        if not weak(tok, workspace_name)
    }


def _bigrams(text: str) -> set[str]:
    cleaned = "".join(text.split()).lower()
    grams = {cleaned[i:i + 2] for i in range(len(cleaned) - 1)} if len(cleaned) >= 2 else {cleaned}
    # 只保留 CJK 二字片段：英文碎片（'er'/'in'/'nk'）无区分度，混入锚会稀释门槛。
    return {g for g in grams if all("\u4e00" <= ch <= "\u9fff" for ch in g)}


def related(topic: str, anchor_tokens: set[str], anchor_bigrams: set[str], min_score: int, workspace_name: str = "") -> bool:
    """相关性：非通名 token 精确交集达标，或字符 bigram 重叠率达标。

    标题常是实体名（如"订单服务"）而 topic 是长句（分词后无整串重叠），
    因此补充字符 bigram 重叠判定——长句与短实体名共享"订单/服务"等
    二字片段即视为相关；纯泛词长句 bigram 命中率极低，不会误判。
    """
    topic_tokens = discriminative_tokens(topic, workspace_name)
    if score_overlap(topic_tokens, anchor_tokens) >= min_score:
        return True
    topic_bigrams = _bigrams(topic)
    if not topic_bigrams or not anchor_bigrams:
        return False
    hit = len(topic_bigrams & anchor_bigrams)
    # CJK 片段锚是高区分度实体词（外链/预警/众包…）。命中 max(2, 锚的1/3) 个
    # 不同片段即视为相关；泛词长句几乎不可能与实体标题共享 3 个连续二字片段。
    return hit >= max(2, len(anchor_bigrams) // 3)


def split_history(text: str) -> list[tuple[str, str, str]]:
    """Split summary-history.md into (timestamp, source, body) chunks."""
    stamps = list(HEADER_RE.finditer(text))
    chunks = []
    for i, match in enumerate(stamps):
        end = stamps[i + 1].start() if i + 1 < len(stamps) else len(text)
        chunks.append((match.group(1), match.group(2), text[match.end():end]))
    return chunks


def entry_topic(chunk_body: str) -> str:
    for line in chunk_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Intent**:"):
            return stripped.removeprefix("**Intent**:").strip()
    for line in chunk_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Task**:"):
            return stripped.removeprefix("**Task**:").strip()
    return ""


def score_overlap(a: set[str], b: set[str]) -> int:
    return len(a & b)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--tasks", default="", help="逗号分隔的 task_id；缺省扫描全部 active")
    parser.add_argument("--min-score", type=int, default=2, help="topic↔标题非通名 token 重叠达标线")
    parser.add_argument("--out", default="", help="报告输出路径；缺省打印 stdout")
    args = parser.parse_args()

    config = load_workspace_config(args.workspace)
    workspace_name = str(config.workspace or "").strip().lower()
    tasks_root = Path(args.workspace).parent / "artifacts" / "tasks"
    wanted = [t.strip() for t in args.tasks.split(",") if t.strip()]
    task_dirs = sorted([d for d in tasks_root.iterdir() if d.is_dir() and (not wanted or d.name in wanted)])

    lines = ["# Task Space 分诊报告 / Triage Report", ""]
    now = datetime.now()
    for task_dir in task_dirs:
        meta_path = task_dir / "meta.json"
        if not meta_path.exists():
            continue
        import json
        meta = json.loads(meta_path.read_text(encoding="utf8"))
        title = str(meta.get("title", "") or task_dir.name)
        intent_meta = str(meta.get("intent", "") or "")
        updated_at = str(meta.get("updated_at", "") or "")
        try:
            stale = (now - datetime.fromisoformat(updated_at)).days >= STALE_DAYS
        except (TypeError, ValueError):
            stale = False

        title_tokens = discriminative_tokens(title, workspace_name)
        intent_tokens = discriminative_tokens(intent_meta, workspace_name)
        anchor_tokens = title_tokens | intent_tokens
        # bigram 锚只用标题：meta.intent 可能被历史轮替污染成长句，会把
        # anchor 稀释成几十个片段导致门槛失衡。标题是任务身份的稳定锚。
        anchor_bigrams = _bigrams(title)

        history_path = task_dir / "summary-history.md"
        if not history_path.exists():
            lines += [f"## {title}", f"- 无 summary-history.md，跳过。", ""]
            continue

        keep, suspect = [], []
        for stamp, source, body in split_history(history_path.read_text(encoding="utf8")):
            topic = entry_topic(body)
            if not topic:
                suspect.append((stamp, source, "(空/模板写入)", 0))
                continue
            ok = related(topic, anchor_tokens, anchor_bigrams, args.min_score, workspace_name)
            overlap = score_overlap(discriminative_tokens(topic, workspace_name), anchor_tokens)
            (keep if ok else suspect).append((stamp, source, topic[:90], overlap))

        lines += [
            f"## {title}",
            f"- 注册状态: {meta.get('status', '')} | 更新: {updated_at[:19]} | {'**stale**' if stale else '活跃'}",
            f"- meta.intent: {intent_meta[:80]}",
            f"- 锚定 token（标题∪meta.intent 去通名）: {sorted(anchor_tokens)[:12]}",
            f"- 历史写入总数: {len(keep) + len(suspect)}  → **KEEP {len(keep)} / SUSPECT {len(suspect)}**",
            "",
        ]
        if suspect:
            lines.append("| 时间 | 来源 | 主题（Intent/Task 头） | 重叠 |")
            lines.append("|---|---|---|---|")
            for stamp, source, topic, overlap in suspect:
                lines.append(f"| {stamp[:19]} | {source} | {topic} | {overlap} |")
            lines.append("")
        top_kept = Counter(topic[:60] for _, _, topic, _ in keep).most_common(3)
        if top_kept:
            lines.append(f"- KEEP 主要主题: " + "；".join(f"{t}（{n}x）" for t, n in top_kept))
        lines.append("")

    report = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(report, encoding="utf8")
        print(f"报告已写入 {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
