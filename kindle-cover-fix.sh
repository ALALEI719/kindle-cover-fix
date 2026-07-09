#!/usr/bin/env bash
# Kindle 封面修复工具 - 快捷启动脚本
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

if ! "$PY" -c "import requests, PIL, ebooklib, mobi_header" >/dev/null 2>&1; then
  echo "正在安装依赖..."
  "$PY" -m pip install -r "$ROOT/requirements.txt"
fi

exec "$PY" "$ROOT/kindle_cover_fix.py" "$@"
