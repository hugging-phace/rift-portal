# Build a standalone Windows executable for the Magnet Agent.
# Run on Windows with Python 3.12+ installed.

python -m pip install --upgrade pip
python -m pip install pyinstaller -r ..\requirements-agent.txt

pyinstaller --noconsole --name "MagnetAgent" `
  --hidden-import magnet_vision `
  --hidden-import magnet_orb `
  --hidden-import PIL `
  --hidden-import mss `
  "..\Magnet Agent.pyw"

Write-Host "Built: dist\MagnetAgent"
