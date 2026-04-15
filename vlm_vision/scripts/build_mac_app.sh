#!/usr/bin/env bash
# Build VLM Vision as a standalone macOS .app bundle.
# Output: dist/VLM Vision.app
#
# Usage:  ./scripts/build_mac_app.sh
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
pip install --quiet pyinstaller

# ── Build ─────────────────────────────────────────────────────
echo "Building macOS app..."
pyinstaller scripts/vlm_vision_mac.spec --noconfirm --clean

echo ""
echo "=========================================="
echo "  Build complete!"
echo "  App:  dist/VLM Vision.app"
echo "=========================================="
echo ""
echo "Before running, make sure you have:"
echo "  1. models/metwall.onnx  in the same folder as the .app"
echo "  2. A .env file          in the same folder as the .app"
echo ""
echo "To run:  open \"dist/VLM Vision.app\""
echo "  or:    dist/VLM\\ Vision.app/Contents/MacOS/VLM\\ Vision"
