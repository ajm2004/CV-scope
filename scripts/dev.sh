#!/usr/bin/env bash
# Start the CV-Scope API and the frontend dev server (Linux / macOS).
#   bash scripts/dev.sh
# API:      http://127.0.0.1:8420  (docs at /api/docs)
# Frontend: http://localhost:5173  (proxies /api and /ws to the API)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "No .venv found. Run scripts/setup.sh first."
  exit 1
fi

.venv/bin/python -m pathscope.cli serve &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT
sleep 2
(cd frontend && npm run dev)
