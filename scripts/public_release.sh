#!/usr/bin/env bash
# 公开发布流水线 / Public release pipeline
#
# 从某个 commit 导出"公开仓库快照"：`git archive` 按 .gitattributes 的
# export-ignore 剔除内部资料（docs-internal/、.dsh-tmp/、示例生成物等），
# 然后在干净目录里新建独立 git 历史（首个 commit 即公开历史，不带私有历史）。
#
# 用法 / Usage:
#   scripts/public_release.sh                     # 导出到临时目录并跑校验门禁（默认不落盘）
#   scripts/public_release.sh --keep --ref HEAD   # 保留导出目录，人工复核
#   scripts/public_release.sh --publish --out ../memory-center-public
#   scripts/public_release.sh --publish --out ../memory-center-public \
#       --remote git@github.com:<org>/memory-center.git
#
# 选项 / Options:
#   --ref <ref>      源提交/标签，默认 HEAD
#   --out <dir>      输出目录（--publish 时必填），默认 ../memory-center-public
#   --remote <url>   推送目标；给出时在 commit 后 push
#   --publish        真正写到输出目录并创建 commit（默认只做 dry-run 校验）
#   --keep           保留临时导出目录（便于逐步检查）
#   --force          输出目录已存在时覆盖（仅删除确认是本脚本产物的情况）
#   -h, --help       显示帮助

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REF="HEAD"
OUT_DIR="../memory-center-public"
REMOTE=""
PUBLISH=0
KEEP=0
FORCE=0

usage() {
  sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:?--ref 需要一个值}"; shift 2 ;;
    --out) OUT_DIR="${2:?--out 需要一个值}"; shift 2 ;;
    --remote) REMOTE="${2:?--remote 需要一个值}"; shift 2 ;;
    --publish) PUBLISH=1; shift ;;
    --keep) KEEP=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数 / unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v git >/dev/null || { echo "需要 git" >&2; exit 2; }
command -v python3 >/dev/null || { echo "需要 python3 做链接校验" >&2; exit 2; }

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "必须在 git 仓库内运行 / must run inside the git repository" >&2
  exit 2
fi

