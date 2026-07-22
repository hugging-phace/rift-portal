# Build a standalone Windows .exe for the Magnet Client v2.
# Run in PowerShell on Windows with Python 3.12+ installed.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

python -m pip install --upgrade pip
python -m pip install pyinstaller
python -m pip install -r requirements-client.txt

pyinstaller --noconsole --name "MagnetClient" `
  --icon "assets\icon.ico" `
  --hidden-import base64 `
  --hidden-import ctypes `
  --hidden-import datetime `
  --hidden-import io `
  --hidden-import json `
  --hidden-import math `
  --hidden-import os `
  --hidden-import pathlib `
  --hidden-import platform `
  --hidden-import random `
  --hidden-import secrets `
  --hidden-import shutil `
  --hidden-import struct `
  --hidden-import subprocess `
  --hidden-import sys `
  --hidden-import threading `
  --hidden-import time `
  --hidden-import urllib.request `
  --hidden-import uuid `
  --hidden-import zlib `
  --hidden-import zipfile `
  --hidden-import hashlib `
  --hidden-import tempfile `
  --hidden-import certifi `
  --collect-data certifi `
  --hidden-import magnet_vision `
  --hidden-import magnet_orb `
  --hidden-import magnet_v2_glyph `
  --hidden-import PIL `
  --hidden-import PIL.Image `
  --hidden-import PIL.ImageGrab `
  --hidden-import mss `
  --add-data "Magnet Client.pyw;." `
  "Magnet Client v2.pyw"

Write-Host "Built: dist\MagnetClient"
