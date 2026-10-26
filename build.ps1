# Builds into dist\:
#   FantomeFixer.exe      - graphical app (files dropped on the icon are preloaded)
#   FantomeFixer-cli.exe  - command line
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name FantomeFixer --collect-binaries zstandard run.py
python -m PyInstaller --noconfirm --onefile --console --name FantomeFixer-cli --collect-binaries zstandard run.py

Get-ChildItem dist\*.exe | ForEach-Object { Write-Host "OK: $($_.FullName)" }
