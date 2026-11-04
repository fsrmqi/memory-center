#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${MEMORY_CENTER_REPO_URL:-git+https://github.com/fsrmqi/memory-center.git}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_INSTALL_TARGET="$REPO_URL"
if [[ -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
  DEFAULT_INSTALL_TARGET="$SCRIPT_DIR"
fi
INSTALL_TARGET="${MEMORY_CENTER_INSTALL_TARGET:-$DEFAULT_INSTALL_TARGET}"
EXTRAS="${MEMORY_CENTER_EXTRAS:-}"
PYTHON_BIN="${PYTHON_BIN:-}"

say() {
  printf '%s\n' "$*"
}

fail() {
  say "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

is_supported_python() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
}

choose_python() {
  local candidate
  for candidate in python3.12 python3.11 python3.10 python3; do
    if need_cmd "$candidate" && is_supported_python "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

user_bin_dir() {
  "$PYTHON_BIN" - <<'PY'
import site
import sys
base = site.USER_BASE
if not base:
    sys.exit(1)
print(base + "/bin")
PY
}

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(choose_python || true)"
fi

if [[ -z "$PYTHON_BIN" ]] || ! need_cmd "$PYTHON_BIN" || ! is_supported_python "$PYTHON_BIN"; then
  fail "Python 3.10+ not found. Install python3.10, python3.11, or newer first, or set PYTHON_BIN explicitly."
fi

if ! need_cmd pipx; then
  say "pipx not found. Installing pipx with ${PYTHON_BIN} -m pip --user pipx ..."
  "$PYTHON_BIN" -m pip install --user pipx || fail "Failed to install pipx."
  "$PYTHON_BIN" -m pipx ensurepath || true
  USER_BIN="$(user_bin_dir 2>/dev/null || true)"
  if [[ -n "${USER_BIN:-}" ]]; then
    export PATH="${USER_BIN}:$PATH"
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! need_cmd pipx; then
  USER_BIN="$(user_bin_dir 2>/dev/null || true)"
  say ""
  say "pipx is installed, but the current shell cannot find it yet."
  say "Run one of the following, then rerun install.sh:"
  if [[ -n "${USER_BIN:-}" ]]; then
    say "  export PATH=\"${USER_BIN}:\$PATH\""
  fi
  say "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  say ""
  say "To make it permanent in zsh:"
  if [[ -n "${USER_BIN:-}" ]]; then
    say "  echo 'export PATH=\"${USER_BIN}:\$PATH\"' >> ~/.zshrc"
  else
    say "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
  fi
  say "  source ~/.zshrc"
  fail "pipx is still not available in PATH."
fi

PACKAGE_SPEC="$INSTALL_TARGET"
if [[ -n "$EXTRAS" ]]; then
  if [[ "$INSTALL_TARGET" == git+* ]]; then
    say "WARNING: extras are not applied automatically for raw git targets."
    say "WARNING: install base package first, then run a manual pipx inject if needed."
  else
    PACKAGE_SPEC="${PACKAGE_SPEC}[${EXTRAS}]"
  fi
fi

say "Installing Memory Center with pipx ..."
say "Package: ${PACKAGE_SPEC}"

if pipx list 2>/dev/null | grep -q "package memory-center "; then
  say "Existing installation detected. Reinstalling from current package target ..."
  pipx uninstall memory-center >/dev/null 2>&1 || true
  pipx install --python "$PYTHON_BIN" "$PACKAGE_SPEC" || {
    say "Install failed after uninstall. Retrying once ..."
    pipx uninstall memory-center >/dev/null 2>&1 || true
    pipx install --python "$PYTHON_BIN" "$PACKAGE_SPEC"
  }
else
  pipx install --python "$PYTHON_BIN" "$PACKAGE_SPEC"
fi

say ""
say "Memory Center installed."
say ""
say "Verify:"
say "  memory-center --version"
say ""
say "MCP support is installed by default."
say ""
say "Example:"
say "  memory-center doctor --workspace /path/to/.memory-center/workspace.yaml --self-test"
if [[ -n "$EXTRAS" && "$INSTALL_TARGET" == git+* ]]; then
  say ""
  say "For extras on a git target, run manually after install:"
  say "  pipx inject memory-center <extra-package>"
fi
