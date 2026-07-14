#!/usr/bin/env bash
# 启动 Streamlit：USB 修复封面并复制到 Kindle documents
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

if ! "$PY" -c "import streamlit" >/dev/null 2>&1; then
  echo "正在安装依赖（含 Streamlit）..."
  "$PY" -m pip install -r "$ROOT/requirements.txt"
fi

exec "$PY" -m streamlit run "$ROOT/streamlit_app.py" --server.headless true
