#!/bin/sh
set -eu
# 构建可发布的 wheel/sdist。前端产物不入库，必须先在打包前生成，
# 否则 wheel 会缺少管理页面（服务启动时会以“管理页面资源缺失”拒绝就绪）。
#
# 用法：sh scripts/service/build-release.sh
# 产物：dist/*.whl、dist/*.tar.gz
cd "$(dirname "$0")/../.."

if ! command -v node >/dev/null 2>&1; then
  echo '需要 Node.js 构建管理页面（仅打包时需要，运行时不需要）。' >&2
  exit 1
fi

echo '== 构建管理页面 =='
cd frontend
npm ci --ignore-scripts
npm run build
cd ..

if [ ! -f memory_center/service/static/index.html ]; then
  echo '前端构建未产出 memory_center/service/static/index.html，中止打包。' >&2
  exit 1
fi

echo '== 构建 wheel 与 sdist =='
python3 -m build
echo '完成：dist/'