git rev-parse --verify -q "$REF^{commit}" >/dev/null || {
  echo "无效的 ref: $REF" >&2; exit 2;
}

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' memory_center/__init__.py)"
[ -n "$VERSION" ] || VERSION="unknown"
SHORT_SHA="$(git rev-parse --short "$REF")"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/memory-center-public.XXXXXX")"
cleanup() {
  if [ "$KEEP" -eq 0 ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

echo "==> 导出来源 / exporting: $REF ($SHORT_SHA), version $VERSION"
git archive --format=tar "$REF" | tar -xf - -C "$TMP_DIR"

echo
echo "==> 校验公开面 / verifying public surface"
FAILED=0
fail() { echo "  [FAIL] $*"; FAILED=$((FAILED + 1)); }
ok() { echo "  [ ok ] $*"; }

# 1) 私有标识与凭证模式
BANNED='ucap|kaipuyun|开普云|cuijiaqi|javaworkspace|众包|预警发送'
# 门禁脚本自身必然包含这些模式，扫描时排除。
HITS="$(grep -rIn -E "$BANNED" "$TMP_DIR" --exclude-dir=.git --exclude=public_release.sh 2>/dev/null || true)"
if [ -n "$HITS" ]; then
  fail "命中私有标识 / private markers:"
  printf '%s\n' "$HITS" | sed -n '1,20p' | sed 's/^/         /'
else
  ok "私有标识 0 命中"
fi

# 1b) 家目录路径：允许测试里的占位用户名，只拦截真实用户名
HOME_DIR_HITS="$(python3 - "$TMP_DIR" <<'PY'
import pathlib, re, sys

ALLOWED = {
    "you", "example", "secret", "test", "john", "admin", "user", "someone",
    "alice", "bob", "dummy", "path", "home", "private", "shared", "demo",
}
root = pathlib.Path(sys.argv[1])
pattern = re.compile(r'/Users/([A-Za-z][A-Za-z0-9_.-]*)')
for path in sorted(root.rglob("*")):
    if not path.is_file() or ".git" in path.parts:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for match in pattern.finditer(text):
        name = match.group(1)
        if name not in ALLOWED:
            print(f"{path.relative_to(root)}: /Users/{name}/")
PY
)"
if [ -n "$HOME_DIR_HITS" ]; then
  fail "命中真实用户家目录 / real home directory:"
  printf '%s\n' "$HOME_DIR_HITS" | sed -n '1,20p' | sed 's/^/         /'
else
  ok "家目录路径 0 命中（仅允许占位用户名）"
fi

SECRET_HITS="$(python3 - "$TMP_DIR" <<'PY'
import pathlib, re, sys

# 明显是占位符的假凭证（测试夹具常用），不算泄露
PLACEHOLDER = ("abcdefghijklmnopqrstuvwxyz", "0000000000", "xxxxxxxx", "example", "placeholder", "dummy")
PATTERN = re.compile(
    r'ghp_[A-Za-z0-9]{36}'
    r'|github_pat_[A-Za-z0-9_]{20,}'
    r'|sk-[A-Za-z0-9]{32,}'
    r'|AKIA[0-9A-Z]{16}'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----'
)
root = pathlib.Path(sys.argv[1])
for path in sorted(root.rglob("*")):
    if not path.is_file() or ".git" in path.parts:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in PATTERN.finditer(line):
            value = match.group(0)
            lowered = value.lower()
            if any(token in lowered for token in PLACEHOLDER):
                continue
            print(f"{path.relative_to(root)}:{lineno}: {value[:24]}…")
PY
)"
if [ -n "$SECRET_HITS" ]; then
  fail "疑似凭证 / possible secrets:"
  printf '%s\n' "$SECRET_HITS" | sed -n '1,10p' | sed 's/^/         /'
else
  ok "凭证模式 0 命中（占位符除外）"
fi

# 2) 内部路径不应出现在导出树
for forbidden in docs-internal .dsh-tmp .gitnexus .venv node_modules .memory-center graph.db store.lock .env; do
  if find "$TMP_DIR" -name "$forbidden" -print -quit 2>/dev/null | grep -q .; then
    fail "导出树中残留内部路径 / leaked path: $forbidden"
  fi
done
if [ -z "$(find "$TMP_DIR" -name '*.db' -print -quit 2>/dev/null)" ]; then
  ok "无 .db 生成物"
fi

# 3) 必须存在的公开面文件
for required in README.md LICENSE NOTICE docs/CHANGELOG.md docs/MCP_GUIDE.md docs/ARCHITECTURE.md \
                docs/USER_GUIDE.md docs/REFERENCE.md .github/workflows/ci.yml frontend/package.json; do
  if [ -e "$TMP_DIR/$required" ]; then
    ok "存在 $required"
  else
    fail "缺少 $required"
  fi
done

# 4) LICENSE 必须是官方 Apache-2.0 全文 + 版权行
if [ -f "$TMP_DIR/LICENSE" ]; then
  LICENSE_LINES="$(wc -l < "$TMP_DIR/LICENSE" | tr -d ' ')"
  if [ "$LICENSE_LINES" -ge 190 ] && grep -q 'APPENDIX: How to apply the Apache License to your work' "$TMP_DIR/LICENSE"; then
    ok "LICENSE 为 Apache-2.0 全文（$LICENSE_LINES 行）"
  else
    fail "LICENSE 不是 Apache-2.0 官方全文（$LICENSE_LINES 行）"
  fi
  grep -q 'Copyright 2026 Memory Center Contributors' "$TMP_DIR/LICENSE" \
    && ok "LICENSE 含版权行" || fail "LICENSE 缺 Copyright 行"
fi

# 5) Markdown 相对链接可解析
LINK_REPORT="$(python3 - "$TMP_DIR" <<'PY'
import pathlib, re, sys

