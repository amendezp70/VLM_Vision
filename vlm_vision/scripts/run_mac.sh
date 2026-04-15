#!/usr/bin/env bash
# Run VLM Vision natively on macOS (no Docker needed).
# Usage:  ./scripts/run_mac.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── Check Python ──────────────────────────────────────────────
PYTHON=""
for candidate in python3.11 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Python 3 not found. Install with:  brew install python@3.11"
    exit 1
fi

echo "Using Python: $($PYTHON --version)"

# ── Virtual environment ───────────────────────────────────────
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── Dependencies ──────────────────────────────────────────────
echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ── Environment ───────────────────────────────────────────────
if [ -f .env ]; then
    set -a; source .env; set +a
else
    echo "Warning: .env not found — copy .env.example to .env and edit it."
    echo "  cp .env.example .env"
    exit 1
fi

# ── Create data dir ──────────────────────────────────────────
mkdir -p data models

# ── Launch ────────────────────────────────────────────────────
echo "Starting VLM Vision on http://localhost:${WEBSOCKET_PORT:-8765}"
$PYTHON -m local_agent.main
