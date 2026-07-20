#!/bin/bash
# Build a standalone macOS .app bundle for the Magnet Agent.
# Run on macOS with Python 3.12+ installed.

set -e

python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller -r ../requirements-agent.txt

pyinstaller --windowed --name "MagnetAgent" \
  --hidden-import magnet_vision \
  --hidden-import magnet_orb \
  --hidden-import PIL \
  --hidden-import mss \
  "../Magnet Agent.pyw"

echo "Built: dist/MagnetAgent.app"