root = pathlib.Path(sys.argv[1])
pattern = re.compile(r'!?\[[^\]]*\]\(([^)\s]+)\)')
broken = []
for path in sorted(root.rglob("*.md")):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for match in pattern.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
            continue
        clean = target.split("#", 1)[0].split("?", 1)[0]
        if not clean or clean.startswith("/"):
            continue
        if not (path.parent / clean).resolve().exists():
            broken.append(f"{path.relative_to(root)} -> {target}")
for item in broken[:20]:
    print(item)
print(f"__COUNT__{len(broken)}")
PY
)"
LINK_COUNT="$(printf '%s\n' "$LINK_REPORT" | sed -n 's/^__COUNT__//p' | tail -1)"
if [ "${LINK_COUNT:-0}" -eq 0 ]; then
  ok "Markdown 相对链接全部可解析"
else
  fail "存在 $LINK_COUNT 个断链 / broken relative links:"
  printf '%s\n' "$LINK_REPORT" | grep -v '^__COUNT__' | sed 's/^/         /'
fi

# 6) 文件规模概览
FILE_COUNT="$(find "$TMP_DIR" -type f -not -path '*/.git/*' | wc -l | tr -d ' ')"
SIZE="$(du -sh "$TMP_DIR" 2>/dev/null | awk '{print $1}')"
echo
echo "==> 公开面概览 / public surface: $FILE_COUNT files, $SIZE"

if [ "$FAILED" -gt 0 ]; then
  echo
  echo "校验未通过（$FAILED 项）。私有仓未改动，导出目录: $TMP_DIR" >&2
  if [ "$KEEP" -eq 0 ]; then
    echo "提示：加 --keep 可保留导出目录定位问题。" >&2
  fi
  trap - EXIT
  exit 1
fi

echo
echo "校验通过 / verification passed"

if [ "$PUBLISH" -eq 0 ]; then
  echo "dry-run 完成，未落盘。加 --publish 生成公开快照仓库。"
  if [ "$KEEP" -eq 1 ]; then
    echo "导出目录已保留: $TMP_DIR"
  fi
  trap - EXIT
  exit 0
fi

# ---- 落盘：新建独立历史 ----
OUT_ABS="$(cd "$(dirname "$OUT_DIR")" && pwd)/$(basename "$OUT_DIR")"
if [ -e "$OUT_ABS" ]; then
  if [ "$FORCE" -ne 1 ]; then
    echo "输出目录已存在: ${OUT_ABS}（加 --force 覆盖）" >&2
    exit 1
  fi
  rm -rf "$OUT_ABS"
fi
mkdir -p "$OUT_ABS"
echo "==> 写入公开快照 / writing snapshot: $OUT_ABS"
tar -C "$TMP_DIR" -cf - . | tar -C "$OUT_ABS" -xf -

cd "$OUT_ABS"
git init -q -b main
git add -A
git -c user.name="${GIT_AUTHOR_NAME:-Memory Center Release}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-release@example.com}" \
    commit -q -m "Memory Center $VERSION — 首个公开快照 / initial public snapshot" \
               -m "从私有仓 $SHORT_SHA 导出，已剔除内部路线、回执、基准与本地生成物。"

git tag -a "v$VERSION" -m "Memory Center $VERSION" 2>/dev/null || true
echo "==> 已创建 ${OUT_ABS}（1 个 commit, tag v$VERSION, $FILE_COUNT files）"

if [ -n "$REMOTE" ]; then
  echo "==> 推送 / pushing to $REMOTE"
  git remote add public "$REMOTE" 2>/dev/null || git remote set-url public "$REMOTE"
  git push -u public main
  git push public "v$VERSION"
  echo "==> 推送完成。检查 GitHub 仓库的 About/许可证识别与 CI 首次运行。"
else
  echo
  echo "下一步（手动推送）/ next steps:"
  echo "  cd \"$OUT_ABS\""
  echo "  git remote add public <url>"
  echo "  git push -u public main && git push public v$VERSION"
fi
