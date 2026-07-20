# Build a standalone Windows executable for the Magnet Agent v2 UI.
# Run on Windows with Python 3.12+ installed.

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition | Split-Path -Parent
Set-Location $RepoRoot

python -m pip install --upgrade pip
python -m pip install pyinstaller -r requirements-agent.txt

pyinstaller --noconsole --name "MagnetAgent" `
  --hidden-import base64 `
  --hidden-import datetime `
  --hidden-import email.mime.multipart `
  --hidden-import email.mime.text `
  --hidden-import io `
  --hidden-import json `
  --hidden-import math `
  --hidden-import os `
  --hidden-import pathlib `
  --hidden-import platform `
  --hidden-import random `
  --hidden-import secrets `
  --hidden-import shutil `
  --hidden-import smtplib `
  --hidden-import subprocess `
  --hidden-import sys `
  --hidden-import threading `
  --hidden-import time `
  --hidden-import urllib.request `
  --hidden-import uuid `
  --hidden-import zipfile `
  --hidden-import hashlib `
  --hidden-import tempfile `
  --hidden-import magnet_vision `
  --hidden-import magnet_orb `
  --hidden-import magnet_v2_glyph `
  --hidden-import PIL `
  --hidden-import PIL.Image `
  --hidden-import PIL.ImageGrab `
  --hidden-import mss `
  --add-data "Magnet Agent v2 Prototype.pyw;." `
  --add-data "Magnet Agent.pyw;." `
  "Magnet Agent v2.pyw"

Write-Host "Built: dist\MagnetAgent"
