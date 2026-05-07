#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${MEMORY_CENTER_REPO_URL:-git+https://github.com/fsrmqi/memory-center.git}"
INSTALL_TARGET="${MEMORY_CENTER_INSTALL_TARGET:-$REPO_URL}"
EXTRAS="${MEMORY_CENTER_EXTRAS:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

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

if ! need_cmd "$PYTHON_BIN"; then
  fail "python3 not found. Install Python 3.10+ first."
fi

if ! need_cmd pipx; then
  say "pipx not found. Installing pipx with ${PYTHON_BIN} -m pip --user pipx ..."
  "$PYTHON_BIN" -m pip install --user pipx || fail "Failed to install pipx."
  "$PYTHON_BIN" -m pipx ensurepath || true
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! need_cmd pipx; then
  fail "pipx is still not available in PATH. Open a new shell or add \$HOME/.local/bin to PATH."
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
  say "Existing installation detected. Upgrading ..."
  pipx upgrade memory-center || {
    say "Upgrade failed. Reinstalling ..."
    pipx uninstall memory-center >/dev/null 2>&1 || true
    pipx install "$PACKAGE_SPEC"
  }
else
  pipx install "$PACKAGE_SPEC"
fi

say ""
say "Memory Center installed."
say ""
say "Verify:"
say "  memory-center --version"
say ""
say "Example:"
say "  memory-center doctor --workspace /path/to/.memory-center/workspace.yaml --self-test"
if [[ -n "$EXTRAS" && "$INSTALL_TARGET" == git+* ]]; then
  say ""
  say "For extras on a git target, run manually after install:"
  say "  pipx inject memory-center <extra-package>"
fi
