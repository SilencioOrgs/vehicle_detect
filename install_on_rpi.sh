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
echo "[1/5] Installing system dependencies..."
sudo apt update
sudo apt install -y python3-pip python3-venv \
    libopencv-dev python3-opencv libatlas-base-dev \
    libhdf5-dev libharfbuzz-dev liblapack-dev gfortran

# Create virtual environment
echo ""
echo "[2/5] Creating virtual environment..."
"$PYTHON_BIN" -m venv "$VENV_DIR" --system-site-packages
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

# Install Python packages
echo ""
echo "[3/5] Installing Raspberry Pi support packages..."
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements-rpi.txt"

# Install CPU-only PyTorch
echo ""
echo "[4/5] Checking PyTorch..."
if ! "$VENV_DIR/bin/python" -c "import torch; import torchvision" >/dev/null 2>&1; then
    echo "PyTorch not found. Attempting CPU-only install..."
    if ! "$VENV_DIR/bin/python" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu; then
        echo ""
        echo "WARNING: Could not install torch automatically."
        echo "Install a Raspberry Pi compatible CPU wheel manually:"
        echo "  $VENV_DIR/bin/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu"
    fi
else
    echo "PyTorch already installed."
fi

# Install Ultralytics after torch so pip sees a CPU torch first and keeps
# the Raspberry Pi-specific dependency set from requirements-rpi.txt.
echo ""
echo "[5/5] Checking Ultralytics..."
if ! "$VENV_DIR/bin/python" -c "from ultralytics import YOLO" >/dev/null 2>&1; then
    echo "Ultralytics not found. Attempting install..."
    if ! "$VENV_DIR/bin/python" -m pip install --no-deps ultralytics; then
        echo ""
        echo "WARNING: Could not install ultralytics automatically."
        echo "Try again after confirming torch/torchvision import cleanly:"
        echo "  $VENV_DIR/bin/python -m pip install --no-deps ultralytics"
    fi
else
    echo "Ultralytics already installed."
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
echo "Verify with:"
echo "  $VENV_DIR/bin/python -c \"import torch; print(torch.__version__)\""
echo "  $VENV_DIR/bin/python -c \"from ultralytics import YOLO; print('YOLO OK')\""
echo "  $VENV_DIR/bin/python -c \"import cv2; print('OpenCV', cv2.__version__)\""
echo ""
echo "To run:"
echo "  source $VENV_DIR/bin/activate"
echo "  python main.py"
echo ""
echo "Press Q to quit the detection window."
