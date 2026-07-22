#!/bin/bash
# Build a standalone macOS .app bundle for the Magnet Client v2.
# Run on macOS with Python 3.12+ installed.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"

python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller -r requirements-client.txt

pyinstaller --windowed --name "MagnetClient" \
  --icon "assets/icon.icns" \
  --osx-bundle-identifier "com.magnetos.client" \
  --hidden-import base64 \
  --hidden-import ctypes \
  --hidden-import datetime \
  --hidden-import io \
  --hidden-import json \
  --hidden-import math \
  --hidden-import os \
  --hidden-import pathlib \
  --hidden-import platform \
  --hidden-import random \
  --hidden-import secrets \
  --hidden-import shutil \
  --hidden-import struct \
  --hidden-import subprocess \
  --hidden-import sys \
  --hidden-import threading \
  --hidden-import time \
  --hidden-import urllib.request \
  --hidden-import uuid \
  --hidden-import zlib \
  --hidden-import zipfile \
  --hidden-import hashlib \
  --hidden-import tempfile \
  --hidden-import magnet_vision \
  --hidden-import magnet_orb \
  --hidden-import magnet_v2_glyph \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageGrab \
  --hidden-import mss \
  --add-data "Magnet Client.pyw:." \
  "Magnet Client v2.pyw"

# Ensure the main executable is executable and ad-hoc signed.
chmod +x "dist/MagnetClient.app/Contents/MacOS/MagnetClient"
codesign --force --deep --sign - "dist/MagnetClient.app"

# The client is a tray/menu-bar app; hide the dock icon.
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" \
  "dist/MagnetClient.app/Contents/Info.plist" 2>/dev/null || true

echo "Built: dist/MagnetClient.app"
