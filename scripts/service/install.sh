#!/bin/sh
set -eu
# 独立安装，不修改系统 Python；参数是本地 wheel 或发行包。
if [ "$#" -ne 1 ]; then
  echo '用法：sh scripts/service/install.sh /path/to/memory_center.whl' >&2
  exit 2
fi
install_dir="${MEMORY_CENTER_INSTALL_DIR:-$HOME/.local/share/memory-center/v5}"
python3 -m venv "$install_dir/venv"
"$install_dir/venv/bin/python" -m pip install "$1"
"$install_dir/venv/bin/memory-center-service" --help
printf '安装完成：%s\n' "$install_dir/venv/bin/memory-center-service"
