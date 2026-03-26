#!/bin/bash
# ============================================================
# One-step installer for Raspberry Pi 4B (Bookworm)
# Usage: chmod +x install_on_rpi.sh && ./install_on_rpi.sh
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "=============================================="
echo "  Vehicle Detection & Counter — RPi Installer"
echo "=============================================="
echo "Project directory: $PROJECT_DIR"

# Check Python
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Error: $PYTHON_BIN not found. Install Python 3 first." >&2
    exit 1
fi
echo "Using Python: $(command -v "$PYTHON_BIN")"

# Install system dependencies
echo ""
echo "[1/4] Installing system dependencies..."
sudo apt update
sudo apt install -y python3-pip python3-venv \
    libopencv-dev python3-opencv libatlas-base-dev \
    libhdf5-dev libharfbuzz-dev liblapack-dev gfortran

# Create virtual environment
echo ""
echo "[2/4] Creating virtual environment..."
"$PYTHON_BIN" -m venv "$VENV_DIR" --system-site-packages
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

# Install Python packages
echo ""
echo "[3/4] Installing Python packages..."
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements-rpi.txt"

# Try to install torch
echo ""
echo "[4/4] Checking PyTorch..."
if ! "$VENV_DIR/bin/python" -c "import torch" >/dev/null 2>&1; then
    echo "PyTorch not found. Attempting install..."
    if ! "$VENV_DIR/bin/python" -m pip install torch; then
        echo ""
        echo "WARNING: Could not install torch automatically."
        echo "Install a Raspberry Pi compatible torch wheel manually:"
        echo "  $VENV_DIR/bin/python -m pip install /path/to/torch.whl"
    fi
else
    echo "PyTorch already installed."
fi

# Check model file
if [ ! -f "$PROJECT_DIR/yolo11n.pt" ]; then
    echo ""
    echo "NOTE: yolo11n.pt not found. It will be auto-downloaded on first run."
fi

echo ""
echo "=============================================="
echo "  Install complete!"
echo "=============================================="
echo ""
echo "To run:"
echo "  source $VENV_DIR/bin/activate"
echo "  python main.py"
echo ""
echo "Press Q to quit the detection window."
