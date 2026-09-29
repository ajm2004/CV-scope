#!/usr/bin/env bash
# CV-Scope setup for Linux / macOS.
# Creates .venv, installs the backend (CUDA PyTorch when an NVIDIA driver is present),
# installs the frontend, downloads sample videos and applies database migrations.
#
#   bash scripts/setup.sh [--cpu] [--no-samples]
set -euo pipefail
cd "$(dirname "$0")/.."

CPU=0
SAMPLES=1
for arg in "$@"; do
  case "$arg" in
    --cpu) CPU=1 ;;
    --no-samples) SAMPLES=0 ;;
  esac
done

step() { printf "\n== %s\n" "$1"; }

step "Python virtual environment (.venv)"
if [ ! -d .venv ]; then
  PY=python3
  command -v python3.11 >/dev/null 2>&1 && PY=python3.11
  "$PY" -m venv .venv
fi
PIP=".venv/bin/python -m pip"
$PIP install --upgrade pip >/dev/null

step "PyTorch"
if [ "$CPU" = "0" ] && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  echo "NVIDIA GPU detected: installing CUDA 12.6 build"
  $PIP install torch torchvision --index-url https://download.pytorch.org/whl/cu126
elif [ "$(uname -s)" = "Darwin" ]; then
  echo "macOS: installing default build (Metal/MPS supported on Apple silicon)"
  $PIP install torch torchvision
else
  echo "Installing CPU build"
  $PIP install torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi

step "Backend package"
$PIP install -e "backend[ultralytics,onnx-cpu,export,dev]"

step "Frontend dependencies"
(cd frontend && npm install --no-audit --no-fund)

step "Database"
.venv/bin/python -m pathscope.cli migrate

if [ "$SAMPLES" = "1" ]; then
  step "Sample videos (CC-BY-4.0)"
  .venv/bin/python scripts/download_samples.py || true
fi

step "Hardware summary"
.venv/bin/python -m pathscope.cli hardware

printf "\nDone. Start CV-Scope with:  bash scripts/dev.sh\nThen open http://localhost:5173\n"
